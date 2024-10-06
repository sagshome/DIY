import copy
import csv
import logging
import pandas as pd

from datetime import datetime, date
from typing import List, Dict

from django.contrib.auth.models import User

from .models import Equity, EquityAlias, Account, EquityValue, EquityEvent, Transaction, DataSource, AV_API_KEY
from base.utils import normalize_date, DIYImportException


FUND = Transaction.FUND
BUY = Transaction.BUY
SELL = Transaction.SELL
INT = Transaction.INTEREST
REDEEM = Transaction.REDEEM
FEES = Transaction.FEES
REINVESTED = Transaction.REDIV
SPLIT = 11
TFSA_TRANSFER = 12
JUNK = 13
DIV = 14
TRANSFER_IN = 15
TRANSFER_OUT = 16

logger = logging.getLogger(__name__)

HEADERS = {
    'default': {
        'Date': 'Date', 'AccountName': 'AccountName', 'AccountKey': 'AccountKey', 'Symbol': 'Symbol',
        'Description': 'Description', 'XAType': 'XAType', 'Currency': 'Currency',  'Quantity': 'Quantity',
        'Price': 'Price', 'Amount': 'Amount'
    }
}

SPLIT_MESSAGE = 'Stock split detected,  only the admin can update prior dividends.   They have been contacted'


class StockImporter:
    """
    Pull the CSV file into a pd structure, so we can sort it.   Sorting is required, so we can calculate the dividends
    based on the amount of shares owned.
    """
    default_pd_columns = ['Date', 'AccountName', 'AccountKey', 'Symbol', 'Description', 'XAType', 'Currency',
                          'Quantity', 'Price', 'Amount']

    def __init__(self, currency: str, reader: csv.reader, user: User, headers: Dict[str, str], managed: bool = False):
        self.warnings = []
        self.user = user
        self.managed = managed
        self.headers = headers  # A dictionary map for csv_columns to pd_columns
        self._columns = copy.deepcopy(self.default_pd_columns)
        self.added_columns = set(self.headers.keys()) - set(self._columns)
        for new_column in self.added_columns:
            self._columns.append(new_column)
        self.pd = pd.DataFrame(columns=self._columns)
        self.accounts: Dict[str, Account] = {}
        self.equities: Dict[str, Equity] = {}
        self.new_account_currency = currency
        self.mappings = self.get_headers(reader)

        for row in reader:
            xa_date: date = self.csv_date(row)  # Normalize and format date (need to override if date format is off)
            if xa_date:  # Skip blank lines
                account_name: str = row[self.mappings['AccountName']]
                account_key: str = self.csv_account_key(row)
                symbol: str = self.csv_symbol(row)
                description: str = self.csv_description(row)
                xa_type: int = self.csv_xa_type(row)
                currency: str = row[self.mappings['Currency']]
                price: float = self.csv_price(row)
                quantity: float = self.csv_quantity(row)
                amount: float = self.csv_amount(row)
                if xa_type:
                    self.pd.loc[len(self.pd.index)] = self.add_extra_data(row,[xa_date, account_name, account_key,
                                                                       symbol, description, xa_type, currency,
                                                                      quantity, price, amount])
                else:
                    self.warnings.append(f'{xa_date}:{symbol} - Can not determine transaction type')

        self.pd['Date'] = pd.to_datetime(self.pd['Date'])
        self.pd = self.pd.sort_values(['Date', 'AccountKey', 'XAType'], ascending=[True, True, True])

    def process(self):
        equity_totals = {}  # Needed to calculate dividends on a specific date
        last_import = None
        for _, prow in self.pd.iterrows():
            do_process: bool = True
            this_date: date = self.pd_date(prow)
            norm_date = normalize_date(this_date)
            symbol: str = self.pd_symbol(prow)
            name: str = self.pd_description(prow)
            xa_action: int = self.pd_xa_type(prow)
            amount: float = self.pd_amount(prow)
            currency: str = self.pd_currency(prow)
            region = 'Canada' if currency == 'CAD' else 'US'
            price = self.pd_price(prow)
            quantity = self.pd_quantity(prow)
            equity: Equity

            #
            account: Account = self.get_or_create_account(self.user, self.pd_account_name(prow), self.pd_account_key(prow), self.new_account_currency)
            if account.account_name not in equity_totals:
                equity_totals[account.account_name] = {}
            if not account.last_import or (this_date > account.last_import):

                last_import = this_date  # This has been pre-ordered by date

                if xa_action == FUND:
                    Transaction(real_date=this_date, account=account, user=self.user, value=amount, xa_action=FUND, quantity=0, price=0).save()
                elif xa_action == REDEEM:
                    Transaction(real_date=this_date, account=account, user=self.user, value=amount * -1, xa_action=REDEEM, quantity=0, price=0).save()
                elif xa_action == JUNK:
                    pass
                elif xa_action == INT:
                    Transaction(real_date=this_date, account=account, user=self.user, value=amount, xa_action=INT, quantity=quantity, price=price).save()
                elif xa_action == FEES:
                    Transaction(real_date=this_date, account=account, user=self.user, value=amount * -1, xa_action=FEES, quantity=quantity, price=price).save()

                elif xa_action == DIV:
                    equity = self.equity_lookup(symbol, self.pd_description(prow), region)
                    if not equity.searchable:
                        value = amount / equity_totals[account.account_name][equity.key]
                        if value != 0:  # CIBC stock split.  Best to handled it manually because dividends are screwy
                            EquityEvent.get_or_create(equity=equity, real_date=this_date, value=value, event_type='Dividend', source=DataSource.UPLOAD.value)
                        if price != 0:
                            EquityValue.get_or_create(equity=equity, real_date=this_date, price=price, source=DataSource.UPLOAD.value)
                else:  # Things that deal with equities
                    if symbol:
                        equity = self.get_or_create_equity(symbol, name, currency, region, False)
                        if equity.key not in equity_totals[account.account_name]:
                            equity_totals[account.account_name][equity.key] = 0  # First purchase
                        equity_totals[account.account_name][equity.key] += quantity

                        if xa_action in [BUY, REINVESTED, TRANSFER_IN, SPLIT]:
                            if not xa_action == SPLIT:
                                if amount and quantity:
                                    price = amount / quantity  # Sometimes amount includes fees!
                                else:
                                    price = price if price else EquityValue.lookup_price(equity, this_date)
                            else:
                                price = 0

                            action = Transaction.BUY if xa_action != REINVESTED else Transaction.REDIV
                            amount = amount if amount else price * quantity
                            Transaction(real_date=this_date, account=account, equity=equity, user=self.user, value=amount, xa_action=action, quantity=quantity, price=price).save()

                        elif xa_action in [SELL, TRANSFER_OUT]:
                            if amount and quantity:
                                price = amount / quantity  # Sometimes amount includes fees!,  quantity will be negative
                            else:
                                price = price if price else EquityValue.lookup_price(equity, this_date)

                            amount = amount if amount else price * quantity
                            Transaction(real_date=this_date, account=account, equity=equity, user=self.user, value=amount * -1, xa_action=SELL, quantity=quantity * -1, price=price).save()
                        elif xa_action == TFSA_TRANSFER:
                            price = EquityValue.lookup_price(equity, normalize_date(this_date))
                            amount = amount if amount else price * quantity
                            if quantity < 0:
                                Transaction(real_date=this_date, account=account, equity=equity, user=self.user, value=amount * -1 , xa_action=SELL,
                                                           quantity=quantity * -1, price=price).save()
                                Transaction(real_date=this_date, account=account, user=self.user, value=amount * -1, xa_action=REDEEM).save()
                            elif quantity > 0:
                                Transaction(real_date=this_date, account=account, equity=equity, user=self.user, value=amount, xa_action=BUY,
                                                           quantity=quantity, price=price).save()
                                Transaction(real_date=this_date, account=account, user=self.user, value=amount, xa_action=FUND).save()
                        else:
                            raise DIYImportException(f'Unexpected Activity type {xa_action}')

        # Finally update everything possible
        for account in self.accounts:
            if (not self.accounts[account].last_import) or (last_import and (self.accounts[account].last_import < last_import)):
                self.accounts[account].last_import = last_import
                self.accounts[account].save()  # Will update last import if anything was done,  if not then not harm.
            for equity in self.accounts[account].equities:
                if self.user.is_superuser or self.user.profile.av_api_key:
                    key = self.user.profile.av_api_key if self.user.profile.av_api_key else AV_API_KEY
                    equity.update(force=False, key=key)
                else:
                    equity.fill_equity_value_holes()
            self.accounts[account].update_static_values()

    def get_headers(self, csv_reader):
        if set(self._columns) - set(self.headers.keys()):
            missing = str(set(self._columns) - set(self.headers.keys()))
            raise DIYImportException('CSV, required column(s) are missing (%s)' % missing)

        header = next(csv_reader)
        fixed_header = []
        for h in header:
            fixed_header.append(h.encode(encoding="ascii",errors="ignore").decode('ascii'))

        return_dict = {}
        for column in self.headers:
            return_dict[column] = fixed_header.index(self.headers[column])
        return return_dict

    # These setters are used so that subclassed importers can override the default value

    @staticmethod
    def strip_value(value) -> str:
        """
        numbers may come in as nnn, -nnn, $nnn, -$nnn
        """
        negative = False
        if value and value[0] == '-':
            negative = True
            value = value[1:]
        value = value if value and not value[0] == '$' else value[1:]
        value = '-' + value if value and negative else value
        return value.replace(',','')

    def csv_symbol(self, row) -> str:
        return row[self.mappings['Symbol']]

    def csv_date(self, row) -> date:
        try:
            data = row[self.mappings['Date']]
            if data:
                try:
                    return datetime.strptime(data, '%Y-%m-%d %H:%M:%S %p')
                except ValueError:  # pragma: no cover
                    logger.debug('Invalid date %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No date on row %s' % row)
        return None

    def csv_price(self, row) -> float:
        value = self.strip_value(row[self.mappings['Price']])
        if value:
            try:
                value = float(value)
            except ValueError:
                logger.error('Failed to convert Price:%s to a floating point number' % row)
                value = 0
        else:
            value = 0
        return value

    def csv_quantity(self, row) -> float:
        value = row[self.mappings['Quantity']]
        if value:
            try:
                value = float(value)
            except ValueError:
                logger.error('Failed to convert Quantity:(%s) to a floating point number' % row)
                value = 0
        else:
            value = 0
        return value

    def csv_amount(self, row) -> float:
        value = self.strip_value(row[self.mappings['Amount']])
        if value:
            try:
                value = float(value)
            except ValueError:
                logger.error(f'Failed to convert Amount:%s to a floating point number' % row)
                value = 0
        else:
            value = 0
        return value

    def csv_xa_type(self, row) -> int:
        csv_value = row[self.mappings['XAType']]
        return Transaction.TRANSACTION_MAP[csv_value]

    def csv_description(self, row) -> str:
        return row[self.mappings['Description']]

    def csv_account_key(self, row) -> str:
        return row[self.mappings['AccountKey']]

    @staticmethod
    def pd_get(row, key):
        return row[key]

    def pd_symbol(self, row) -> str:
        return self.pd_get(row, 'Symbol')

    def pd_account_name(self, row) -> str:
        return self.pd_get(row, 'AccountName')

    def pd_account_key(self, row) -> str:
        return self.pd_get(row, 'AccountKey')

    def pd_description(self, row) -> str:
        return self.pd_get(row, 'Description')

    def pd_date(self, row) -> date:
        return self.pd_get(row, 'Date').date()

    def pd_price(self, row) -> float:
        return abs(float(self.pd_get(row, 'Price')))

    def pd_quantity(self, row) -> float:
        return abs(float(self.pd_get(row, 'Quantity')))

    def pd_amount(self, row) -> float:
        return abs(float(self.pd_get(row, 'Amount')))

    def pd_xa_type(self, row) -> int:
        return self.pd_get(row, 'XAType')

    def pd_currency(self, row) -> str:
        return self.pd_get(row, 'Currency')

    def add_extra_data(self, row, existing) -> List:
        """
        Adding data from the input dict to the columns
        :param row:
        :param existing:
        :return:
        """
        for added in self.added_columns:
            existing.append(row[self.mappings[added]])
        return existing

    def equity_lookup(self, symbol: str, name: str, region: str):
        lookup = symbol + '.' + region
        if lookup not in self.equities:
            try:
                equity = Equity.objects.get(symbol=symbol, region=region)
            except Equity.DoesNotExist:
                try:
                    alias = EquityAlias.objects.get(symbol=lookup)
                    equity = alias.equity
                except EquityAlias.DoesNotExist:
                    equity = EquityAlias.find_equity(name, region)
                    if not equity:
                        raise DIYImportException(f'Failed to lookup {symbol} - {name} @ {region}')
            self.equities[lookup] = equity
        return self.equities[lookup]

    def get_or_create_equity(self, symbol: str, name: str, currency: str, region: str, managed: bool):
        """
        Given a symbol,  and a descriptive name - do your best to lookup and / or create a new equity
        :param symbol:  The basic for the search
        :param name:  The text description
        :param currency: Used to pick region and possible symbol decorations
        :param managed:  Used to determine MoneyMarket vs MutualFund for managed accounts
        :return:
        """

        try:
            equity = self.equity_lookup(symbol, name, region)
        except DIYImportException:
            equity = Equity.objects.create(symbol=symbol, name=name, region=region, currency=currency)
            if not equity.equity_type:
                if equity.name.find(' ETF') != -1:
                    equity.equity_type = 'ETF'
            elif not managed:
                equity.equity_type = 'Equity'
            elif name.find('%') != -1 or name.find('SAVINGS') != -1:
                equity.equity_type = 'MM'
            else:
                equity.equity_type = 'MF'
            equity.save()

        if not equity:  # pragma: no cover
            raise DIYImportException(f'Could not create/lookup equity {symbol} - {name}')

        lookup = symbol + '.' + region
        if not EquityAlias.objects.filter(symbol=lookup, name=name, region=region).exists():
            EquityAlias.objects.create(symbol=lookup, name=name, equity=equity, region=region)

        equity.update_external_equity_data(force=False)   # This will only happen once a day.
        self.equities[lookup] = equity
        return self.equities[lookup]

    def get_or_create_account(self, user, name, account_id, base_currency):
        """

        :param user: what
        :param name: The account name we import as
        :param account_id:  The account id we are going to use as a none changable key
        :return:
        """
        if account_id not in self.accounts:
            account: Account
            try:
                account = Account.objects.get(account_name=account_id, user=user)
            except Account.DoesNotExist:
                account = Account(name=name, user=user, account_name=account_id, managed=self.managed, currency=base_currency)
                account.save()
                account = Account.objects.get(account_name=account_id, user=user)  # Refresh
            self.accounts[account_id] = account
        return self.accounts[account_id]

    @staticmethod
    def fill_value_holes():
        """
        Inporting based on transactions leaves a lot of holes in price data.    This function will fill those holes
        with estimated data based on price changes between data points.

        :return:
        """
        for equity in Equity.objects.all():
            equity.fill_equity_value_holes()


class Manulife(StockImporter):
    """
    Downloaded my transactions from manulife and looking to import them
    :param file_name:
    :return:
    """

    ManulifeKeys = {
        'AccountKey': 'Account Number',
        'AccountName': 'Account',
        'Description': 'Investment Name',
        'Symbol': 'Symbol',
        'XAType': 'Transaction Type',
        'Currency': 'Currency',
        'Quantity': 'Unit Quantity',
        'Price': 'Price',
        'Amount': 'Net Amount',
        'Date': 'Process Date',
    }

    def __init__(self, currency: str, file_name: csv.reader, user: User):
        super().__init__(currency, file_name, user, self.ManulifeKeys, managed=True)

    def csv_xa_type(self, row) -> int:
        csv_value = row[self.mappings['XAType']]
        if csv_value in ['Purchase', 'Switch In', 'Transfer In - External']:
            return BUY
        if csv_value == 'Transfer Out - External':
            return REDEEM
        if csv_value in ['Redemption', 'Switch Out']:
            return SELL
        if csv_value == 'Deposit':
            return FUND
        elif csv_value == 'Reinvested Dividend/Interest':
            return REINVESTED
        elif csv_value in ['Fee Rebate', 'Cash Dividend/Interest']:
            return INT
        else:
            logger.error('Unexpected XA Type:%s' %  csv_value)
            return JUNK

    def csv_date(self, row) -> date:
        try:
            data = row[self.mappings['Date']]
            if data:
                try:
                    return datetime.strptime(row[self.mappings['Date']], '%Y-%m-%d')
                except ValueError:
                    logger.debug('Invalid date %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No Date on row %s' % row)
        return None

    def csv_account_key(self, row) -> str:
        return 'Manulife_' + super().csv_account_key(row)


class ManulifeWealth(StockImporter):
    """
    Downloaded my transactions from manulife Wealthand looking to import them
    :param file_name:
    :return:
    """

    ManulifeKeys = {
        'AccountKey': 'Account Number',
        'AccountName': 'Account Type',
        'Description': 'Description',
        'Symbol': 'Symbol',
        'XAType': 'Transaction Type',
        'Currency': 'Account Currency',
        'Quantity': 'Quantity',
        'Price': 'Price (Trade Currency)',
        'Amount': 'Total Value (Account Currency)',
        'Date': 'Date',
    }

    def __init__(self, currency: str, file_name: csv.reader, user: User):
        super().__init__(currency, file_name, user, self.ManulifeKeys, managed=True)

    def csv_xa_type(self, row) -> int:
        csv_value = row[self.mappings['XAType']]
        #if csv_value in ['Conversion',]:
        #    if row[self.mappings['Quantity']] == 0:
        #        return INT
        #    return TRANSFER_IN
        if csv_value in ['Buy', ]:
            return BUY
        if csv_value == 'Transfer Out - External':  # Do not know,  we have not ever withdrawn funds
            return REDEEM
        if csv_value in ['Sell',]:
            return SELL
        elif csv_value in ['Div Re-inv','Mut Fd Reinv Mgmt Fee Reb', 'Reinv Div', 'Trust Inc & Prtnr DRIP']:
            return REINVESTED
        elif csv_value == 'Dividend':
            return INT
        elif csv_value in ['Conversion Buy', 'Conversion Entry', 'Conversion']:
            return JUNK
        elif csv_value == 'Tfsa Contribution':
            return TFSA_TRANSFER
        else:
            logger.error('Unexpected XA Type:%s' %  csv_value)
            return JUNK

    def csv_date(self, row) -> date:
        try:
            data = row[self.mappings['Date']]
            if data:
                try:
                    return datetime.strptime(row[self.mappings['Date']], '%m/%d/%Y')
                except ValueError:
                    logger.debug('Invalid date %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No Date on row %s' % row)
        return None

    def csv_account_key(self, row) -> str:
        return 'ManulifeWealth_' + super().csv_account_key(row)


class QuestTrade(StockImporter):

    QuestTradeKeys = {
        'AccountName': 'Account Type',
        'Description': 'Description',
        'Symbol': 'Symbol',
        'XAType': 'Activity Type',
        'Currency': 'Currency',
        'Quantity': 'Quantity',
        'Price': 'Price',
        'Amount': 'Net Amount',
        'Date': 'Settlement Date',
        'Action': 'Action',
        'Fees': 'Commission',
        'AccountKey': 'Account #'
    }

    def __init__(self, currency, reader: csv.reader,  user):
        super().__init__(currency, reader, user, self.QuestTradeKeys, managed=False)

    def csv_xa_type(self, row) -> int:
        csv_value = row[self.mappings['XAType']]
        action = row[self.mappings['Action']]
        if csv_value == 'Deposit':
            return FUND
        if csv_value == 'Trades':
            if action == 'Buy':
                return BUY
            elif action == 'Sell':
                return SELL
            else:
                logger.error("Unexpected XA value:%s Source %s(%s) and %s(%s)" % (
                    csv_value, self.mappings['XAType'], row[self.mappings['XAType']],
                    self.mappings['Action'], row[self.mappings['Action']]))
                return JUNK
        elif csv_value == 'Dividends':
            if action == 'DIS':
                return SPLIT
            return DIV
        elif csv_value == 'Interest':  # pragma: no cover
            return INT
        elif csv_value in ['Fees and rebates', 'Transfers', 'Other']:
            amount = self.csv_amount(row)
            if amount > 0:
                return INT
            elif amount < 0:
                return FEES
            else:
                return JUNK
        elif csv_value in ['Deposits', 'Withdrawals']:
            amount = self.csv_amount(row)
            if amount >= 0:
                return FUND
            else:
                return REDEEM
        elif csv_value == 'FX conversion':
            return JUNK  # We use BOC conversation rates
        else:
            logger.error("Unexpected XA value:%s Source %s(%s)" % (
                csv_value, self.mappings['XAType'], row[self.mappings['XAType']]))

    def csv_price(self, row) -> float:
        try:
            price = float(row[self.mappings['Price']])
            if price:
                quantity = self.csv_quantity(row)
                if quantity != 0:  # On trades we have fees with Questtrade
                    try:
                        fees = float(row[self.mappings['Fees']])
                        return (price * quantity + fees * -1) / quantity
                    except ValueError:
                        logger.error('Could not convert commission (%s) to a value' % row[self.mappings['Fees']])
            return price
        except ValueError:
            logger.error('Could not convert price (%s) to a value' % row[self.mappings['Price']])
            return 0

    def csv_symbol(self, row) -> str:
        symbol = super().csv_symbol(row)
        if symbol and symbol[0] == '.':  # Dividends are often reported as '.symbol'
            symbol = symbol[1:]

        parts = symbol.split('.')
        parts_cnt = len(parts)
        if parts_cnt > 1 and parts[parts_cnt - 1] == 'TO':
            prefix = '-'.join(parts[:parts_cnt - 1])
            symbol = prefix
        else:
            symbol = '-'.join(parts)
        return symbol

    def csv_description(self, row):
        value = super().csv_description(row)
        if 'CASH DIV ON' in value:
            return value.split('CASH DIV ON')[0].rstrip()
        if 'WE ACTED AS AGENT' in value:
            return value.split('WE ACTED AS AGENT')[0].rstrip()
        if 'DIST ON' in value:
            return value.split('DIST ON')[0].rstrip()
        return value

    def csv_account_key(self, row) -> str:
        return 'QuestTrade_' + super().csv_account_key(row)
