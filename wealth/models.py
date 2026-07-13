import logging

import math
import numpy as np
import pandas as pd
import time
import yfinance as yf

from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models, IntegrityError
from django.db.models import Value as DJValue, QuerySet, BooleanField, IntegerField, Q, F, Sum, Subquery, OuterRef, Max
from django.db.models.functions import Trunc, TruncDay, TruncMonth
from django.urls import reverse
from django.utils import timezone

from functools import cached_property
from itertools import groupby
from operator import itemgetter
from yfinance.exceptions import YFRateLimitError

from typing import List, Union

from base.ioom_dates import IOOMDates
from base.models import API, DataSource, NormalizedDataModel, CURRENCIES
from base.utils import df_start, dates_dataframe, force_decimal, adjust_date, to_utc_midnight, to_utc_datetime

logger = logging.getLogger(__name__)
logging.getLogger('yfinance').setLevel(logging.CRITICAL)  # Quiet damn you.
logging.getLogger('peewee').setLevel(logging.ERROR)

# Investment class is used for both Investment objects and account objects.
INVESTMENT_CLASS = (('Trading', 'Equity/ETF/Mutual Fund'),    # Transactions -> Values: Multiple units,  multiple prices - Accounts have Funding and Cash Investments
                    ('Cash', 'Bank Accounts'),                # CashFlow -> Values: Multiple units,  prices is always 1 - Accounts only have 1 Cash Investment
                    ('Value', 'Value Account'),               # direct to -> Values: 1 share, multiple prices - Accounts have Funding but no Cash Investment
                    ('Funding', "Account's actual funding"),  # Funding -> Values: Multiple shares,  prices is always 1 - Accounts only have 1 Cash Investment
                    )  # Accounts, slices this constant - be careful

FUND = 1  # Actual Contributions
BUY = 2
REDIV = 3
SELL = 4
REDEEM = 5  # Money removed from Funding
INTEREST = 6  # Used for anything that alters cash balance but is not tied an equity
FEES = 7
TRANS_IN = 8  # Money moved in but not a contribution
TRANS_OUT = 9  # Money moved out but not from contributions
VALUE = 10
BALANCE = 11

TRANSACTION_TYPE = ((FUND, 'Deposit'),  # Value only and always positive
                    (BUY, 'Buy'),  # Price and Quantity
                    (REDIV, 'Reinvested Dividend'),  # Price and Quantity but Price is set to 0
                    (SELL, 'Sell'),
                    (INTEREST, 'Dividends/Interest'),
                    (REDEEM, 'Withdraw'),
                    (FEES, 'Fees Paid'),
                    (TRANS_IN, 'Transfer In'),
                    (TRANS_OUT, 'Transfer Out'),
                    (VALUE, 'Value'),
                    (BALANCE, 'Balance')
                    )

TRANSACTION_MAP = dict(TRANSACTION_TYPE)

SCOPES = ['day', 'month']
'''
This is the foundation

DataFrame are build from Positions + Values, where Positions hold the number of units per month or day, Values contains the price on that month or day or in-day
    - it must be 500 ms, to load all accounts all investments - 40 accounts, 100 investments
    
Positions are build from:
    Transactions for Trading Investments,
    CashFlow for Cash Investments,
    Funding for Funding Investments 
    ValueBalance for Value Investments
    - Positions are rebuild and changes to Investments for Accounts.   They should change infrequently (once per month, assuming reinvested dividends)    

Values are build from:
    YFinance for searchable Trading Investments
    User input (and/or linear calculations) for all else
    
Transaction, Funding, CashFlow and ValueAcct objects are used to build Position objects.  Position objects are cumulative in so much as they hold the 
current value as of the date.    

Position + Value + Dividend Dataframes are combined to build the result dataframe that is used as the basis for all data.
┌─────────────┐                                         
│ Transaction ├──────┐   ┌─────────┐                    
└─────────────┘      │   │Value    ├──────┐             
┌─────────────┐      │   └─────────┘      │             
│ Funding     ├──────┤                    │             
└─────────────┘      │  ┌─────────┐       │  ┌───────────┐
┌─────────────┐      │─►│Position ├───────│─►│ dataFrame │
│ CashFlow    ├──────┤  └─────────┘       │  └───────────┘
└─────────────┘      │                    │             
┌─────────────┐      │   ┌─────────┐      │             
│ValueBalance ├──────┘   │Dividend ├──────┘             
└─────────────┘          └─────────┘                    
                                                        
                                                                  
update month values once a week
update day values at market close + 20 minutes
update minute every 15 minutes
'''





'''
def rebuild_amount_links(scope: str, df: pd.DataFrame, query: QuerySet):
    """
    scope: is either day or month
    query: is the QuerySet of Dividend records (it may have be filtered by account(s), investments(s))

    Update the M2M relationships,  This needs to be done prior to calculating amounts
    """

    div_df = Dividend.as_dataframe(scope=scope, investment=None)
    if div_df.empty:
        logger.error('Empty DataFrame - Impossible')
        return

    div_df = div_df.rename(columns={"investment": "Symbol", "date_value": "Date", "id": "DividendID", "amount": "AmountID", "amount__dividend": "AmountDivID"}).astype({'Symbol': 'str', 'DividendID': 'Int64'})

    df = df.merge(div_df, on=['Date', 'Symbol'])  # Note not using how='left' truncates out the rows without dividends

    acct_dict = {account.id: account for account in Account.objects.all()}                 # Cheap lookup table
    inv_dict = {investment.symbol: investment for investment in Investment.objects.all()}  # Cheap lookup table

    if not df.empty:
        for index, row in df.iterrows():
            try:
                amount = Amount(date=row.Date, account=acct_dict[row.AccountID], investment=inv_dict[row.Symbol], scope=scope)
                amount.save()
                amount.dividend.add(row.id)  # Add the many-to-many relationship
                continue  # on to the next to_process entry
            except IntegrityError:  # This already exists,  this is the rare case(s) as documented above
                try:
                    amount = Amount.objects.get(date=row.Date, account=acct_dict[row.AccountID], investment=inv_dict[row.Symbol], scope=scope)
                except Amount.DoesNotExist:
                        logger.error('Fatal Can not lookup existing Amount based on %s %s %s %s' % (row.Date, row.AccountID, row.Symbol, scope))
                        continue  # on to the next to_process entry
            if row.id not in amount.dividend.all().values_list('id', flat=True):
                amount.dividend.add(row.id)  # A second dividend payout has been detected


def rebuild_amount_amounts(scope: str, df: pd.DataFrame, query: QuerySet):
    """
    scope: is either day or month
    query: is the QuerySet of Dividend records (it may have be filtered by account(s), investments(s))

    Note:  Most of the complexity here is because in rare cases an investment will pay out twice in a time period.   As an example VDY.TO in Dec 2025.
    this caused the model to be a many to many between a dividend and an amount.   Any dividend payout can be applied to many accounts,  and because of the
    rare case above,  an amount may actually be linked to multiple divided payouts.
    """

    div_df = pd.DataFrame(query.filter(amount__account__isnull=False).values('id', 'date_value', 'investment', 'value', 'amount__account', 'amount__amount'))
    div_df.rename(columns={"investment": "Symbol", "date_value": "Date", "amount__amount": "amount"}, inplace=True)

    div_df['amount__account'] = div_df['amount__account'].astype('int64')  # The account (if any) that this amount was linked to
    div_df['amount'] = div_df['amount'].fillna(0).astype('float64')                  # The recorded value of this dividend (if different it will be changed)
    div_df['value'] = div_df['value'].astype('float64')                              # The actual value of the dividend value (via API)
    div_df['Symbol'] = div_df['Symbol'].astype('string')                             # The investment that paid he dividend value

    df = df.merge(div_df, on=['Date', 'Symbol'])  # Note not using how='left' truncates out the rows without dividends

    df = df.loc[(df['amount__account'] == 0) | (df['amount__account'] == df['AccountID'])]  # Remove duplicate caused by AccountID == 0
    df['new_amount'] = df['Quantity'] * df['value']  # Calculate what the amount should be,  this will detect a change in dividend value or Quantity of shares
    df.drop(df[df['new_amount'] == 0].index, inplace=True)  # This will happen if Quantity is change to 0 or the original dividend value was erroneous

    to_process = df.loc[~np.isclose(df['amount'], df['new_amount'])]  # We only need to process changes

    acct_dict = {account.id: account for account in Account.objects.all()}                 # Cheap lookup table
    inv_dict = {investment.symbol: investment for investment in Investment.objects.all()}  # Cheap lookup table

    if not to_process.empty:
        for index, row in to_process.iterrows():
            try:
                amount = Amount.objects.get(id=row.amount__id)
            except Amount.DoesNotExist:
                logger.error('Fatal Can not lookup existing Amount based on id %s - %s %s %s %s' % (row.amount_id, row.Date, row.AccountID, row.Symbol, scope))
                continue
            amount.amount = amount.dividend.aggregate(sum_amount=Sum('value')) ['sum_amount'] * Decimal(row.Quantity)
            amount.save()


def rebuild_amount_total(query: QuerySet):
    """
    query: is the QuerySet of Amount records - prefiltered by scope,  account(s), investment(s)

    Ensure the cumulative values of total is correct for all amount records.
    """
    df = pd.DataFrame(query.values('id', 'date', 'investment', 'account', 'value', 'amount', 'total'))
    df = df.sort_values(["account", "investment", "date"])
    df["new_total"] = df.groupby(["AccountID", "Symbol"])["amount"].cumsum()

    to_process = df.loc[~np.isclose(df['total'], df['new_total'])]  # We only need to process changes

    acct_dict = {account.id: account for account in Account.objects.all()}  # Cheap lookup table
    inv_dict = {investment.symbol: investment for investment in Investment.objects.all()}  # Cheap lookup table

    if not to_process.empty:
        for index, row in to_process.iterrows():
            amount = Amount.objects.get(id=row.id)
            amount.total = row.new_total
            amount.save()


def rebuild_amounts(scope: str = 'month',
                    accounts: Union['Account', QuerySet, None] = None,
                    investments: Union['Investment', QuerySet, None] = None):
    """
    Build/Update Amount records.
    Dividend(s) -> Amount -> CashFlow
    """

    trunc = {  # Pattern thanks to AI
        "day": TruncDay("date"),
        "month": TruncMonth("date"),
    }[scope]

    # todo:  1) Filter out things that are not searchable, 2) Do we need to chunk this up ?  I know it only runs once a day but could it eat all my memory
    df = Position.as_dataframe(scope=scope, account=accounts, investment=investments, force_start=True)
    if df.empty:
        logger.debug('No Position records found for Account:%s Investment:%s Scope:%s' % (accounts, investments, scope))
        return
    div_base_query = filter_by_account_and_investment(Dividend.objects.all(), account=None, investment=investments).annotate(date_value=trunc)
    if div_base_query.count() == 0:
        logger.debug('No Dividend records found for Account:%s Investment:%s' % (accounts, investments))
        return

    rebuild_amount_links(scope, df, div_base_query)  # Ensures amount values are correct and all dividends are linked to amount records
    rebuild_amount_amounts(scope, df, div_base_query)
    rebuild_amount_total(filter_by_account_and_investment(Account.objects.filter(scope=scope), account=None, investment=investments))


def rebuild_amounts_orig(scope: str = 'month',
                    accounts: Union['Account', QuerySet, None] = None,
                    investments: Union['Investment', QuerySet, None] = None):
    """
    Build/Update Amount records.
    Dividend(s) -> Amount -> CashFlow
    """

    trunc = {  # Pattern thanks to AI
        "day": TruncDay("date"),
        "month": TruncMonth("date"),
    }[scope]

    # todo:  1) Filter out things that are not searchable, 2) Do we need to chunk this up ?  I know it only runs once a day but could it eat all my memory
    df = Position.as_dataframe(scope=scope, account=accounts, investment=investments, force_start=True)
    if df.empty:
        logger.debug('No Position records found for Account:%s Investment:%s Scope:%s' % (accounts, investments, scope))
        return
    div_base_query = filter_by_account_and_investment(Dividend.objects.all(), account=None, investment=investments).annotate(date_value=trunc)
    if div_base_query.count() == 0:
        logger.debug('No Dividend records found for Account:%s Investment:%s' % (accounts, investments))
        return


    div_df = pd.DataFrame(div_base_query.values('id', 'date_value', 'investment', 'value', 'amount__id', 'amount__account', 'amount__amount', 'amount__total'))
    if div_df.empty:
        logger.debug('No Dividend records found for Account:%s Investment:%s' % (accounts, investments))
        return
    else:
        div_df.rename(columns={"investment": "Symbol", "date_value": "Date", "amount__amount": "amount", "amount__total": "total"}, inplace=True)

        div_df['amount__id'] = div_df['amount__id'].fillna(0).astype('int64')
        div_df['amount__account'] = div_df['amount__account'].fillna(0).astype('int64')
        div_df['amount'] = div_df['amount'].fillna(0).astype('float64')
        div_df['total'] = div_df['total'].fillna(0).astype('float64')
        div_df['value'] = div_df['value'].astype('float64')
        div_df['Symbol'] = div_df['Symbol'].astype('string')

        df = df.merge(div_df, on=['Date', 'Symbol'])  # Note not using how='left' truncates out the rows without dividends

    df = df.loc[(df['amount__account'] == 0) | (df['amount__account'] == df['AccountID'])]  # Remove duplicate caused by AccountID == 0
    df['new_amount'] = df['Quantity'] * df['value']
    df.drop(df[df['new_amount'] == 0].index, inplace=True)

    df = df.sort_values(["AccountID", "Symbol", "Date"])
    df["new_total"] = df.groupby(["AccountID", "Symbol"])["new_amount"].cumsum()

    to_process = df.loc[(~np.isclose(df['amount'], df['new_amount'])) | (~np.isclose(df['total'], df['new_total']))]

    acct_dict = {account.id: account for account in Account.objects.all()}                 # Cheap lookup table
    inv_dict = {investment.symbol: investment for investment in Investment.objects.all()}  # Cheap lookup table

    if not to_process.empty:
        for index, row in to_process.iterrows():
            if row.amount__id == 0:
                try:
                    amount = Amount(date=row.Date, account=acct_dict[row.AccountID], investment=inv_dict[row.Symbol], scope=scope, amount=row.new_amount, total=row.new_total)
                    amount.save()
                    amount.dividend.add(row.id)
                    continue
                except IntegrityError:
                    pass  # This already existing, use case - I am adding two new records with the same date - rare buy possible VDY.TO Dec 2025
                    try:
                        amount = Amount.objects.get(date=row.Date, account=acct_dict[row.AccountID], investment=inv_dict[row.Symbol], scope=scope)
                    except Amount.DoesNotExist:
                        logger.error('Fatal Can not lookup existing Amount based on %s %s %s %s' % (row.Date, row.AccountID, row.Symbol, scope))
                        continue
            else:
                try:
                    amount = Amount.objects.get(id=row.amount__id)
                except Amount.DoesNotExist:
                    logger.error('Fatal Can not lookup existing Amount based on id %s - %s %s %s %s' % (row.amount_id, row.Date, row.AccountID, row.Symbol, scope))
                    continue

            if row.id not in amount.dividend.all().values_list('id', flat=True):
                amount.dividend.add(row.id)
            amount.amount = amount.dividend.aggregate(sum_amount=Sum('value')) ['sum_amount']
            amount.total = row.Quantity
            amount.save()

'''


def clear_caches(user=None):
    """
    wealth.dataframes caches values,  to avoid a circular loop I need to move the clear caches to here
    """
    from collections import OrderedDict
    to_delete = []

    if isinstance(cache._cache, OrderedDict):  # simple cache
        for item in cache._cache.keys():
            if user:
                if item.startswith('IOOM:1:user_dataframe:{user}'):
                    to_delete.append(item[7:])
            elif item.startswith(f'IOOM:1:user_dataframe:'):
                to_delete.append(item[7:])

    else:  # Assume this is Redis backend
        client = cache._cache.get_client(write=True)
        for key in client.scan_iter(match="*user_dataframe*"):
            to_delete.append(key)

    cache.delete_many(to_delete)



def build_running_totals(query: QuerySet, value_key: str = 'value', static_quantity: bool = False) -> []:
    """
    Provided a queryset that will return a list of dictionaries with each dictionary having the following values:

        this_day is the date or month used - typically an annotation with TruncMonth or TruncDay
        value is the signed value to generate either increase or decrease
        price is the cost of that value
        balance for resetting the running total,  used to correct data.

    return is a list of lists of [date, running_value, average_price]
    """
    data = {
        this_day: list(rows)
        for this_day, rows in groupby(query, key=itemgetter("this_day"))
    }

    running_total = 0
    running_spend = 0
    result = []
    for key in data.keys():
        for record in data[key]:
            if 'balance' in record and record['balance'] or static_quantity:
                running_total = record[value_key]
                if record['price'] == 1:
                    running_spend = running_total
            else:
                running_spend += record[value_key] * record['price']
                running_total += record[value_key]
        running_price = running_spend / running_total if running_total != 0 else 0
        result.append([key, running_total, running_price])
    return result


def filter_by_account_and_investment(query: QuerySet, account: Union[QuerySet, 'Account', str, None], investment: Union[QuerySet, 'Investment', str, None]) -> QuerySet:
    if investment and query.model != 'Investment' and hasattr(query.model, 'investment'):
        try:
            if isinstance(investment, Investment):
                query = query.filter(investment=investment)
            elif isinstance(investment, QuerySet):
                query = query.filter(investment__in=investment)
            elif isinstance(investment, str) :
                query = query.filter(investment__symbol=investment)
        except ValueError:
            logger.error('Unexpected "Investment": %s' % investment)  # Result will be all values

    if account and query.model != 'Account' and hasattr(query.model, 'account'):
        try:
            if isinstance(account, Account):
                query = query.filter(account=account)
            elif isinstance(account, QuerySet):
                query = query.filter(account__in=account)
            elif isinstance(account, str):
                query = query.filter(account__name=account)
            elif isinstance(account, int):
                query = query.filter(account__id=account)

        except ValueError:
            logger.error('Unexpected "Account": %s', account)
    return query


class Investment(models.Model):
    """
    Class to hold information regarding an investment vehicle
    """

    symbol: str = models.CharField(max_length=64, blank=False, null=False, primary_key=True, verbose_name='Trading symbol')  # Symbol
    country: str = models.CharField(max_length=2, blank=False, null=False, default='CA', verbose_name='Country hosting the investment')
    user: User = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)  # Set on non-equity accounts
    name: str = models.CharField(max_length=128, blank=True, null=True, verbose_name='Investments Full Name')
    inv_type: str = models.CharField(max_length=10, blank=True, null=True, choices=INVESTMENT_CLASS, default='Trading')
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='CAD')
    last_updated: date = models.DateTimeField(blank=True, null=True)
    deactivated_date: date = models.DateField(blank=True, null=True, verbose_name='Date this investment was de-listed or deactivated')
    searchable: bool = models.BooleanField(default=False)  # Set to True if validation found an API that could be used to search this data
    validated: bool = models.BooleanField(default=False)   # Set to True was validation is done
    closed: date = models.DateField(null=True, blank=True, help_text='The date an investment is de-listed')

    static_values = ['Cash', 'Funding', 'Values']  # Investment types that have a Value of 1,  where the quantity alone dictates the Investment Value

    def __str__(self):
        return self.symbol

    @property
    def alias(self):
        proper = self.symbol.split('~')
        return proper[0] if len(proper) == 2 else proper[1]

    @staticmethod
    def _process_value_diff(scope:bool, diff_df, last_update=None):
        if diff_df.empty:
            return

        required_columns = {'id', 'Date', 'investment', 'Close', 'Open', 'source'}
        result = required_columns - (required_columns & set(diff_df.columns))
        if result:
            logger.error('Missing Columns: %s' % result)
            return

        diff_df = diff_df.loc[(diff_df['source'].isna()) | (diff_df['source'] >= DataSource.API.value)]  # Remove better source

        investments = {investment.symbol: investment for investment in Investment.objects.filter(searchable=True)}
        updated = []
        items = []
        run_date = orig_date = last_update

        diff_df.sort_values(['investment', 'Date'], inplace=True)
        for index, row in diff_df.iterrows():
            this_id = row.id if not math.isnan(row.id) else None
            open_value = row.Open
            close_value = row.Close
            this_date = IOOMDates.ioom_ts(row.Date)
            logger.debug('Updating %s for %s = old:(%s,%s) new:(%s,%s)' % (row.investment, row.Date, row.open_value, row.close_value, open_value, close_value))

            items.append(Value(id=this_id, date=this_date, day_scope=scope, investment=investments[row.investment],
                               source=DataSource.API.value, open_value=force_decimal(open_value), close_value=force_decimal(close_value)))
            run_date = this_date if not run_date or this_date > run_date else run_date
            if row.investment not in updated:
                updated.append(row.investment)

        cleaned = []
        symbol = this_time = None
        for item in reversed(items):
            if item.investment != symbol or (item.investment == symbol and item.date != this_date):
                cleaned.append(item)
                symbol = item.investment
                this_date = item.date

        if len(cleaned):
            Value.objects.bulk_create(cleaned, batch_size=500, update_conflicts=True, update_fields=['open_value', 'close_value', 'source'], unique_fields=['id'])
        else:
            return

        if len(updated) and (not orig_date and run_date) or run_date != orig_date:
            Investment.objects.filter(symbol__in=updated).update(last_updated=run_date)

    @staticmethod
    def _process_dividend_diff(scope: bool, diff_df):
        if diff_df.empty:
            return

        investments = {investment.symbol: investment for investment in Investment.objects.filter(searchable=True)}
        for index, row in diff_df.iterrows():
            update_value = row.Dividends
            if not math.isnan(update_value) and update_value != 0:
                this_date = row.Date
                logger.debug('Updating Dividend for %s@%s old:%s new:%s' % (row.investment, row.Date, row.value, update_value))
                Dividend.objects.update_or_create(date=this_date, investment=investments[row.investment], day_scope=scope,
                                                  defaults={'source': DataSource.API.value, 'value': force_decimal(update_value)})

    @classmethod
    def daily_update(cls):
        """
        Run daily, to update and cleanup - It will take a good chunk of time (15 minutes ish)
        """
        for investment in Investment.objects.filter(searchable=True):
            investment.limited_update()

        clear_caches()

    @classmethod
    def day_range(cls) -> pd.DataFrame:
        when = datetime.today().date()
        searchable = list(Investment.objects.filter(searchable=True).values_list('symbol', flat=True))

        pd.options.mode.chained_assignment = None  # The warning is caused by dividends in this period but not provided with minute interval
        api_df = yf.Tickers(searchable).history(interval='15m', period='1d', start=when, auto_adjust=False, progress=False)[['Open', 'Close']]
        pd.options.mode.chained_assignment = "warn"
        if api_df.empty:
            logger.warning('Failed to pull the in-day results')
            return api_df

        api_df = api_df.stack(future_stack=True).reset_index().rename(columns={"Ticker": "investment", "level_0": 'Datetime'})
        api_df['Open'] = api_df.groupby('investment')['Open'].transform(lambda x: x.ffill().bfill())
        api_df['Close'] = api_df.groupby('investment')['Close'].transform(lambda x: x.ffill().bfill())
        current_time = api_df['Datetime'].max()  # It will get wiped out below
        if not current_time.date() == when:
            logger.info('Run attempted pre-market open')
            return pd.DataFrame()  # Right day but still to early

        # From chatgpt
        api_df = api_df.groupby('investment').apply(
            lambda group: pd.Series({
                'api_open': group.loc[group['Datetime'].idxmin(), 'Open'],
                'api_close': group.loc[group['Datetime'].idxmax(), 'Close']
            }), include_groups=False)

        api_df.dropna(inplace=True)
        api_df['Datetime'] = current_time
        api_df = api_df.reset_index()
        api_df.columns = ['investment', 'Open', 'Close', 'Datetime']
        return api_df

    @classmethod
    def in_day_update(cls):
        """
        Updating the CLOSE (and OPEN) values for the value records
        We are doing this every 15 minutes so lets be quick
        - Tricky,  sometimes we do not get a close,
        - We don't want to update open on a month record (using daily data)
        """
        current_date = IOOMDates(build=False).day_end
        if not current_date == datetime.now().date():
            logger.info('Run attempted on NON Market Day')
            return  # Not a 'market' day, no point in trying

        api_df = cls.day_range() # DataFrame which is coerced to be first open value and last closed value on this date
        if not api_df.empty:
            current_time = api_df['Datetime'].max()

            for day_scope in [True, False]:
                value_day = current_date if day_scope else current_date.replace(day=1)
                api_df['Date'] = value_day
                values_df = pd.DataFrame(Value.objects.filter(investment__in=Investment.objects.filter(searchable=True),
                                                              day_scope=day_scope, date=value_day).values(
                    'id', 'investment', 'date', 'open_value', 'close_value', 'source'))

                if not values_df.empty:
                    values_df.rename(columns={"date": "Date"}, inplace=True)
                else:
                    values_df = pd.DataFrame(columns=['id', 'Date', 'investment', 'open_value', 'close_value', 'source'])

                values_df['open_value'] = values_df['open_value'].astype("float64")
                values_df['close_value'] = values_df['close_value'].astype("float64")

                values_df = api_df.merge(values_df, on=['Date', 'investment'], how='left')
                if not day_scope:  # Don't take the daily open value
                    values_df['Open'] = values_df["open_value"]

                values_df = values_df[(~np.isclose(values_df["Close"], values_df["close_value"], atol=1e-3, rtol=1e-3)) |
                                      (~np.isclose(values_df["Open"], values_df["open_value"], atol=1e-3, rtol=1e-3))]

                cls._process_value_diff(day_scope, values_df)
                Investment.objects.filter(symbol__in=api_df['investment'].tolist()).update(last_updated=current_time)
                clear_caches()
            # update existing cached dataframes
        clear_caches()

    def limited_update(self):
        if not self.searchable:
            return

        yf_df = yf.Ticker(self.symbol).history(auto_adjust=False,  interval='1d', period='20y').reset_index()
        if yf_df.empty:
            return

        yf_df['Date'] = yf_df['Date'].dt.tz_localize(None)

        ioom_dates = IOOMDates(build=False)
        for day_scope in [True, False]:
            if day_scope:
                df = yf_df.loc[(yf_df['Date'] >= pd.Timestamp(ioom_dates.day_start))].reset_index()
            else:
                df = yf_df.groupby(pd.Grouper(key='Date', freq='MS')).agg({'Open': 'first', 'Close': 'last', 'Dividends': 'sum'}).reset_index()
            df['investment'] = self.symbol  # Restore this value

            update_start = df['Date'].min()  # Limit the update of the data to that was found in (older stuff is no longer retrievable
            values_df = pd.DataFrame(Value.objects.filter(investment=self, date__gte=update_start, day_scope=day_scope).values(
                'id', 'date', 'open_value', 'close_value', 'day_scope', 'source'))

            if values_df.empty:
                values_df = pd.DataFrame(columns=['id', 'Date', 'open_value', 'close_value', 'day_scope', 'source'])  # Needed for the merge
            else:
                values_df.rename(columns={"date": "Date"}, inplace=True)
                values_df['Date'] = pd.to_datetime(values_df['Date'])

            dividends_df = pd.DataFrame(Dividend.objects.filter(investment=self, date__gte=update_start, day_scope=day_scope).values(
                'id', 'date', 'value', 'source'))
            if dividends_df.empty:
                dividends_df = pd.DataFrame(columns=['id', 'Date', 'value', 'source'])  # Needed for the merge
            else:
                dividends_df.rename(columns={"date": "Date"}, inplace=True)
                dividends_df['Date'] = pd.to_datetime(dividends_df['Date'])

            if day_scope:  # Cleanup
                remove_df = values_df[~values_df['Date'].isin(yf_df['Date'])]
                for index, row in remove_df.iterrows():
                    Value.objects.filter(investment=self, date=row.Date).delete()

                remove_df = dividends_df[~dividends_df['Date'].isin(yf_df['Date'])]
                for index, row in remove_df.iterrows():
                    Dividend.objects.filter(investment=self, date=row.Date).delete()

            values_df = df.merge(values_df, on='Date', how='left')
            dividends_df = df.merge(dividends_df, on='Date', how='left')

            values_df['open_value'] = values_df['open_value'].astype('float64')
            values_df['close_value'] = values_df['close_value'].astype('float64')

            dividends_df['value'] = dividends_df['value'].astype('float64')
            dividends_df = dividends_df.loc[dividends_df['Dividends'] != 0]

            values_df = values_df[(~np.isclose(values_df["Close"], values_df["close_value"], atol=1e-3, rtol=1e-3)) |
                                  (~np.isclose(values_df["Open"], values_df["open_value"], atol=1e-3, rtol=1e-3))]
            dividends_df = dividends_df[~np.isclose(dividends_df["Dividends"], dividends_df["value"], atol=1e-3, rtol=1e-3)]

            Investment._process_value_diff(day_scope, values_df, last_update=self.last_updated)
            Investment._process_dividend_diff(day_scope, dividends_df)

    @classmethod
    def stale(cls, best_before=60, run_date: date = timezone.now().date()) -> QuerySet:

        cutoff = run_date - timedelta(days=best_before)

        active_investments = cls.objects.filter(
            Q(closed__isnull=True) | Q(closed__gt=run_date),
            account__closed__isnull=True,
        )

        stale_investments = active_investments.annotate(
            last_value_date=Max('values__date')
        ).filter(
            last_value_date__lt=cutoff
        )

        return stale_investments

    @staticmethod
    def test_symbol(symbol: str, region: Union [str, None] = None) -> str:
        """
        Using yfinance to validate a symbol based on region and some awful hard-coding
        If the lookup does not match return an empty str, else any augmented symbol
        """
        # todo:  Find a way to avoid this hardcoding
        region_values = {'Canada': ['.TO', '.NE'],
                         'USA': ['']}
        results = []
        if region in region_values:
            for exchange_key in region_values[region]:
                try:
                    results = yf.search.Search(symbol + exchange_key, max_results=100, news_count=0, raise_errors=False).quotes
                    if results:
                        break
                except:  # todo: Add the exception(s)
                    logger.error('API Failed')
                    break
        else:
            try:
                results = yf.search.Search(symbol, max_results=1, news_count=0, raise_errors=False).quotes
                if results and not results[0]['symbol'] == symbol:
                    results = []
            except:  # todo: Add the exception(s)
                logger.error('API Failed')

        return results[0]['symbol'] if results else ''

    def validate(self):
        self.searchable = False
        self.validated = True
        try:
            data = yf.Ticker(self.symbol).info
        except AttributeError as e:  # Call to yf failed
            logger.error('Symbol lookup on %s: %s' % (self.symbol, e))
            return
        except:  # Call to yf failed
            logger.error('Unknown lookup error on %s' % self.symbol)
            return
        try:
            self.region = data['country'] if 'country' in data else data['region']  # What do you expect with free data
            self.currency = data['currency']
            self.name = data['shortName']
        except KeyError:
            logger.error('Lookup data error on %s: %s' % (self.symbol, data))
            return
        self.searchable = True

    def save(self, *args, **kwargs):
        if 'update' in kwargs:
            do_update = kwargs.pop('update')
        else:
            do_update = False

        if self.inv_type == 'Trading':
            if self.user:  # Funds can not be owned by a user.
                self.user = None
            if not self.symbol.isupper():
                self.symbol = self.symbol.upper()
        else:
            if not self.name:
                self.name = self.symbol
            self.validated = True   # These type investments can never be searched or validated so just set it on definition
            self.searchable = False

        super().save(*args, **kwargs)
        if do_update:
            if not self.validated:
                self.validate()
                super().save(*args, **kwargs)
            if self.searchable:
                self.limited_update()


class Value(NormalizedDataModel):
    """
    The value of one share on this date.
    Only used for Trading InvType investments
    """
    investment: Investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='values')
    close_value: Decimal = models.DecimalField(decimal_places=3, max_digits=10)  # Up to $999,999 per share
    open_value: Decimal = models.DecimalField(decimal_places=3, max_digits=10)

    day_scope: bool = models.BooleanField(default=False)
    split_fixed: bool = models.BooleanField(default=False)

    class Meta:
        unique_together = ('date', 'investment', 'day_scope')

    def __str__(self):
        try:
            return f'{self.investment}:{self.date.strftime("%Y-%m-%d")} {self.close_value}'
        except Value.investment.RelatedObjectDoesNotExist:
            pass

    @classmethod
    def lookup(cls, lookup_date: date, symbol: str):
        try:
            lookup = Value.objects.filter(investment__symbol=symbol, date__lte=lookup_date).latest('date')
            return lookup.close_value if lookup.close_value != 0 else lookup.open_value
        except cls.DoesNotExist:
            logger.error('Attempt to lookup %s on date:%s = No Value' % (symbol, lookup_date))
            return 0

    @classmethod
    def create_values(cls, investment: Investment, value_date: pd.Timestamp, value: Decimal, source: int = DataSource.USER.value):
        """
        Create the needed value records based on the date and the rules for scope
        """
        now = datetime.now().date()
        if now >= IOOMDates().day_start:
            Value.objects.update_or_create(date=value_date, investment=investment, day_scope=True,
                                           defaults={'source': source, 'close_value': value, 'open_value': value})
        Value.objects.update_or_create(date=value_date.replace(day=1), investment=investment, day_scope=False,
                                       defaults={'source': source, 'close_value': value, 'open_value': value})

    @classmethod
    def rebuild(cls, investment: Investment, data: List, scope: str):
        """
        Rebuild all Value records based on expected data.   Called for Value accounts.
        data: List of [date, value,  scope, source]
        """
        existing = {item.date: item for item in cls.objects.filter(investment=investment, scope=scope)}
        for item in data:
            this_date = item[0]
            if scope == 'minute':
                this_date = pd.to_datetime(this_date).tz_convert('America/Toronto').replace(hour=9, minute=30).tz_convert('UTC')
            elif scope == 'month':
                this_date = this_date.replace(day=1)
            value = item[1]
            scope = item[2]
            source = item[3]
            if this_date not in existing:
                logger.info('Creating Value: %s %s %s %s' % (investment, this_date, value, scope))
                Value.objects.update_or_create(date=this_date, investment=investment, scope=scope, defaults={'source': source, 'value': value})
            else:
                if existing[this_date].source <= source and existing[this_date].close_value != value:
                    existing[this_date].source = source
                    existing[this_date].close_value = value
                    existing[this_date].save()
                del existing[this_date]

            for not_found in existing.keys():
                existing[not_found].delete()

    def save(self, *args, **kwargs):
        if not self.day_scope:
            self.date = self.date.replace(day=1)

        super().save(*args, **kwargs)


class Dividend(NormalizedDataModel):
    """
    Each Dividend Record will have a DividendRecorder record for each
    Account that held shares on the date of the dividend.   The end point
    will be a cashFlow record with the value = to the Dividend Value * number of units

                                                           +---------+
                                                           | Account | <-+
                                                           +---------+   |
                                                                |        |
                                                                v        |
    +----------+           +------------------+           +-----------+  |
    | Dividend |-----------| DividendRecorder |-----------| CashFlow  |  |
    +----------+           +------------------+           +-----------+  |
         * date                                                ^ * date  |
                                                               |         |
                                                            +---------+  |
                                                           | Position |--+  * Each Scope
                                                           +----------+
                                                               * date


    Store dividend payouts and update CashFlow and linkage records
    todo:  Day dividend values will be orphaned when the rollout of scope,  we need to account for this and cleanup the cashflow and linkage records
    """
    investment: Investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='dividends')
    value: Decimal = models.DecimalField(decimal_places=3, max_digits=10)  # Up to $999,999 per share
    day_scope: bool = models.BooleanField(default=False)
    class Meta:
        unique_together = ('date', 'investment', 'day_scope')

    def __str__(self):
        return f'Dividend({self.investment} - {self.date} @ {self.value}'

    @classmethod
    def accounts(cls, investment: Investment = None) -> QuerySet:
        if investment:
            investments = [investment.pk,]
        else:
            investments = cls.investments()
        return Account.objects.filter(id__in=Transaction.objects.filter(investment__in=investments).values_list('account', flat=True).distinct())

    @classmethod
    def scoped_df(cls) -> pd.DataFrame:

        columns = ('id', 'date', 'investment', 'value')
        delimiter = IOOMDates(build=False).day_start
        part1 = pd.DataFrame(cls.objects.filter(day_scope=False, date__lte=delimiter).values(*columns))
        part2 = pd.DataFrame(cls.objects.filter(day_scope=True, date__gt=delimiter).values(*columns))
        df = pd.concat([part1, part2])
        if df.empty:
            df = pd.DataFrame(columns=columns)

        df['date'] = pd.to_datetime(df['date'])
        df.rename(columns={"id": "dividend"}, inplace=True)
        df = df.astype({"value": "float64", "dividend": "Int64", "investment": "string"})
        return df

    @classmethod
    def investments(cls) -> QuerySet:
        """
        The distinct set of Investment objects that have recorded dividends
        """
        return Investment.objects.filter(symbol__in=cls.objects.values_list('investment', flat=True).distinct())

    def positions(self,  account: 'Account') -> QuerySet:
        """
        The full set of Position objects for this Dividend's Investment with this account
        todo: Not used.
        """
        return Position.objects.filter(investment=self, account=account, scope='day')

    def save(self, *args, **kwargs):
        if not self.day_scope:
            self.date = self.date.replace(day=1)

        self.value = Decimal(self.value)
        try:
            super().save(*args, **kwargs)
        except Exception as e:
            pass
        # self.update_cash()

    @classmethod
    def significant(cls) -> QuerySet:
        try:
            earliest_by_day = Dividend.objects.filter(scope='day').earliest('date').date
            query = Dividend.objects.filter(Q(scope='month', date__lt=earliest_by_day) | Q(scope='day'))
        except Dividend.DoesNotExist:
            query = Dividend.objects.all()
        return query

    @staticmethod
    def update_cash():
        """
        Run Daily to update and CASHFLOW records that should have been derived from Dividends
        """
        today = datetime.now().date()
        base_dates = IOOMDates(build=True).scoped_df
        base_dates.rename(columns=({'Date': 'date'}), inplace=True)

        div_df = Dividend.scoped_df()
        pos_df = Position.scoped_df()
        div_amt_df = DividendAmount.scoped_df()

        accounts = []
        to_process = []
        account: Account
        investment: Investment
        account_dict = {x.id: x for x in Account.objects.filter(managed=False)}
        for account in Account.objects.filter(managed=False):
            for investment in account.investments().filter(inv_type='Trading'):
                # Using standard dates,  fold in any dividend records
                df = base_dates.merge(div_df.loc[div_df['investment'] == investment.symbol], on='date', how='left')
                df['investment'] = df['investment'].ffill()
                df.dropna(subset=["investment"], inplace=True)

                # Fold in the positions held by this account for this symbol
                df = df.merge(pos_df.loc[(pos_df['account'] == account.pk) & (pos_df['investment'] == investment.symbol)], on=['date', 'investment'], how='left')
                df['quantity'] = df['quantity'].ffill()
                df['account'] = df['account'].ffill()
                df.dropna(subset=['quantity', 'dividend'], inplace=True)
                df = df.loc[df["quantity"] != 0]

                # Fold in current CASHFLOW records
                df = df.merge(div_amt_df, on='dividend', how='left')
                df = df.loc[df['altered'] != True]
                df["pay_date"] = df["date"] + pd.DateOffset(months=1)
                df = df.loc[df["pay_date"] <= pd.Timestamp('today').normalize()]
                df["pay_amt"] = df['quantity'] * df['value']
                df = df.loc[df['pay_amt'] != df['amount']]

                if not df.empty:
                    accounts.append(account.pk)
                    for row in df.itertuples(index=False):
                        note = f'Dividend Payout: {row.quantity} units @ ${row.value} of {row.investment}'
                        if pd.isna(row.cash_record):
                            cash = CashFlow.objects.create(account=account, investment=account.cash_investment, value=row.pay_amt, date=row.pay_date, note=note)
                            DividendAmount.objects.create(cash_record=cash, dividend_id=row.dividend).save()
                        else:
                            logger.info("Detected a DividendAmount divergence:  recid %s,  new:%s old:%s" % (row.divamt_id, row.amount, row.pay_amt))
                            divamt = DividendAmount.objects.get(pk=row.divamt_id)
                            divamt.amount = row.pay_amt
                            divamt.save()

        if accounts:
            for account in Account.objects.filter(pk__in=accounts).distinct():
                CashFlow.build_positions(account, account.cash_investment, CashFlow.objects.filter(account=account, investment=account.cash_investment))


class BaseContainer(models.Model):

    name: str = models.CharField(max_length=64, primary_key=False, help_text='The name to display for this Account/Portfolio')
    currency: str = models.CharField(max_length=3, null=False, blank=True, choices=CURRENCIES, default='CAD')

    class Meta:
        abstract = True


class Portfolio(BaseContainer):

    user: User = models.ForeignKey(User, related_name='portfolios', blank=False, null=False, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

    @property
    def container_type(self):
        return 'Portfolio'

    def get_absolute_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.id})

    def get_data_url(self):
        return reverse('portfolio_table', kwargs={'pk': self.id})

    def delete_url(self):
        return reverse('portfolio_delete', kwargs={'pk': self.id})

    def edit_url(self):
        return reverse('portfolio_edit', kwargs={'pk': self.id})

    @property
    def transactions(self):
        return Transaction.objects.filter(account__in=Account.objects.filter(portfolio=self))


class Account(BaseContainer):

    choices = INVESTMENT_CLASS[0:3]

    class Meta:
        unique_together = (('account_name', 'user'),)

    account_name: str = models.CharField(max_length=128, null=True, blank=True, help_text='Specific Account Name, use in imports from your trading account')
    managed: bool = models.BooleanField(default=True, help_text="Set when Dividends will be automatically reinvested")
    portfolio = models.ForeignKey(Portfolio, blank=True, null=True, on_delete=models.SET_NULL)
    acct_type: str = models.CharField(max_length=10, blank=True, null=True, choices=choices, default='Trading')
    positions = models.ManyToManyField(Investment, through='Position')
    closed: date = models.DateField(null=True, blank=True, help_text='Date when account was closed')
    user: User = models.ForeignKey(User, related_name='accounts', blank=False, null=False, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

    def can_close(self, this_date: date):
        if self.last_date and this_date < self.last_date:
            return f'Can not close this account before {self.last_date}'
        '''
        if transfer_to and self.portfolio and transfer_to.portfolio != self.portfolio:
            return f'Can only transfer to an account in portfolio: {self.portfolio}'
        if not transfer_to:
            scope = 'month' if this_date < IOOMDates(start=this_date, build=False).day_start else 'day'
            pos_date = this_date if scope == 'day' else this_date.replace(day=1)
        '''
        return ''

    def close(self, this_date: date, re_close: bool=False):
        if self.can_close(this_date):
            if not self.closed or re_close:
                if not self.closed:
                    self.closed = this_date
                    self.save()

        scope = 'month' if this_date < IOOMDates(start=this_date, build=False).day_start else 'day'
        pos_date = this_date if scope == 'day' else this_date.replace(day=1)
        for i in Investment.objects.filter(symbol__in=Position.objects.filter(account=self).exclude(investment__in=[self.cash_investment, self.funding_investment]).values_list('investment', flat=True).distinct()):
            p: Position = Position.objects.filter(account=self, investment=i, scope=scope).latest('date')
            if p.quantity > 0:
                try:
                    price = Value.objects.filter(date__lte=pos_date, investment=i, day_scope=(scope=='day')).latest('date')
                    price = price.close_value
                except Value.DoesNotExist:
                    price = 0
                Transaction.sell(account=self, investment=i, quantity=p.quantity, price=price, this_date=this_date, note='Auto-sold, closing of account')
        p: Position = Position.objects.filter(account=self, investment=self.funding_investment, scope=scope).latest('date')
        Funding.withdraw(this_date, p.quantity, self, note='Auto-withdraw, closing of account')
        CashFlow.objects.create(date=this_date, account=self, investment=self.cash_investment, value=0, balance=True, note='Clearing any cash value,  closing of account')
        self.rebuild()
        clear_caches(self.user)


    @cached_property
    def cash_investment(self) -> Investment:
        try:
            return Investment.objects.get(symbol=self.cash_investment_symbol)
        except Investment.DoesNotExist:
            logger.debug('Unable to find a Cash investment for %s', self)
            return None

    @property
    def cash_investment_symbol(self):
        return f'{self.pk}~Cash'

    @property
    def container_type(self):
        return 'Account'

    def get_absolute_url(self):
        return reverse('account_details', kwargs={'pk': self.pk})

    def get_data_url(self):
        return reverse('account_table', kwargs={'pk': self.pk})

    def close_url(self):
        return reverse('account_close', kwargs={'pk': self.id})

    def delete_url(self):
        return reverse('account_delete', kwargs={'pk': self.id})

    def edit_url(self):
        return reverse('account_edit', kwargs={'pk': self.id})

    @property
    def last_date(self) -> date:
        last = None
        xa_date = Transaction.objects.filter(account=self).latest('date').date if Transaction.objects.filter(account=self).exists() else None
        fund_date = Funding.objects.filter(account=self).latest('date').date if Funding.objects.filter(account=self).exists() else None
        value_date = ValueBalance.objects.filter(account=self).latest('date').date if ValueBalance.objects.filter(account=self).exists() else None
        cash_date = CashFlow.objects.filter(account=self).latest('date').date if CashFlow.objects.filter(account=self).exists() else None

        valid_dates = list(filter(None, [xa_date, fund_date, value_date, cash_date]))
        return max(valid_dates) if valid_dates else None


    @cached_property
    def funding_investment(self) -> Investment:
        try:
            return Investment.objects.get(symbol=self.funding_investment_symbol)
        except Investment.DoesNotExist:
            logger.debug('Unable to find a Funding investment for %s', self)
            return None

    @property
    def funding_investment_symbol(self):
        return f'{self.pk}~Funding'

    @property
    def transactions(self):
        return Transaction.objects.filter(account=self)

    @cached_property
    def value_investment(self) -> Union[Investment | None]:
        try:
            return Investment.objects.get(symbol=self.value_investment_symbol)
        except Investment.DoesNotExist:
            logger.debug('Unable to find a Value investment for %s', self)
            return None

    @property
    def value_investment_symbol(self):
        return f'{self.pk}~{self.name}'

    def investments(self, searchable=False, include_funding=False, include_cash=False) -> QuerySet:
        query = Q(symbol__in=(Transaction.objects.filter(account=self).values_list('investment', flat=True)))
        if include_cash or self.acct_type == 'Cash':
            query |= Q(symbol=self.cash_investment_symbol)
        if self.acct_type == 'Value':
            query |= Q(symbol=self.value_investment_symbol)
        if include_funding and not self.acct_type == 'Cash':
            query |= Q(symbol=self.funding_investment_symbol)
        if searchable:
            query &= Q(searchable=True)

        return Investment.objects.filter(query).distinct()

    def rebuild(self, values=False, positions=True, recreate=False):
        """
        Perhaps only for debugging but update all the Value's for this account and rebuild all the positions
        """
        if recreate:
            Position.objects.filter(account=self).delete()
        pd_now = pd.to_datetime('now', utc=True)
        for investment in self.investments(include_funding=False, include_cash=False):
            if values and investment.searchable:
                investment.limited_update()
            if positions:
                if investment.inv_type == 'Trading':
                    Transaction.build_positions(account=self, investment=investment)
        if self.cash_investment:
            query_base = CashFlow.objects.filter(account=self, investment=self.cash_investment)
            BaseCash.build_positions(self, self.cash_investment, query_base)
        if self.funding_investment:
            query_base = Funding.objects.filter(account=self, investment=self.funding_investment)
            BaseCash.build_positions(self, self.funding_investment, query_base)
        if self.value_investment:
            query_base = ValueBalance.objects.filter(account=self, investment=self.value_investment)
            ValueBalance.build_positions(self, self.value_investment, query_base)

    def save(self, *args, **kwargs):
        """
        Create a CASH investment
        """
        super().save(*args, **kwargs)
        """
        Value accounts have a ID~Value account, and a Funding account
        Trading accounts have a many Investment accounts,  a Funding Account and a ID~Cash account
        Cash accounts have a single ID~Cash account
        """


        if self.acct_type == 'Value':
            Investment.objects.update_or_create(inv_type='Value', symbol=self.value_investment_symbol, user=self.user,
                                                defaults={'country': self.user.profile.country, 'currency': self.user.profile.currency, 'searchable': False, 'validated': True})
        else:
            Investment.objects.update_or_create(inv_type='Cash', symbol=self.cash_investment_symbol, user=self.user,
                                                defaults={'country': self.user.profile.country, 'currency': self.user.profile.currency, 'searchable': False, 'validated': True})

        if self.acct_type != 'Cash':  # Value and Trading accounts have Funding
            Investment.objects.update_or_create(inv_type='Funding', symbol=self.funding_investment_symbol, user=self.user,
                                                defaults={'country': self.user.profile.country, 'currency': self.user.profile.currency, 'searchable': False, 'validated': True})

    def delete(self, *args, **kwargs):
        for i in Investment.objects.filter(account=self, inv_type__in=['Cash', 'Value', 'Funding'], symbol__startswith=f'{self.pk}-', user=self.user):
            i.delete()
        for p in Position.objects.filter(account=self):
            p.delete()
        super().delete(*args, **kwargs)


class Position(models.Model):
    """
    Position objects are used to build the basic quantity and price (aka - average cost) over time portion of a DataFrame
    CashFlow,  Funding, ValueAcct and Transaction objects are used to build the Position objects.
    Quantity for acc

    Position records have a scope of either 'month' or 'day'
    """

    account: Account = models.ForeignKey(Account, on_delete=models.CASCADE, help_text='The account this is linked to', related_name='accounts')
    investment: Investment = models.ForeignKey(Investment, on_delete=models.CASCADE, help_text='The investment this is linked to', related_name='positions')
    date: date = models.DateField(null=False, blank=True, help_text='The date of position')
    scope: str = models.CharField(max_length=10, blank=False, null=False, default='month')  # other choice is 'day'
    quantity: Decimal = models.DecimalField(decimal_places=3, max_digits=10, help_text='The quantity of units on this date')  # Up to 999,999.000 shares
    price: Decimal = models.DecimalField(decimal_places=3, max_digits=10, help_text='The avg price of each unit on this date')  # Up to $999,999.999 per share

    df_columns = ['Date', 'AccountID', 'Symbol', 'Quantity', 'Price']
    query_columns = ['day_value', 'account_id', 'investment__symbol', 'quantity', 'price']

    def __str__(self):
        return f'{super().__str__()} {self.quantity} @ ${self.price}'

    class Meta:
        unique_together = ('date', 'account', 'investment', 'scope')

    def __str__(self):
        return f'{self.__class__.__name__} {self.account}:{self.investment}({self.scope})'

    @classmethod
    def build(cls, account: Account, investment: Investment, data: List, scope: str, running_var='quantity', current_var='price'):
        """
        data: List of [date, running value, current value]

        """
        try:
            existing = {item.date: item for item in cls.objects.filter(account=account, investment=investment, scope=scope)}
        except InvalidOperation as e:  # I am not sure how this can happen
            logger.error('Failed build on %s - %s Reason:%s' % (account, investment, e))
            cls.objects.filter(account=account, investment=investment, scope=scope).delete()
            existing = {}

        for item in data:  # What if I have 2 items in the same date?  they would be filtered out in build_running_totals
            this_date = item[0]
            running = item[1]
            current = item[2]
            if this_date not in existing:
                # logger.info('Creating Position(%s): %s - %s %s %s@%s' % (scope, account.name, investment, this_date, running, current))
                try:
                    cls.objects.create(**{'account': account, 'investment':investment, 'date': this_date, running_var:running, current_var:current, 'scope':scope})
                except TypeError as e:
                    logger.debug('%s' % e)
                except IntegrityError as e:
                    logger.debug('%s' % e)

            else:
                try:
                    if getattr(existing[this_date], running_var) != running or getattr(existing[this_date], current_var) != current:
                        # logger.debug('Updating Position(%s): %s - %s %s %s@%s' % (scope, account.name, investment, this_date, running, current))
                        setattr(existing[this_date], running_var, running)
                        setattr(existing[this_date], current_var, current)
                        existing[this_date].save()
                except AttributeError as e:
                    logger.error('Failed to update %s - Attribute Error' % (e, existing[this_date]))
                if this_date in existing:
                    del existing[this_date]

        for not_found in existing.keys():
            try:
                existing[not_found].delete()
            except ValueError:
                pass
        clear_caches()

    @classmethod
    def scoped_df(cls):
        columns = ('date', 'account', 'investment', 'quantity', 'price')
        delimiter = IOOMDates(build=False).day_start
        part1 = pd.DataFrame(Position.objects.filter(scope='month', date__lte=delimiter).values(*columns))
        part2 = pd.DataFrame(Position.objects.filter(scope='day', date__gt=delimiter).values(*columns))
        df = pd.concat([part1, part2])
        if df.empty:
            df = pd.DataFrame(columns=columns)
        df = df.astype({"quantity": "float64", "price": "float64", "account": "Int64"})
        df['date'] = pd.to_datetime(df['date'])
        return df

    def save(self, *args, **kwargs):
        """
        Force price and quantity to be the correct case
        Update all Positions for this Account and Investment
        """
        if self.scope == 'day':
            self.date = to_utc_midnight(adjust_date(self.date))
        elif self.scope == 'month':
            self.date = to_utc_midnight(self.date.replace(day=1))
        super().save(*args, **kwargs)

    """
    Position objects are used to build the basic quantity and cost over time portion of a data frame
    Value objects build the value over time component
    Dividend objects build and Dividend representation

    CashFlow,  Funding, ValueAcct and Transaction objects are used to build (and rebuild) the Position objects.
    """

    def save(self, *args, **kwargs):
        """
        Force price and quantity to be the correct case
        """
        if self.quantity < 0:
            logger.error('%s:Negative quantity detected:%s -> %s' % (self.date, self, self.quantity))
            # self.quantity = Decimal(0)
        self.quantity = force_decimal(self.quantity)
        self.price = force_decimal(self.price)
        super().save(*args, **kwargs)


class BaseCash(NormalizedDataModel):
    """
    DB component for Cash, Funding and Value accounts
    The glue that holds this all together is accounts have dataframes that contain investments that build their data by Value records and Position records
        Value records are Investment + Date + Price for each month,  day and inter-day
        Position records are Account + Investment + Units + Price (for those units) for each month and day

        Cash, ValueAcct and  Funding always have a price of 1, and a quantity of the actual value.   Position records need to be calculated via a running total

    On save, we need to ensure we have Value records and Position records.  It is slow but only required on add and modify which do not happen often.
    """

    account: Account = models.ForeignKey(Account, on_delete=models.CASCADE, null=False, help_text='The account this is linked to')
    investment: Investment = models.ForeignKey(Investment, on_delete=models.CASCADE, null=False, help_text='The investment this is linked to', related_name='cash')
    value: Decimal = models.DecimalField(decimal_places=3, max_digits=10, null=False, help_text='The value on this date')
    balance: bool = models.BooleanField(default=False, help_text='Set when used to force a balance on a particular Day - Used to override deposit values')
    note = models.TextField(null=True, blank=True, help_text='Arbitrary text to describe where this funding came from/went to')

    def __str__(self):
        account = self.account.name if self.account else None
        return f'{self.__class__.__name__}:{account} {self.date} Value:{self.value} - {self.note}'

    def get_current_value(self, scope: str):
        """
        We can only have one Value record per Investment per scope per day.

        funding or cash records,  build value based on scope and update it based on self
        if valueAcct ,  the only
        """
        pass

    @staticmethod
    def build_positions(account: Account, investment: Investment, query_base: QuerySet):
        """
        Calculate the daily and monthly values based on Deposit and Balance settings,
        Call the build function of Position to do the actual work
        """

        Position.build(account, investment, build_running_totals(query_base.annotate(
            this_day=TruncDay('date'), price=DJValue(1, output_field=IntegerField())).order_by('date')
                                                                 .values('this_day', 'value', 'balance', 'price')), 'day')

        Position.build(account, investment, build_running_totals(query_base.annotate(
            this_day=TruncMonth('date'), price=DJValue(1, output_field=IntegerField())).order_by('date')
                                                                 .values('this_day', 'value', 'balance', 'price')), 'month')

    @classmethod
    def set_balance(cls, this_date: date, amount: int, account: Account, note: str = None, rebuild: bool = False, source: int = DataSource.USER):

        if not note:
            note = f'Balance of {amount} set on {timezone.now().date()}'

        cls(date=this_date, value=amount, account=account, balance=True, note=note, source=source).save(rebuild=rebuild)


    def save(self, *args, **kwargs):
        """
        Force price and quantity to be the correct case
        Update all Positions for this Account and Investment
        """
        rebuild = kwargs.pop('rebuild') if 'rebuild' in kwargs else False
        super().save(*args, **kwargs)
        if rebuild:
            self.build_positions(self.account, self.investment, self.__class__.objects.filter(account=self.account, investment=self.investment))


class CashFlow(BaseCash):
    """
    class for tracking CashFlow
    Possible Sources
        1) Funding  -> Funding record
        2) Purchases / Sales of Investments -> Transaction record
        2) Dividends -> Dividend Record
        3) Interest -> CashFlow Record
        4) Fee or Rebates -> CashFlow Record
        5) Corrections (manual intervention) - CashFlow Record - Balance Record
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.account_id:
            self.investment = self.account.cash_investment

    def delete(self, *args, **kwargs):
        rebuild = kwargs.pop('rebuild') if 'rebuild' in kwargs else False

        account = self.account
        investment = self.investment
        super().delete(*args, **kwargs)
        if rebuild:
            self.build_positions(account, investment, CashFlow.objects.filter(account=account, investment=investment))


class Funding(BaseCash):
    """
    class for tracking Funding
    """

    cash_record: 'CashFlow' = models.OneToOneField(CashFlow, null=True, blank=True, on_delete=models.CASCADE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.account_id:
            self.investment = self.account.funding_investment

    @classmethod
    def deposit(cls, amount: int, account: Account, this_date: date = datetime.today().date(), note: str = None, rebuild: bool = False, source: int = DataSource.USER.value) -> object:
        if not note:
            note = f'Deposited {amount} on {timezone.now().date()}'
        funding = abs(amount)
        fund = cls(date=this_date, value=funding, account=account, note=note, source=source)
        fund.save(rebuild=rebuild)
        return fund

    @classmethod
    def withdraw(cls, this_date: date, amount: int, account: Account, note: str = None, rebuild: bool = False, source: int = DataSource.USER):
        if not note:
            note = f'Withdrew {amount} on {timezone.now().date()}'
        funding = abs(amount) * -1
        fund = cls(date=this_date, value=funding, account=account, note=note, source=source)
        fund.save(rebuild=rebuild)
        return fund

    def save(self, *args, **kwargs):
        """
        Update/create cash flow if appropriate
        Update all Positions for this Account and Investment if requested
        """
        rebuild = kwargs['rebuild'] if 'rebuild' in kwargs else False

        if self.account.acct_type == 'Trading':
            # todo: wrap this in atomic
            if self.cash_record:
                self.cash_record.value = self.value
                self.cash_record.save(rebuild=rebuild)
            else:
                cf = CashFlow(date=self.date, value=self.value, account=self.account, note=f'From Funding {self.note}', source=DataSource.SYSTEM)
                cf.save(rebuild=rebuild)
                self.cash_record = cf

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        account = self.account
        investment = self.investment
        if self.cash_record:
            self.cash_record.delete()
            self.cash_record = None
        super().delete(*args, **kwargs)
        self.build_positions(account, investment, Funding.objects.filter(account=account, investment=investment))


class ValueBalance(BaseCash):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.account_id:
            self.investment = self.account.value_investment

    @classmethod
    def set(cls, account: Account, value: Decimal , this_date: date, source: int = DataSource.USER.value) -> object:
        value = abs(value)
        note = f'Set as {value} on {timezone.now().date()}'
        rec = cls(date=this_date, value=value, balance=True, investment=account.value_investment, account=account, note=note, source=source)
        rec.save(rebuild=True)
        return rec

    def save(self, *args, **kwargs):
        rebuild = kwargs.pop('rebuild') if 'rebuild' in kwargs else False
        self.balance = True
        super().save(*args, **kwargs, rebuild=rebuild)


class Transaction(NormalizedDataModel):
    """
        Each transaction is an individual Buy or Sell of an Investment.  They are used to calculate Positions, which are used as a quick way to
        calculate account holdings on a date and/or month basis

        Since Transaction are added infrequently and Positions are few.   We will recalculate all position on each transaction save()
    """

    account: Account = models.ForeignKey(Account, on_delete=models.CASCADE, null=False, help_text='The account this is linked to')
    investment: Investment = models.ForeignKey(Investment, on_delete=models.CASCADE, null=False, help_text='The investment this is linked to', related_name='transactions')
    quantity: Decimal = models.DecimalField(decimal_places=3, max_digits=10, null=False, help_text='The quantity of units')  # Up to 999,999.000 shares
    price: Decimal = models.DecimalField(decimal_places=3, max_digits=10, null=False, help_text='The price of each unit (and the time of purchase')  # Up to $999,999 per share
    note = models.TextField(null=True, blank=True, help_text='Arbitrary text to describe where this Transaction came from/went to')
    cash_record: CashFlow = models.ForeignKey(CashFlow, null=True, blank=True, on_delete=models.CASCADE, help_text='Cash Flow Record')

    @property
    def action_str(self):
        if self.quantity > 0:
            return 'Buy'
        else:
            return 'Sell'

    @staticmethod
    def build_positions(account: Account, investment: Investment):
        """
        Calculate the daily and monthly values based on Deposit and Balance settings,
        Call the build function of Position to do the actual work
        """

        Position.build(account, investment, build_running_totals(Transaction.objects.filter(account=account, investment=investment)
                                                                 .annotate(this_day=TruncDay('date'), value=F("quantity"),
                                                                           balance=DJValue(False, output_field=BooleanField())).order_by('date')
                                                                 .values('this_day', 'value', 'balance', 'price')), 'day')

        Position.build(account, investment, build_running_totals(Transaction.objects.filter(account=account, investment=investment)
                                                                 .annotate(this_day=TruncMonth('date'), value=F("quantity"),
                                                                           balance=DJValue(False, output_field=BooleanField())).order_by('date')
                                                                 .values('this_day', 'value', 'balance', 'price')), 'month')

    @classmethod
    def buy(cls, account: Account, investment: Investment, quantity: int, price: int , this_date: date, note: str = None, rebuild: bool = False, source: int = DataSource.USER.value) -> object:
        if not note:
            note = f'Purchased {quantity} units @ {price} on {timezone.now().date()}'
        quantity = abs(quantity)
        rec = cls(date=this_date, quantity=quantity, price=price, account=account, investment=investment, note=note, source=source)
        rec.save(rebuild=rebuild)
        return rec

    @classmethod
    def sell(cls, account: Account, investment: Investment, quantity: int, price: int , this_date: date, note: str = None, rebuild: bool = False, source: int = DataSource.USER.value) -> object:
        if not note:
            note = f'Sold {quantity} units @ {price} on {timezone.now().date()}'
        quantity = abs(quantity) * -1
        rec = cls(date=this_date, quantity=quantity, price=price, account=account, investment=investment, note=note, source=source)
        rec.save(rebuild=rebuild)
        return rec

    @property
    def is_major(self):
        return True

    def save(self, *args, **kwargs):
        """
        Force price correct case
        create / update cash_record
        rebuild positions if requested
        """
        rebuild = kwargs.pop('rebuild') if 'rebuild' in kwargs else False
        self.price = abs(self.price)

        if self.account.acct_type == 'Trading':
            value = float(self.quantity) * float(self.price)
            if self.cash_record:
                self.cash_record.value = value * -1
                self.cash_record.save(rebuild=rebuild)
            else:
                cf = CashFlow(account=self.account, date=self.date, value=value * -1, note=self.note, source=self.source)
                cf.save(rebuild=rebuild)
                self.cash_record = cf

        try:
            super().save(*args, **kwargs)
        except Exception as e:
            logger.error('Failed to save')

        if not self.investment.searchable:  # Create the needed Value records
            if self.price != 0:  # Price is 0 when the transaction was a reinvested
                Value.create_values(self.investment, self.date, self.price, self.source)

        if rebuild:
            self.build_positions(account=self.account, investment=self.investment)

    def delete(self, *args, **kwargs):
        # Your custom logic here

        account = self.account
        investment = self.investment
        if self.cash_record:
            self.cash_record.delete()
            self.cash_record = None
        super().delete(*args, **kwargs)
        self.build_positions(account, investment)

    @property
    def value(self):
        return abs(self.quantity * self.price)


class DividendAmount(models.Model):
    """
    These records are used to tie a Dividend Ex-dividend date and the Payment date,  the payment date is then used to build a CashFlow record.
    The time span between a Ex-dividend date and Payment date is by default 1 month.

    Dividend are only converted to CASH for accounts that are not managed,  i.e. you take care of them yourself

        todo: make this configurable on the investment
        todo: make this record editable by the user.   They can records a differant payout if they wish (some of mine of off by a few cents)
    """
    dividend: Dividend = models.ForeignKey(Dividend, null=False, on_delete=models.CASCADE, help_text="This Dividend record")
    cash_record: 'CashFlow' = models.OneToOneField(CashFlow, null=False, blank=False, on_delete=models.CASCADE)
    altered: bool = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.cash_record.account.name}:{self.dividend.investment} {self.cash_record.value}'

    @classmethod
    def build(cls, accounts: Union[QuerySet | None] = None, investments: Union[QuerySet | None] = None):
        if not accounts:
            accounts = Account.objects.filter(managed=False)
        else:
            accounts = accounts.exclude(managed=False)
        if accounts.count() == 0:
            return

        if not investments:
            investments = Investment.objects.filter(searchable=True)
        else:
            investments = investments.exclude(searchable=False)
        if investments.count() == 0:
            return

        values = ['id', 'dividend__date', 'dividend__id', 'dividend__investment', 'account__id', 'amount', 'altered']
        df = Dividend.as_dataframe(investment=investments, account=accounts, scope='day', audit=True)
        if df.empty:
            return

        existing_df = pd.DataFrame(filter_by_account_and_investment(cls.objects.all(), account=accounts, investment=investments).values(*values))
        if existing_df.empty:  # Add in the merge result columns
            df['amount'] = 0
            df['id'] = 0
        else:
            existing_df.rename(columns={'dividend__date': 'Date', 'dividend__investment': 'Symbol', 'account__id': 'AccountID'}, inplace=True)
            df = df.merge(existing_df, on=['Date', 'AccountID', 'Symbol'], how='left')
            df[['amount', 'id']] = df[['amount', 'id']].fillna(0)

        df = df.loc[(df['amount'] == 0) | (df['amount'] != df['DivAmount'])]

        for index, row in df.iterrows():
            note = f'Dividends from {row.Symbol} {row.Quantity} units at {row.DivValue}'
            if row.id == 0:
                try:
                    dividend = Dividend.objects.get(investment__symbol=row.Symbol, date=row.Date, value=row.DivValue)
                    account = Account.objects.get(id=row.AccountID)
                    record = cls(account=account, dividend=dividend)
                except Dividend.DoesNotExist:
                    logger.error('Could not look up Dividend for %s on %s with a value of %s' % (row.Symbol, row.Date, row.DivValue))
                    continue
                except Dividend.DoesNotExist:
                    logger.error('Could not look up Account with id %s' % row.AccountID)
                    continue
            else:
                record = cls.objects.get(id=row.id)

            record.amount = row.DivAmount
            record.save(cash_note=note)

        query_base = CashFlow.objects.filter(account=accounts, investment=investments)
        BaseCash.build_positions(accounts, investments, query_base)

    def delete(self, *args, **kwargs):
        cashflow = self.cash_record
        super().delete(*args, **kwargs)
        cashflow.delete()

    @classmethod
    def scoped_df(cls):
        columns = ('pk', 'dividend', 'cash_record', 'cash_record__value', 'altered')
        df = pd.DataFrame(DividendAmount.objects.values(*columns))
        if df.empty:
            df = pd.DataFrame(columns=columns)
        df.rename(columns=({'pk': 'divamt_id', 'cash_record__value': 'amount'}), inplace=True)
        df = df.astype({"divamt_id": "Int64", "dividend": "Int64", "amount": "float64", "cash_record": "Int64"})
        return df

