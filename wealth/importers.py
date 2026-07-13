import logging
import numpy as np
import pandas as pd

from pandas.tseries.offsets import BDay

from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import List, Union

from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile

from base.models import API, DataSource
from .models import Account, Portfolio, CashFlow, Funding, Investment, Transaction, Value, ValueBalance, Dividend, clear_caches

logger = logging.getLogger(__name__)


FUND = 1
BUY = 2
SELL = 3
REDEEM = 4
CASH = 5

JUNK = 99


users = {user.username: user for user in User.objects.all()}
accounts = {account.id: account for account in Account.objects.all()}
portfolios = {portfolio.id: portfolio for portfolio in Portfolio.objects.all()}
investments = {investment.symbol: investment for investment in Investment.objects.all()}

account_transl = {}
portfolio_transl = {}


def get_or_add_user(username: str) -> User:
    if username not in users:
        try:
            user = User.objects.get(username=username)
            users[username] = user
        except User.DoesNotExist:
            print(f'    {datetime.now()} - Creating {username}')
            users[username] = User.objects.create_user(username)

    return users[username]


def get_or_add_account(pk: int, account: str, account_name: str, account_type: str, currency: str, managed: str, username: str, portfolio) -> Account:
    if pk not in account_transl:
        user = get_or_add_user(username)
        try:
            account = Account.objects.get(name=account, user=user)
        except Account.DoesNotExist:
            print(f'    {datetime.now()} - Creating Account:{account_name}')
            acc_type = 'Trading' if account_type == 'Investment' else 'Value' if account_type == 'Value' else 'Cash'
            managed = True if acc_type in ['Value', 'Cash'] else managed
            account = Account.objects.create(name=account, account_name=account_name, acct_type=acc_type, managed=managed, currency=currency, portfolio=portfolio, user=user)
        account_transl[pk] = account.id
        accounts[account.id] = account
    return accounts[account_transl[pk]]


def get_or_add_portfolio(pk: int, name: str, currency:str, user: User):
    if pk not in portfolio_transl:
        try:
            portfolio = Portfolio.objects.get(name=name, user=user)
        except Portfolio.DoesNotExist:
            print(f'    {datetime.now()} - Creating Portfolio:{name}')
            portfolio = Portfolio.objects.create(name=name, currency=currency, user=user)
        portfolio_transl[pk] = portfolio.id
        portfolios[portfolio.id] = portfolio
    return portfolios[portfolio_transl[pk]]


def get_investment(symbol: str, region: str=None, set_default: bool = False) -> str:
    if region == 'Canada' and not (symbol.endswith('.TO') or symbol.endswith('.NE')):
        if f'{symbol}.TO' in investments:
            symbol = f'{symbol}.TO'
        elif f'{symbol}.NE' in investments:
            symbol = f'{symbol}.NE'

    if symbol not in investments:
        try:
            investments[symbol] = Investment.objects.get(symbol=symbol)
        except Investment.DoesNotExist:
            result = Investment.test_symbol(symbol, region)
            symbol = symbol if set_default and not result else result
    return symbol


def get_or_add_investment(symbol: str, name: str=None, region: str=None) -> Investment:

    symbol = get_investment(symbol, region, set_default=True)
    if symbol not in investments:

        print(f'    {datetime.now()} - Creating Investment:{symbol}')
        investment = Investment(symbol=symbol, name=name)
        investment.validate()
        investment.save(update=True)
        investments[symbol] = investment
    return investments[symbol]


def prune_imported(imported: pd.DataFrame, actions: List[str]) -> (pd.DataFrame, pd.DataFrame):
    new_list = []
    for action in actions:
        new_list.append(imported.loc[imported['action'] == action])
    if len(new_list) == 0:
        return imported, pd.DataFrame()
    if len(new_list) == 1:
        new_df = new_list[0]
    else:
        new_df = pd.concat(new_list)

    to_remove = imported.merge(new_df, how='left', indicator=True)
    return to_remove[to_remove['_merge'] == 'left_only'].drop(columns='_merge'), new_df


def prune_existing(cls, imported, compare_keys):
    for mandatory in ['date', 'account__id']:
        if mandatory not in compare_keys:
            logger.error('Missing mandatory key:%s' % mandatory)
            return pd.DataFrame()
    existing = pd.DataFrame(cls.objects.values(*compare_keys))
    if existing.empty:
        return imported

    #existing['date'] = pd.to_datetime(existing['date'])
    removed = (
        imported.merge(
            existing[compare_keys],
            on=compare_keys,
            how='left',
            indicator=True
        )
        .query('_merge == "left_only"')
        .drop(columns='_merge')
    )
    return removed


def import_apis():
    input_file = Path.home().joinpath('API.csv')
    df = pd.read_csv(input_file)
    for row in df.itertuples(index=False):
        API.objects.update_or_create(name=row.name, defaults={'base': row.base})


def import_accounts():
    input_file = Path.home().joinpath('Accounts.csv')
    df = pd.read_csv(input_file)
    df['portfolio__id'] = df['portfolio__id'].fillna(0)
    for row in df.itertuples(index=False):
        user = get_or_add_user(row.user__username)
        if row.portfolio__id != 0:
            portfolio = get_or_add_portfolio(row.portfolio__id, row.portfolio__name, row.portfolio__currency, user)
        else:
            portfolio = None
        get_or_add_account(row.id, row.name, row.account_name, row.account_type, row.currency, row.managed, user.username, portfolio=portfolio)


def import_funding(df):
    print(f'{datetime.now()} - Starting Funding Import')
    funds = prune_existing(Funding, df, ['date', 'account__id'])
    for row in funds.itertuples(index=False):
        if row.account__id in account_transl:
            process_date = row.date
            value = row.value
            if value > 0:
                Funding.deposit(account=accounts[account_transl[row.account__id]], amount=value, this_date=process_date, source=DataSource.IMPORT.value, note=row.action)
            elif value < 0:
                Funding.withdraw(account=accounts[account_transl[row.account__id]], amount=value, this_date=process_date, source=DataSource.IMPORT.value, note=row.action)
        else:
            print(f'Funding, skipping no account inforation for {row.account__id}')
    print(f'{datetime.now()} - Ending Funding Import')


def import_xas(df):
    print(f'{datetime.now()} - Starting Transaction Import')

    xas = prune_existing(Transaction, df, ['date', 'account__id'])
    for row in xas.itertuples(index=False):
        if row.account__id in account_transl:
            investment = get_or_add_investment(row.equity__symbol, row.equity__name)
            process_date = row.date
            note = None
            if row.price == 0:
                note = 'Reinvested' if row.quantity > 0 else 'Fees/Charges'
            if row.quantity > 0:
                Transaction.buy(account=accounts[account_transl[row.account__id]], price=row.price, quantity=row.quantity, this_date=process_date, investment=investment, note=note, source=DataSource.IMPORT.value)
            else:
                Transaction.sell(account=accounts[account_transl[row.account__id]], price=row.price, quantity=row.quantity, this_date=process_date, investment=investment, note=note, source=DataSource.IMPORT.value)

        else:
            print(f'XA, skipping no account inforation for {row.account__id}')

    print(f'{datetime.now()} - Ending Transaction Import')


def import_reinvested(df):
    print(f'{datetime.now()} - Starting ReInvestment Import')

    reinvested = prune_existing(Transaction, df, ['date', 'account__id'])
    for row in reinvested.itertuples(index=False):
        if row.account__id in account_transl:
            investment = get_or_add_investment(row.equity__symbol, row.equity__name)
            process_date = row.date
            if row.quantity > 0:
                Transaction.buy(account=accounts[account_transl[row.account__id]], price=0, quantity=row.quantity, this_date=process_date, investment=investment, note='Reinvested', source=DataSource.IMPORT.value)
        else:
            print(f'Reinvested, skipping no account inforation for {row.account__id}')

    print(f'{datetime.now()} - Ending ReInvestment Import')


def import_cash(df):
    print(f'{datetime.now()} - Starting Cash Import')
    cash = prune_existing(CashFlow, df, ['date', 'account__id'])
    for row in cash.itertuples(index=False):
        print(f'   CashFlow {row.account__id}')
        if row.account__id in account_transl:
            if accounts[account_transl[row.account__id]].acct_type != 'Value':
                process_date = row.date
                value = row.value
                logger.debug('Skipping CASH on %s for %s value:$%s $%s' % (process_date, accounts[account_transl[row.account__id]], value, row.action))
                continue
                CashFlow(account=accounts[account_transl[row.account__id]], value=value, date=process_date, note=row.action, source=DataSource.IMPORT.value).save(rebuild=False)
        else:
            print(f'Cash, skipping no account inforation for {row.account__id}')

    print(f'{datetime.now()} - Ending Cash Import')


def coerce_business_day_preserve_month(s):
    fri = s - BDay(0)
    mon = s + BDay(0)
    weekend = s.dt.weekday >= 5
    month_change = fri.dt.month != s.dt.month
    return s.where(~weekend, fri.where(~month_change, mon))


def import_from_diy():

    import_apis()
    import_accounts()

    df = pd.read_csv(Path.home().joinpath('Transactions.csv'))
    df['date'] = pd.to_datetime(df['real_date'])
    df['date'] = coerce_business_day_preserve_month(df['date'])
    df['date'] = df['date'].dt.date

    # Split out import into IOOM compatible chunks
    df, funds = prune_imported(df, ['Deposit', 'Withdraw', 'Transfer In', 'Transfer Out'])
    df, xas = prune_imported(df, ['Buy', 'Sell'])
    df, reinvested = prune_imported(df, ['Reinvested Dividend',])
    df, cash = prune_imported(df, ['Dividends/Interest', 'Fees Paid'])

    import_funding(funds)
    import_xas(xas)

    import_reinvested(reinvested)
    import_cash(cash)

    now = pd.to_datetime('now', utc=True)
    print(f'{datetime.now()} - Starting EquityValues Import')

    input_file = Path.home().joinpath('EquityValues.csv')
    df = pd.read_csv(input_file)
    df['date'] = pd.to_datetime(df['real_date'])
    df['date'] = coerce_business_day_preserve_month(df['date'])

    for symbol in df['equity__symbol'].unique():
        try:
            earliest = Value.objects.filter(investment__symbol=symbol).earliest('date').date
            idf = df.loc[(df['date'] < pd.Timestamp(earliest)) & (df['equity__symbol'] == symbol)]
        except Value.DoesNotExist:
            idf = df.loc[df['equity__symbol'] == symbol]

        for row in idf.itertuples(index=False):
            if row.equity__symbol in investments:
                investment = investments[row.equity__symbol]
                Value.create_values(investment, row.date, row.price, row.source)
    print(f'{datetime.now()} - Ending EquityValues Import')

    print(f'{datetime.now()} - Starting FundValues Import')
    input_file = Path.home().joinpath('FundValues.csv')
    df = pd.read_csv(input_file)
    df['date'] = pd.to_datetime(df['real_date'], utc=True)
    df['date'] = coerce_business_day_preserve_month(df['date'])
    df.sort_values(['equity__symbol', 'date'], inplace=True)

    for symbol in df['equity__symbol'].unique():
        idf = df.loc[df['equity__symbol'] == symbol]
        previous = -1
        for row in idf.itertuples(index=False):
            if row.account__id in account_transl:
                account = accounts[account_transl[row.account__id]]
                if row.value == 0 and previous == 0:
                    continue
                previous = row.value
                if account.acct_type == 'Value':
                    ValueBalance.objects.update_or_create(account=account, value=row.value, date=row.date, balance=True)
                elif account.acct_type == 'Cash':
                    CashFlow.objects.update_or_create(account=account, investment=account.cash_investment, date=row.date, value=row.value, balance=True,
                                                      note='Imported Balance')
            else:
                print(f'Value, skipping no account information for {row.account__id}')
    print(f'{datetime.now()} - Ending FundValues Import')

    for account in Account.objects.all():
        account.rebuild(positions=True, values=False)


class BaseImporter:
    ImportMap = {}
    XAKeys = {}
    ImportColumns = []

    def __init__(self, input_file, user):
        self.input_file = input_file
        self.user = user
        self.parse_errors = ''
        self.symbol_cache = {}
        self.account_cache = {}
        self.warning = []

    def create_accounts(self, account_keys: List[str]):
        for account in account_keys:
            try:
                self.account_cache[account] = Account.objects.get(account_name=account, user=self.user)
            except Account.DoesNotExist:
                Account(account_name=account, user=self.user, name=account).save()
                logger.info('Created a new Account %s:%s' % (self.user, account))
                self.account_cache[account] = Account.objects.get(user=self.user,  account_name=account)

    def lookup_symbol(self, symbol: str, region:str) -> str:
        """
        Do a lookup and cache the value
        """
        return get_or_add_investment(symbol, region=region).symbol


    def process_group(self, group):
        pass

    def prepare_input_df(self) -> pd.DataFrame:
        """
        Convert the input to a dataframe and do the basic translations required to normalize the fields
        - ImportMap  (localized by subclass)
        - XAMap (localized by subclass)
        """
        df = self.read_csv(self.input_file)
        df = df[self.ImportColumns].reset_index()
        df.rename(columns=self.ImportMap, inplace=True)  # ImportMap to standardize column names
        df.dropna(subset=['Date'], inplace=True)

        df['Date'] = pd.to_datetime(df['Date'])
        df['Symbol'] = df['Symbol'].astype('str')
        missing = df[~df['XAType'].isin(list(self.XAKeys.keys()))]  # Warn admin about any missing rows
        df["XAKey"] = df["XAType"].map(self.XAKeys)
        if len(missing) > 0:
            self.parse_errors += f'Unknown Actions skipped: {missing["XAType"].unique()}'
            logger.error('Imported %s with invalid XA Columns:%s' % (self.input_file, missing['XAType'].unique()))
        df.dropna(subset=['XAKey'], inplace=True)
        df = df.loc[df['XAKey'] != JUNK]  # Clear out junk

        # Precompute rounded absolute values - Setting to int64 to avoid floating point weirdness
        df['Amount'] = pd.to_numeric(df['Amount']).fillna(0).mul(100).round().astype('int64')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0).mul(100).round().astype('int64')

        # Apply sign using masks
        # df.loc[df["XAKey"] == REDEEM, "Amount"] *= -1
        # df.loc[df["XAKey"] == SELL, "Quantity"] *= -1

        # BoolField - used in internal representations negative denote Sell,  or Withdraw
        df["BoolField"] = ~df["XAKey"].isin([REDEEM, SELL])

        # Price
        df["Price"] = df["Price"].abs().fillna(0)

        return df

    def process_transactions_df(self, input_df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract existing Transaction records into a compatible dataframe
        """
        # todo: remove note and perhaps price, there just for debugging
        existing_columns = ['date', 'account__account_name', 'investment', 'quantity', 'price', 'note']
        e_query = Transaction.objects.filter(account__account_name__in=input_df['AccountKey'].unique())
        if e_query.count():
            df = pd.DataFrame(e_query.values(*existing_columns))
            if df.empty:
                df = pd.DataFrame(columns=existing_columns)
        else:
            df = pd.DataFrame(columns=existing_columns)
        df['Date'] = pd.to_datetime(df['date'])
        df.rename(columns={'account__account_name': 'AccountKey', 'investment': 'Symbol', 'quantity': 'Quantity'}, inplace=True)
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0).mul(100).round().astype('int64')
        merged = input_df.loc[input_df['XAKey'].isin([BUY, SELL])].merge(df, on=['Date', 'AccountKey', 'Symbol', 'Quantity'], how='left', indicator=True)

        for _, row in merged.loc[merged['_merge'] == 'left_only'].iterrows():
            investment = get_or_add_investment(row['Symbol'], row['Symbol'])
            quantity = row['Quantity'] / 100
            logger.debug('Transaction:%s:%s %s: %s@%s Note:%s' % (row['Date'], row['AccountKey'], row['Symbol'], quantity, row['Price'], row['Description']))
            if quantity > 0:
                Transaction.buy(this_date=row['Date'], account=self.account_cache[row['AccountKey']], quantity=quantity, price=row['Price'],
                                investment=investment, note=row['Description'], source=DataSource.UPLOAD.value)
            elif quantity < 0:
                Transaction.sell(this_date=row['Date'], account=self.account_cache[row['AccountKey']], quantity=quantity, price=row['Price'],
                                 investment=investment, note=row['Description'], source=DataSource.UPLOAD.value)
            else:
                logger.debug('Transaction:IGNORED 0 quantity %s:%s Note:%s' % (row['Date'], row['AccountKey'], row['Description']))

    def process_funding(self, input_df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract existing Funding records into a compatible dataframe
        """
        # todo: remove note there just for debugging
        existing_columns = ['date', 'account__account_name', 'value']
        e_query = Funding.objects.filter(account__account_name__in=input_df['AccountKey'].unique()).exclude(balance=True)
        if e_query.count():
            df = pd.DataFrame(e_query.values(*existing_columns))
            if df.empty:
                df = pd.DataFrame(columns=existing_columns)
        else:
            df = pd.DataFrame(columns=existing_columns)
        df['Date'] = pd.to_datetime(df['date'])
        df.rename(columns={'account__account_name': 'AccountKey', 'value': 'Amount'}, inplace=True)
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0).mul(100).round().astype('int64')

        merged = input_df.loc[input_df['XAKey'].isin([FUND, REDEEM])].merge(df, on=['Date', 'AccountKey', 'Amount'], how='left', indicator=True)

        for _, row in merged.loc[merged['_merge'] == 'left_only'].iterrows():
            real_value = row['Amount'] / 100
            logger.debug('Funding:%s:%s Value:%s Note:%s' % (row['Date'], row['AccountKey'], real_value, row['Description']))
            if real_value > 0:
                Funding.deposit(this_date=row['Date'], account=self.account_cache[row['AccountKey']], amount=real_value, note=row['Description'],
                                source=DataSource.UPLOAD.value)
            elif real_value < 0:
                Funding.withdraw(this_date=row['Date'], account=self.account_cache[row['AccountKey']], amount=real_value, note=row['Description'],
                                source=DataSource.UPLOAD.value)
            else:
                logger.debug('Funding:IGNORED 0 value %s:%s Note:%s' % (row['Date'], row['AccountKey'], row['Description']))

    def process_cash_df(self, input_df: pd.DataFrame):
        """
        Extract existing Cash records into a compatible dataframe
        """

        # todo: remove note there just for
        input_df = input_df.loc[input_df['XAKey'].isin([CASH])]

        existing_columns = ['date', 'account__account_name', 'value', 'note']
        e_query = CashFlow.objects.filter(account__account_name__in=input_df['AccountKey'].unique()).exclude(balance=True)
        if e_query.count():
            df = pd.DataFrame(e_query.values(*existing_columns))
            if df.empty:
                df = pd.DataFrame(columns=existing_columns)
        else:
            df = pd.DataFrame(columns=existing_columns)
        df['Date'] = pd.to_datetime(df['date'])
        df.rename(columns={'account__account_name': 'AccountKey', 'value': 'Amount'}, inplace=True)
        df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0).mul(100).round().astype('int64')

        merged = input_df.merge(df, on=['Date', 'AccountKey', 'Amount'], how='left', indicator=True)

        for _, row in merged.loc[merged['_merge'] == 'left_only'].iterrows():
            real_value = row['Amount']
            if real_value == 0 and row['Quantity'] != 0 and row['Price'] != 0:
                real_value = row['Quantity'] * row['Price']
            real_value = real_value / 100
            logger.debug('IGNORED CashFlow:%s:%s Value:%s Note:%s' % (row['Date'], row['AccountKey'], real_value, row['Description']))
            continue
            # Value account's do not have cash components
            if self.account_cache[row['AccountKey']].cash_investment:
                logger.debug('CashFlow:%s:%s Value:%s Note:%s' % (row['Date'], row['AccountKey'], real_value, row['Description']))
                CashFlow(date=row['Date'], account=self.account_cache[row['AccountKey']], value=real_value, note=row['Description'], source=DataSource.UPLOAD.value).save(rebuild=False)
            else:
                logger.debug('Value Account - skipping cashflow:%s:%s Value:%s Note:%s' % (row['Date'], row['AccountKey'], real_value, row['Description']))

    def process(self):
        idf: pd.DataFrame = self.prepare_input_df()
        if idf.empty:
            return

        self.create_accounts(list(idf['AccountKey'].unique()))

        self.process_funding(idf)
        self.process_transactions_df(idf)
        self.process_cash_df(idf)
        for account in Account.objects.filter(account_name__in=list(idf['AccountKey'].unique())):
            account.rebuild()
        clear_caches()
    @classmethod
    def matches(cls, headers: set[str]) -> bool:
        """Override in subclasses"""
        raise NotImplementedError

    def read_csv(self, filepath) -> pd.DataFrame:
        raise NotImplementedError

    @classmethod
    def set_importer(cls, file_path, user):
        if isinstance(file_path, InMemoryUploadedFile):
            suffix = Path(file_path.name).suffix
        else:
            suffix = Path(file_path).suffix
        # 👇 Only read headers
        if suffix == '.csv':
            headers = set(pd.read_csv(file_path, nrows=0).columns)
        elif suffix == '.xlsx':
            headers = set(pd.read_excel(file_path, nrows=0).columns)
        else:
            raise ValueError(f"No support processor for extension: {suffix}")

        for subclass in cls.__subclasses__():
            if subclass.matches(headers):
                return subclass(file_path, user)
        raise ValueError(f"Unable to determine the source of this file based on these headings: {headers}")


class NewQuestrade(BaseImporter):

    AllColumns = ['Transaction Date', 'Settlement Date', 'Action', 'Symbol', 'Description', 'Quantity', 'Price', 'Gross Amount', 'Commission', 'Net Amount', 'Currency', 'Account #', 'Activity Type', 'Account Type']
    ImportColumns = ['Date', 'Action', 'Symbol', 'Description', 'Quantity', 'Price', 'Gross Amount', 'Commission', 'Net Amount', 'Currency', 'Account #', 'Activity Type', 'Account Type']
    ImportMap = {
        'Account #': 'AccountKey',
        'Account Type': 'AccountName',
        'Action': 'XAType',
        'Net Amount': 'Amount',
    }

    dot_name_cache = {}

    XAKeys = {'Buy': BUY,
              'DEP': FUND,
              'DIS': BUY,  # This is a stock split BUY
              'DIV': CASH,  # processed to not import if searchable and after first search
              'EFT': REDEEM,  # Electronic Funds Transfer
              'FCH': CASH,  # Fees
              'FED': REDEEM,  # Taxes
              'FXT': CASH,  # Actual a +/- Exchange cost
              'HST': REDEEM,  # More Taxes
              'LFJ': JUNK,  # Securities lending int payment as of March Symbol-EMA 3 cents
              'Sell': SELL,
              'TFO': REDEEM,  # Transfer Out
              'WDR': REDEEM,  # WithDraw
              'skipped DIV': JUNK,
              }

    @staticmethod
    def region_key(key: Union[str, None]) -> str:
        return 'Canada' if key == 'CAD' else None

    @classmethod
    def matches(cls, headers):
        return set(headers) == set(cls.AllColumns)

    def _extract_fees(self, df:pd.DataFrame) -> pd.DataFrame:
        """
        Create Fees (reduce cash) for each commission entry
        """
        new_rows = []
        for idx, row in df.loc[df['Commission'] != 0].iterrows():
            new_row = row.to_dict()
            new_row['Description'] = f'Commission on -> {row["Description"]}'
            new_row['Action'] = 'FCH'
            new_rows.append(new_row)

        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        return df

    def read_csv(self, filepath):
        """
        Make any import file specific changes here
        """
        df = pd.read_excel(filepath)
        df['Date'] = pd.to_datetime(df['Settlement Date'], format='%Y-%m-%d %I:%M:%S %p')  # Perhaps Settlement Date ?
        df['Account #'] = df['Account #'].astype('str')
        df['Account #'] = 'QuestTrade_' + df['Account #']
        df.loc[(df['Activity Type'] == 'Dividends') & (pd.isna(df['Action'])), 'Action'] = 'DIV'  # Fix missing DIV Actions

        df = self._validate_symbols(df)  # The rest depends on Symbol being corrected/validated
        df = self._validate_dividends(df)  # Requires _validate_symbols(df)
        df = self._extract_fees(df)
        return df



    def _scan_lookup(self, sdf: pd.DataFrame, symbol: str, description: str) -> str:
        """
        scan the DataFrame trying to match description,  if found,  lookup that value
        return the validated (and cached) symbol or ''
        """

        if symbol in investments:
            return symbol

        if symbol in self.dot_name_cache:
            return self.dot_name_cache[symbol]

        desc = result = ''
        if 'CASH DIV ON' in description:
            desc = description.split('CASH DIV ON')[0].rstrip()
        elif 'WE ACTED AS AGENT' in description:
            desc = description.split('WE ACTED AS AGENT')[0].rstrip()
        elif 'DIST ON' in description:
            desc = description.split('DIST ON')[0].rstrip()
        if desc:  # DIV would be thyself,  and DIS has another value
            symbol_df = sdf.loc[(sdf['Description'].str.contains(desc, na=False)) & (sdf['Action'] != 'DIV') & (sdf['Action'] != 'DIS') ].reset_index()
            if len(list(symbol_df['Symbol'].unique())) == 1:
                region = 'Canada' if symbol_df.iloc[0]['Currency'] == 'CDN' else None
                result = get_investment(symbol_df.iloc[0]['Symbol'], region)
                if result:
                    self.dot_name_cache[symbol] = result
        return result

    def _validate_dividends(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Force Junk record for dividend we record via API
        todo: Add a start date to the inventory item so we can leave dates prior to the first search
        """
        for idx, row in df.loc[df['Action'] == 'DIV'].iterrows():
            # We have a case where quantity is less than 0 it is a sell (makes no sense buy I see it in the exports (buy/sell) combo
            investment = get_or_add_investment(row['Symbol'], region=self.region_key(row['Currency']))
            if investment.searchable:
                df.loc[idx, 'Transaction Type'] = 'skipped DIV'
        return df

    def _validate_symbols(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        .symbol sometimes do not match there symbol at all!
        This could be better done with a translation
        """
        for idx, row in df.loc[~pd.isna(df['Symbol'])].iterrows():
            symbol = row['Symbol']
            if symbol not in self.dot_name_cache:
                symbol_str = get_investment(symbol, self.region_key(row['Currency']))
                if not symbol_str:
                    symbol_str = self._scan_lookup(df, symbol, row['Description'])
                    if not symbol_str:
                        if symbol.startswith('.') and symbol != '.':
                            symbol = symbol[1:]
                        symbol_str = get_investment(symbol_str, self.region_key(row['Currency']), set_default=True)
            else:
                symbol_str = self.dot_name_cache[symbol]
            if symbol != symbol_str:
                df.loc[idx, 'Symbol'] = symbol_str
        return df


class NewManLife(BaseImporter):

    AllColumns = ['Date', 'Account Number', 'Transaction Type', 'Description', 'Quantity',
       'Price (Trade Currency)', 'Total Value (Account Currency)',
       'Account Type', 'Account Name', 'Process Date', 'Settlement Date',
       'Trade Currency', 'Account Currency', 'Market', 'CUSIP', 'Symbol',
       'SEC Fee', 'Commission', 'FX Rate']

    ImportColumns = ['Date', 'Account Number', 'Transaction Type', 'Description', 'Quantity',
       'Price (Trade Currency)', 'Total Value (Account Currency)',
        'Account Name', 'Symbol',
                     ]

    ImportMap = {
        'Account Number': 'AccountKey',
        'Account Type': 'AccountName',
        'Transaction Type': 'XAType',
        'Account Currency': 'Currency',
        'Price (Trade Currency)': 'Price',
        'Total Value (Account Currency)': 'Amount',
    }

    XAKeys = {'Buy': BUY,
              'Sell': SELL,
             'Div Re-inv': BUY,
             'Mut Fd Reinv Mgmt Fee Reb': BUY,
             'Reinv Div': BUY,
             'Trust Inc & Prtnr DRIP': BUY,
             'Dividend': CASH,  # Dividend records are used for equities, we are already getting dividend values from yfinance
             'Conversion Buy': BUY,  # This is a reinvested Div from earlier account that was not yet accounted for
             'Conversion Entry': JUNK,  # Does not seem to have any cost associated
             'Conversion': BUY,  # These were shares transfered in
             'Tfsa Contribution': FUND,
             'Transfer Out - External': REDEEM,
             'Transfer In - Internal': FUND,
              'Reinv Funding': FUND,
             'Transfer Out - Internal': REDEEM,
              'Interest In Kind': CASH,
             'Conversion Roc': JUNK,  # Does not seem to have any cost associated
             'Adjust Cost': JUNK,  # Does not seem to have any cost associated
             'Fee For Service': CASH,  # Value in 'Total Value (Account Currency)' is what we were charged
             'Cash Deposit': CASH,  # This is made up, for the purpose of Conversion records with only money to indicate a cash
             'Make Junk': JUNK,  # This I process as part of read_csv that I want to ignore
              'skipped DIV': JUNK,
              }

    @staticmethod
    def region_key(key: Union[str, None]) -> str:
        return 'Canada' if key == 'T' else None

    @classmethod
    def matches(cls, headers):
        return set(headers) == set(cls.AllColumns)

    def _process_conversions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Conversion are unique to the new manulife format and resulted from the initial imports aka, transfer in
        """

        df = df[~((df['Transaction Type'] == 'Conversion Roc') & (df['Quantity'] == 0))]  # Delete some empty Roles
        df = df[~((df['Transaction Type'] == 'Conversion Buy') & (df['Quantity'] == 0))]
        df = df[~((df['Transaction Type'] == 'Conversion Entry') & (df['Quantity'] == 0))]
        mask = (df['Transaction Type'] == 'Conversion')
        for idx, row in df.loc[mask].iterrows():
            if row['Quantity'] == 0:
                df.loc[idx, 'Transaction Type'] = 'Cash Deposit'
            else:
                # Update the record to a Buy for  shares that were transferred in
                df.loc[idx, 'Transaction Type'] = 'Buy'
                if row['Price (Trade Currency)'] == 0:
                    price = Value.lookup(row['Date'], row['Symbol'])
                    df.loc[idx, 'Price (Trade Currency)'] = float(price)
        return df

    def _process_tfsa_contributions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Some weirdness with TFSA processing,  these TFSA contributions were not cash but share transfers
        """
        new_rows = []

        mask = ((df['Transaction Type'] == 'Tfsa Contribution') & (df['Total Value (Account Currency)'] == 0) & (df['Quantity'] != 0))
        for idx, row in df.loc[mask].iterrows():
            price = Value.lookup(row['Date'], row['Symbol'])
            df.loc[idx, 'Total Value (Account Currency)'] = float(price) * float(row['Quantity'])
            if float(row['Quantity']) < 0:  # This happens when we transfer out of our CASH account into our TFSA
                df.loc[idx, 'Transaction Type'] = 'Transfer Out - External'
            df.loc[idx, 'Description'] = 'TFSA Contribution -> ' + row['Description']
            # Create the BUY/SELL records
            new_row = row.to_dict()
            new_row['Price (Trade Currency)'] = price
            new_row['Description'] = 'TFSA Contribution -> ' + row['Description']
            new_row['Transaction Type'] = 'Buy' if float(row['Quantity']) > 1 else 'Sell'
            new_rows.append(new_row)

        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        return df

    def _process_dividends(self, df:pd.DataFrame) -> pd.DataFrame:
        """
        If a dividend has been re-invested that we should also create a funding record since we are putting more money into stock purchases,
        also we need to make sure we have a price, so we can calculate the actual cost per share
        """
        dividend_types = ['Div Re-inv', 'Mut Fd Reinv Mgmt Fee Reb', 'Reinv Div', 'Trust Inc & Prtnr DRIP', 'Conversion']
        new_rows = []
        for idx, row in df.loc[df['Transaction Type'].isin(dividend_types)].iterrows():
            # We have a case where quantity is less than 0 it is a sell (makes no sense buy I see it in the exports (buy/sell) combo
            price = row['Price (Trade Currency)']
            if row['Price (Trade Currency)'] == 0:
                price = float(Value.lookup(row['Date'], row['Symbol']))
                df.loc[idx, 'Price (Trade Currency)'] = float(price)
            description = f'({row["Transaction Type"]}) : ReInvested Dividends: {row["Quantity"]} units @ ${price}'
            df.loc[idx, 'Description'] = description
            if float(row['Quantity']) < 0:
                df.loc[idx, 'Transaction Type'] = 'Sell'

            new_row = row.to_dict()
            new_row['Description'] = f'ReInvested Dividends {row["Symbol"]}: {row["Quantity"]} units @ ${price}'
            new_row['Transaction Type'] = 'Reinv Funding' if float(row['Quantity']) > 0 else 'Transfer Out - Internal'
            if row['Total Value (Account Currency)'] == 0:
                new_row['Total Value (Account Currency)'] = float(row['Quantity']) * price
            new_rows.append(new_row)

        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        return df

    def read_csv(self, filepath):
        """
        Make any import file specific changes here
        """
        if isinstance(filepath, InMemoryUploadedFile):
            # filepath = StringIO(filepath.read().decode('utf-8'))
            filepath.seek(0)

        df = pd.read_csv(filepath,
                         converters={
                             "Price (Trade Currency)": lambda x: float(x.replace("$", "").replace(",", "")),
                             "Total Value (Account Currency)": lambda x: float(x.replace("$", "").replace(",", "")),
                             "Commission": lambda x: float(x.replace("$", "").replace(",", "")),
                         }
                         )
        df['Account Number'] = 'ManulifeWealth_' + df['Account Number']
        df['Date'] = pd.to_datetime(df['Date'])  # todo:  Perhaps this is where I set Process Date ?

        df = self._validate_symbols(df)  # The rest depends on Symbol being corrected/validated
        df = self._process_conversions(df)
        df = self._process_tfsa_contributions(df)
        df = self._process_dividends(df)
        df = self._validate_dividends(df)
        df.loc[(df['Transaction Type'] == 'Interest In Kind'), 'Total Value (Account Currency)'] = df['Quantity']  # Quirk of NewML
        return df

    def _validate_dividends(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Force Junk record for dividend we record via API
        todo: Add a start date to the inventory item so we can leave dates prior to the first search
        """
        for idx, row in df.loc[df['Transaction Type'] == 'Dividend'].iterrows():
            # We have a case where quantity is less than 0 it is a sell (makes no sense buy I see it in the exports (buy/sell) combo
            investment = get_or_add_investment(row['Symbol'], region=self.region_key(row['Market']))
            if investment.searchable:
                df.loc[idx, 'Transaction Type'] = 'skipped DIV'
        return df

    def _validate_symbols(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        This is going to be slow.
        """
        for idx, row in df.loc[~pd.isna(df['Symbol'])].iterrows():
            region = 'Canada' if row['Market'] == 'T' else None  # This is primitive, but it is all the data I have
            symbol = self.lookup_symbol(row['Symbol'], region=region)
            df.loc[idx, 'Symbol'] = symbol
        return df
