"""
Build a DataFrame based on User
"""
import logging
import pandas as pd
import numpy as np
import time

from datetime import date
from dateutil.relativedelta import relativedelta
from pandas import DataFrame, Timestamp
from typing import Union, Dict

from itertools import groupby

from django.core.cache import cache
from django.contrib.auth.models import User

from django.db.models import QuerySet, OuterRef, Subquery
from django.db.models.functions import Trunc, TruncDay, TruncMonth

from base.models import Inflation
from base.utils import df_start, to_utc_midnight
from base.ioom_dates import IOOMDates, IOOM_RANGES
from wealth.models import Account, CashFlow, Portfolio, Dividend, Funding, Investment, Position, Value

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60  # 60 minutes

"""
volatile_df - All searchable by last of the month for history less then one year,  by the day after that
    - dividends_df - All searchable by last of the month for history less then one year,  by the day after that
hourly_df - All searchable by 15m increments for the past 4 weeks (I can pull the values in 2 secs)
          - Source for today's gain.  Not the day should always be included with results,  it will only update starting at 9:45 AM
          - Should update volatile_df well
static_df

"""


class WealthDF:
    def __init__(self, user: User, scope: str = None, date_range: str = None):
        if not scope and not date_range:
            scope = 'month'
        if not scope and date_range:
            scope = IOOMDates.range_to_scope(date_range)

        assert scope in ['day', 'month']

        self.user: User = user
        self.scope: str = scope

        self._accounts = Account.objects.filter(user=self.user)
        self._investments = Investment.objects.filter(account__in=self._accounts).distinct()

        self._account_lookup = dict(self._accounts.values_list('id', 'name'))
        self._portfolio_lookup = dict(Portfolio.objects.filter(id__in=self._accounts.values_list('portfolio_id', flat=True).distinct()).values_list('id', 'name'))

        self._positions = Position.objects.filter(investment__in=self._investments, account__in=self._accounts, scope=scope)

        if self._positions.count():
            self.start = self._positions.earliest('date').date
            if self.scope == 'day':
                self.dates = IOOMDates(start=self.start).days_df
            else:
                self.start = self.start.replace(day=1)
                self.dates = IOOMDates(start=self.start).months_df
            self.end = self.dates['Date'].max()
        else:
            self.start = None
            self.dates = DataFrame()
            logger.warning('No position data exists for user:%s, scope:%s' % (self.user, self.scope))

    @property
    def df(self) -> DataFrame:
        if self.dates.empty:
            logger.warning('No position data exists for user:%s, scope:%s' % (self.user, self.scope))
            return DataFrame()

        base_key = self.df_cache_key

        if self.scope == 'day':
            try:
                return cache.get_or_set(
                    f'{base_key}_day',
                    lambda: self.build_dataframe(),
                    timeout=CACHE_TTL,
                )
            except Exception as e:
                logger.error('Failed - dataframe user:%s Error:%s' % (self.user, e))

        elif self.scope == 'month':
            try:
                return cache.get_or_set(
                    f'{base_key}_month',
                    lambda: self.build_dataframe(),
                    timeout=CACHE_TTL,
                )
            except Exception as e:
                logger.error('Failed - dataframe user:%s Error:%s' % (self.user, e))

        return DataFrame()

    def build_dataframe(self) -> DataFrame:
        """
        This is the "blessed" (and tested) way to build a DataFrame for IOOM representation.
        scope - either day or month
        account: A set or not of all the accounts you want included (filters Positions)
        investment: A set or not of all the Investments you want included (filter Positions) - Special note Funding and Cash need to be excluded if not wanted
        include_dividends: bool - False,  included with each row any dividends that would be earned

        start is used to build a dates_df dataframe from the very first possible date.
        """
        logger.debug('Get/Set DF for user:%s scope:%s' % (self.user, self.scope))

        positions_df = self.build_positions_df_v2()
        value_df = self.build_values_df()

        result = positions_df.merge(value_df, on=['Date', 'Symbol'], how='left')

        result['Value'] = result['Value'].astype('float64').fillna(1)  # Set the default value for everything that is not managed via 'Value' records
        result['InvValue'] = result['Quantity'] * result['Value']
        dividends = self.build_dividends_df(positions_df=positions_df)
        if not dividends.empty:
            result = result.merge(dividends, on=['Date', 'Symbol', 'AccountID'], how='left')
            result[['DivAmount', 'DivValue']] = result[['DivAmount', 'DivValue']].fillna(0)
            result['DivTotal'] = result['DivTotal'].ffill()
        else:
            result[['DivTotal', 'DivAmount', 'DivValue']] = 0
        result[['Value', 'InvValue']] = result[['Value', 'InvValue']].fillna(0)
        result.dropna(subset=["AccountID", "Symbol"], inplace=True)
        result["Symbol"] = result["Symbol"].str.split("~").str[-1]  # Cleanup alias names
        if 'Estimated' in result.columns:
            result['Estimated'] = result['Estimated'].astype('boolean').fillna(True)
        result = self.calc_inflation(result, column='Funding')
        if 'Funding_infl' in result.columns:
            result.rename(columns={"Funding_infl": "InflatedCost"}, inplace=True)
        return result

    def build_dividends_df(self, positions_df: DataFrame) -> pd.DataFrame:

        """
        Build a dataframe based on Dividend data overlaid with TimeSeries data appropriate for the scope
        Columns for the dataframe are:
            columns = ['Date', 'Symbol', 'Value']
        Any DateTime without a Value will be set to 0
        audit: is used when building a DataFrame for the population of CashFlow records (see DividendAmount)
        """
        start = positions_df['Date'].min()
        day_scope = True if self.scope == 'day' else False
        columns = ['Datetime', 'Symbol', 'Dividend']

        query = Dividend.objects.filter(investment__in=self._investments, day_scope=day_scope, date__gte=start)
        div_df = pd.DataFrame(query.values('value', 'date', 'investment'))
        if div_df.empty:
            return pd.DataFrame(columns=columns)

        div_df['Date'] = pd.to_datetime(div_df['date'])

        div_df.rename(columns={"investment": "Symbol", 'value': 'DivValue'}, inplace=True)
        div_df['DivValue'] = div_df['DivValue'].astype('float64')

        df = positions_df[['Date', 'AccountID', 'Symbol', 'Quantity']]
        df = df.merge(div_df, on=['Date', 'Symbol'], how='right')  # Clears out dates that don't apply since we are dealing with the largest possible set
        df.dropna(subset=["AccountID"], inplace=True)  # Clear out values prior to the first good record - Testing,  50.1 MB drops to 967 KB

        # This groupby is required in the VDY.TO example of two entries in the same month - Not needed with scoped Dividends
        # df = df.groupby(['Date', 'AccountID', 'Symbol'], as_index=False).agg(DivValue=('DivValue', 'sum'), Quantity=('Quantity', 'mean'))

        df['DivAmount'] = df['DivValue'] * df['Quantity']  # Calculate the payout

        df = df.sort_values(["AccountID", "Symbol", "Date"])
        df["DivTotal"] = df.groupby(["AccountID", "Symbol"])["DivAmount"].cumsum()

        df.drop(columns=['Quantity', 'date'], inplace=True)  # It will be re-added with the merge

        # Fix up the holes
        df[['DivValue', 'DivAmount']] = df[['DivValue', 'DivAmount']].fillna(0)
        df['DivTotal'] = df['DivTotal'].fillna(0)
        return df

    def build_positions_df(self) -> DataFrame:
        """
        Build a dataframe based on Position data overlaid with TimeSeries data appropriate for the scope and subclass
        force_start will cause the dataframe to span to the first Position date (based on account and investment parameters)
        requires
        """
        df_columns = ['Date', 'AccountID', 'PortfolioID', 'Symbol', 'Quantity', 'Price']
        # todo: I can not just use the default day calendar becuase postions are older.  This fullgird is very expensive,  Maybe I could
        # look into sorting by symbol and taking the last value if it less then day start ???
        dates = IOOMDates(start=self.start, force=True, build=True)
        dates = dates.days_df if self.scope == 'day' else dates.months_df
        if dates.empty:
            logger.warning('No position data exists for user:%s, scope:%s' % (self.user, self.scope))
            return DataFrame(columns=df_columns)

        query_columns = ['date', 'account_id', 'account__portfolio', 'investment__symbol', 'investment__inv_type', 'quantity', 'price']

        queryset = self._positions.values(*query_columns).order_by('account_id', 'investment__symbol', 'date')
        df = DataFrame(queryset)
        df['Date'] = pd.to_datetime(df['date'])

        df.rename(columns={"account_id": "AccountID", "account__portfolio": "PortfolioID", "investment__symbol": "Symbol",
                           "investment__inv_type": "InvType", "quantity": "Quantity", "price": "Price"}, inplace=True)
        # from chatgpt
        full_grid = pd.MultiIndex.from_product([dates['Date'], df['AccountID'].unique(), df['Symbol'].unique()], names=['Date', 'AccountID', 'Symbol'])

        merged = (df.set_index(['Date', 'AccountID', 'Symbol']).reindex(full_grid).reset_index())
        merged.sort_values(['AccountID', 'Symbol', 'Date'], inplace=True)
        merged = merged.astype({"Quantity": "float64", "Price": "float64"})
        merged['InvType'] = merged.groupby(['AccountID', 'Symbol'])['InvType'].ffill()
        merged['PortfolioID'] = merged.groupby(['AccountID'])['PortfolioID'].ffill()
        merged.dropna(subset=["InvType"], inplace=True)  # Clear out values prior to the first good record - Testing,  50.1 MB drops to 967 KB
        merged.loc[merged['InvType'] != 'Trading', 'Price'] = 1.0

        merged['i_q'] = merged['Quantity'].interpolate(method='linear')  # used to fill the quantity gaps in Cash and Value Accounts
        merged.loc[(merged['InvType'] == 'Cash') | (merged['InvType'] == 'Value'), 'Quantity'] = merged.loc[merged['InvType'] != 'Trading', 'i_q']
        merged[['Quantity', 'Price']] = merged[['Quantity', 'Price']].ffill().fillna(0)
        merged['PortfolioID'] = pd.to_numeric(merged['PortfolioID'], errors='coerce').fillna(0)
        merged = merged.drop(columns=['i_q', 'date'])

        return self.dates.merge(merged, on='Date', how='left')  # Strip out anything we don't need

    def build_positions_df_v2(self) -> DataFrame:
        """
        V2,  not currently used.   Avoid the HUGE dataframe for scope = day.   100 Invesments * 250 days * 20 years
        Trying to extract all and join via FFILL maybe instead I could pull the earlier and collect the last value per investment to the first row

        Build a dataframe based on Position data overlaid with TimeSeries data appropriate for the scope and subclass
        force_start will cause the dataframe to span to the first Position date (based on account and investment parameters)
        requires
        """
        df_columns = ['Date', 'AccountID', 'PortfolioID', 'Symbol', 'Quantity', 'Price']
        # todo: I can not just use the default day calendar becuase postions are older.  This fullgird is very expensive,  Maybe I could
        # look into sorting by symbol and taking the last value if it less then day start ???
        if self.dates.empty:
            logger.warning('No position data exists for user:%s, scope:%s' % (self.user, self.scope))
            return DataFrame(columns=df_columns)

        query_columns = ['date', 'account_id', 'account__portfolio', 'investment__symbol', 'investment__inv_type', 'quantity', 'price']

        if self.scope == 'month':
            df = DataFrame(self._positions.values(*query_columns).order_by('account_id', 'investment__symbol', 'date'))
        else:
            delimiter = IOOMDates().day_start
            latest = self._positions.filter(
                date__lte=delimiter,
                investment=OuterRef('investment'),
                account_id=OuterRef('account_id'),  # ← critical
            ).order_by('-date')

            part1 = DataFrame(self._positions.filter(quantity__gt=0, id__in=Subquery(latest.values('id')[:1])).values(*query_columns))
            part1['date'] = delimiter
            part2 = DataFrame(self._positions.filter(date__gt=delimiter).values(*query_columns))
            df = pd.concat([part1, part2])

        df['Date'] = pd.to_datetime(df['date'])
        df.rename(columns={"account_id": "AccountID", "account__portfolio": "PortfolioID", "investment__symbol": "Symbol",
                           "investment__inv_type": "InvType", "quantity": "Quantity", "price": "Price"}, inplace=True)

        # from chatgpt
        full_grid = pd.MultiIndex.from_product([self.dates['Date'], df['AccountID'].unique(), df['Symbol'].unique()], names=['Date', 'AccountID', 'Symbol'])
        merged = (df.set_index(['Date', 'AccountID', 'Symbol']).reindex(full_grid).reset_index())
        if self.scope == 'day':  # Add in the positions prior to the day lower limit
            merged = pd.concat([merged, df.loc[df['Date'] < merged['Date'].min()]])
        merged.sort_values(['AccountID', 'Symbol', 'Date'], inplace=True)

        merged['InvType'] = merged.groupby(['AccountID', 'Symbol'])['InvType'].ffill()
        merged['PortfolioID'] = merged.groupby(['AccountID'])['PortfolioID'].ffill()
        merged.dropna(subset=["InvType"], inplace=True)  # Clear out values prior to the first good record - Testing,  50.1 MB drops to 967 KB

        merged.loc[merged['InvType'] != 'Trading', 'Price'] = 1.0

        merged = merged.astype({"Quantity": "float64", "Price": "float64"})

        # Step 1,   Trading accounts with a price of 1 use Quantity for the value,  so don't Forward Fill them.
        mask = ((merged['InvType'] == 'Trading') & (merged['Price'] != 1))
        merged.loc[mask, 'Quantity'] = (
            merged.loc[mask, 'Quantity']
            .ffill()
        )
        # Prices is not the value,  it is the price we paid,  so like quantity forward fill
        merged.loc[mask, 'Price'] = (
            merged.loc[mask, 'Price']
            .ffill()
        )

        # Funding should also be Forward Filled
        mask = merged['InvType'] == 'Funding'
        merged.loc[mask, 'Quantity'] = (
            merged.loc[mask, 'Quantity']
            .ffill()
        )

        # Remove the 0 values to prevent interpolate from moving quantities down to 0 - previous trading fills mean they are excluded already
        mask = merged['Quantity'] != 0
        merged.loc[mask, 'Quantity'] = (
            merged.loc[mask]
            .groupby(['AccountID', 'Symbol'])['Quantity']
            .transform(lambda x: x.interpolate(method='linear'))
        )

        # What ever is left can be forward filled,  or set to 0
        merged[['Quantity', 'Price']] = merged[['Quantity', 'Price']].ffill().fillna(0)
        merged['PortfolioID'] = pd.to_numeric(merged['PortfolioID'], errors='coerce').fillna(0)  # Set to 0, accounts outside of portfolios can be filtered
        merged = merged.drop(columns=['date'])  # No longer required

        return self.dates.merge(merged, on='Date', how='left')  # Strip out anything we don't need

    def build_values_df(self) -> DataFrame:
        """
        Build a dataframe based on Value data overlaid with TimeSeries data appropriate for the scope
        Columns for the dataframe are:
            columns = ['DateTime', 'Symbol', 'Value']
        Any DateTime without a Value will be set to 0

        """
        day_scope = self.scope == 'day'
        columns = ['Date', 'Symbol', 'Value', 'Estimated']
        query = Value.objects.filter(investment__in=self._investments, day_scope=day_scope)

        if not query.count():
            return DataFrame(columns=columns)

        queryset = query.values('date', 'investment__symbol', 'investment__inv_type', 'close_value', 'day_scope').order_by('investment__symbol', 'date')

        df = DataFrame(queryset)
        df['Date'] = pd.to_datetime(df['date'])
        df.rename(columns={"investment__symbol": "Symbol", "investment__inv_type": "type", "close_value": "Value"}, inplace=True)


        full_grid = pd.MultiIndex.from_product([self.dates['Date'], df['Symbol'].unique()], names=['Date', 'Symbol'])
        #full_grid = pd.MultiIndex.from_product([dates['Date'], self.investments.values_list('symbol', flat=True)], names=['Date', 'Symbol'])

        merged = (df.set_index(['Date', 'Symbol']).reindex(full_grid).reset_index())
        merged.sort_values(['Symbol', 'Date'], inplace=True)
        merged = merged.astype({"Value": "float64"})
        merged['Estimated'] = False
        merged.loc[merged['Value'].isna(), 'Estimated'] = True

        merged['Value'] = merged.groupby('Symbol')['Value'].transform(
            lambda s: s.interpolate()
        )
        merged.groupby('Symbol').ffill()
        merged.dropna(subset=["Value"], inplace=True)
        merged.drop(columns=['date', 'type', 'day_scope'], inplace=True)

        non_value = self._investments.exclude(inv_type='Trading').values_list('symbol', flat=True)
        full_grid = pd.MultiIndex.from_product([self.dates['Date'], non_value], names=['Date', 'Symbol'])
        full_grid = full_grid.to_frame(index=False)
        full_grid['Value'] = 1
        full_grid['Estimated'] = False

        return pd.concat([merged, full_grid])

    @property
    def df_cache_key(self):
        version = int(time.time() // CACHE_TTL)
        return f"user_dataframe:{self.user.username}:df:v{version}"

    def calc_inflation(self, df: DataFrame, column: str = None) -> DataFrame:
        """
        Calculate effect of inflation.
        create new column <column>_infl if column is provided
        create column Inflation if not provided

        scope must be month

        user = AppUser.objects.get(username='sparky')
        from wealth.dataframes import WealthDF
        dfo = WealthDF(user=user, scope='month')

        """
        if not (isinstance(df, DataFrame) and self.scope == 'month' and 'Date' in df.columns):
            logger.warning('Inflation not support with this dataframe')
            return df

        if 'Inflation' not in df.columns:
            dfi = DataFrame(Inflation.objects.values('date', 'inflation'))
            if not dfi.empty:
                dfi.columns = ['Date', 'Inflation']
                dfi['Date'] = pd.to_datetime(dfi['Date'])
                df = df.merge(dfi, on='Date', how='left')
                df['Inflation'] = df['Inflation'].astype('float64').fillna(0)
            else:
                df['Inflation'] = 0
        if not column:
            return df

        new_column = column + '_infl'
        if new_column in df.columns or len(df.loc[df['InvType'] == column]) == 0:
            return df

        # todo - should I check if we have multiple entries?
        df['Contribution'] = df.loc[df['InvType'] == column].groupby(['AccountID'])['InvValue'].diff()
        df['Contribution'] = df['Contribution'].fillna(0)

        adjusted = []
        balance = 0
        account = 0
        df = df.sort_values(['AccountID', 'Date']).reset_index()
        for row in df.itertuples():
            if row.InvType == column:
                if row.AccountID != account:
                    balance = row.InvValue  # First contribution is always 0 based on the behaviour of diff()
                    account = row.AccountID
                balance *= (1 + row.Inflation / 100)
                balance += row.Contribution
                adjusted.append(balance)
            else:
                adjusted.append(np.nan)
        df[new_column] = adjusted
        df = df.sort_values(['Date'])
        ndf = df.loc[df['InvType'] == 'Funding'].sort_values(['AccountID', 'Date'])
        return df

    def totals(self, filtered=False) -> pd.DataFrame:
        """
        The totals by InvType
        """
        df = self.df if not filtered else self.filtered
        return df.groupby(['Date', 'InvType'])[['InvValue', 'DivTotal']].agg('sum').reset_index()

    @staticmethod
    def on_datetime(odf: DataFrame, run_date: Union[date, Timestamp, None] = None) -> DataFrame:
        if isinstance(run_date, Timestamp):
            run_date = run_date.date()
        else:
            run_date = pd.to_datetime(run_date)

        if odf.empty or 'Date' not in odf.columns:
            return odf

        if not run_date:
            run_date = odf['Date'].max()

        return odf.loc[odf['Date'] == run_date].reset_index()

    def by_range(self, value: str):
        if self.df.empty:
            return self.df
        else:
            start = IOOMDates().range_start(value)
            return self.df.loc[self.df['Date'] >= start].reset_index()

    def set_names(self, df: DataFrame):
        """
        Update (if necessary) the dataframe with real account and portfolio names
        """
        if not df.empty:

            columns = df.columns

            if 'AccountID' in columns and 'AccountName' not in columns:
                df["AccountName"] = df["AccountID"].map(self._account_lookup)
            if 'PortfolioID' in columns and 'PortfolioName' not in columns:
                df["PortfolioName"] = df["PortfolioID"].map(self._portfolio_lookup)
        return df

    def investment_summary_values(self, df: DataFrame, run_date: Timestamp) -> DataFrame:
        """
        Key metrics for Trading Investments on a particular day
        """
        df = df.loc[(df['InvType'] == 'Trading') & (df['Date'] == run_date) & (df['Quantity'] > 0)].reset_index()
        df['Cost'] = df['Quantity'] * df['Price']

        equity_data = df.groupby(['Date', 'Symbol']).agg(
            {'Quantity': 'sum', 'Value': 'max', 'DivValue': 'max', 'AccountID': 'max', 'PortfolioID': 'max',
             'DivTotal': 'sum', 'InvValue': 'sum', 'Price': 'max', 'Cost': 'sum', 'InvType': 'first'}).reset_index()

        equity_data.replace(np.nan, 0, inplace=True)
        equity_data.sort_values(by=['InvValue', 'Quantity', 'Symbol'], inplace=True, ascending=[False, False, True])

        equity_data['Gain'] = equity_data['InvValue'] - equity_data['Cost'] + equity_data['DivTotal']
        equity_data['GainPercent'] = equity_data['Gain'] / equity_data['Cost'] * 100

        return equity_data

    def container_values_by_date_df(self, ldf):
        """
        Return a dataframe, that has the ordered list of summary values (Cash, Funding, Trading, Value) ordered by Date (newest to oldest)
        """
        if not ldf.empty:
            saveit = ldf
            ldf = ldf.groupby(['Date', 'InvType']).agg({'InvValue': 'sum', 'Estimated': 'any'}).reset_index()
            g1 = ldf.pivot(index='Date', columns='InvType', values='InvValue').reset_index()
            g1 = g1.fillna(0)
            g2 = ldf.pivot(index='Date', columns='InvType', values='Estimated').reset_index()
            g2 = g2.fillna(False)
            ldf = g1.join(g2, rsuffix='_est')
            ldf = self.force_columns(ldf)
            # Create the Totals
            ldf['Total'] = ldf['Trading'] + ldf['Value']
            ldf['Total_est'] = ldf['Value_est'] | ldf['Trading_est']
            ldf.sort_values('Date', ascending=False, inplace=True)
        return ldf

    @staticmethod
    def _container_change(cdf: DataFrame) -> Dict:
        last = previous = first = percent = 0

        if cdf.empty:
            run_date = Timestamp('today').date()
        else:
            cdf = cdf.groupby(['Date', 'InvType']).agg({'InvValue': 'sum'}).reset_index()
            cdf = cdf.pivot(index='Date', columns='InvType', values='InvValue').reset_index()
            cdf.sort_values('Date', inplace=True)
            prev_index = -2 if len(cdf) > 1 else 0  # Just in case we are provided a DF of len 1
            run_date = cdf['Date'].iloc[-1]

            if 'Trading' in cdf.columns and 'Value' in cdf.columns:
                cdf[['Trading', 'Value']] = cdf[['Trading', 'Value']].fillna(0)
                last = cdf['Trading'].iloc[-1] + cdf['Value'].iloc[-1]
                previous = cdf['Trading'].iloc[prev_index] + cdf['Value'].iloc[prev_index]
                first = cdf['Trading'].iloc[0] + cdf['Value'].iloc[0]
            elif 'Trading' in cdf.columns:
                cdf[['Trading']] = cdf[['Trading']].fillna(0)
                last = cdf['Trading'].iloc[-1]
                previous = cdf['Trading'].iloc[prev_index]
                first = cdf['Trading'].iloc[0]
            elif 'Value' in cdf.columns:
                cdf[['Value']] = cdf[['Value']].fillna(0)
                last = cdf['Value'].iloc[-1]
                previous = cdf['Value'].iloc[prev_index]
                first = cdf['Value'].iloc[0]
            percent = (last - previous) / last * 100 if last != 0 else 100

        return {'date': run_date, 'value': last, 'first': first, 'change': last - previous, 'percent': percent}

    def container_summary_by_date(self, ldf: Union [DataFrame, None] = None, this_date: Union[date, None] = None):
        """
        for the given date (default today),  and using the provided DataFrame,  return a dictionary with:
        'investment_value', 'cash_value', 'funding_value', 'investment_change',  'run_date'
        Dict:
        start_value (Value on first day of range)
        end_value (Value on last day of range)
        change_percent (Percent change between dates)
        dividends (totals all time)
        """
        ldf = ldf if isinstance(ldf, DataFrame) else self.df
        if not ldf.empty:
            daily_df = WealthDF(self.user, scope='day').df

            if 'AccountID' in ldf.columns:  # limit daily results to records in input local df
                daily_df = daily_df[daily_df['AccountID'].isin(ldf['AccountID'].unique())]
            if 'Symbol' in ldf.columns:  # limit daily results to records in input local df
                daily_df = daily_df[daily_df['Symbol'].isin(ldf['Symbol'].unique())]

            # To facilitate a specif data query,  trim based on input date
            if this_date:
                ldf = ldf.loc[ldf['Date'] <= Timestamp(this_date)]

            daily = self._container_change(daily_df)
            range = self._container_change(ldf)
            cash = ldf.loc[(ldf['Date'] == ldf['Date'].max()) & (ldf['InvType'] == 'Cash')].agg({'InvValue': 'sum'}).item()
            funding = ldf.loc[(ldf['Date'] == ldf['Date'].max()) & (ldf['InvType'] == 'Funding')].agg({'InvValue': 'sum'}).item()
            range_change = range['value'] - range['first']
            range_percent = range_change / range['value'] * 100 if range['value'] != 0 else 100

            return {'value': daily['value'], 'change': daily['change'], 'cash': cash, 'funding': funding, 'percent': daily['percent'],
                    'run_date': daily['date'], 'range_start': range['first'], 'range_change': range_change, 'range_percent': range_percent}

        return {'value': 0, 'change': 0, 'cash': 0, 'funding': 0, 'percent': 0,
                'run_date': Timestamp('today').date(), 'range_start': 0, 'range_change': 0, 'range_percent': 0}

    def investment_summary_by_date_df(self, ldf: DataFrame, this_date: date = IOOMDates(build=False).day_end) -> DataFrame:
        """
        for the given date (default today),  and using the provided DataFrame,  return a dataframe with:
        the following columns:
            ['Date', 'AccountID', 'Symbol', 'Quantity', 'AvgPrice', 'CurrPrice', 'Value', 'Cost']
        sort most Valuable to least
        """

        if self.scope == 'day':
            this_date = IOOMDates.align_day(this_date, keep_month=False)
        else:
            this_date = this_date.replace(day=1)
        if not ldf.empty:
            ldf = ldf.loc[((ldf['InvType'] == 'Trading') | (ldf['InvType'] == 'Value')) & (ldf['Date'] == Timestamp(this_date)) & (ldf['Quantity'] != 0)]
            ldf = ldf.groupby(['Date', 'AccountID', 'Symbol']).agg({'Quantity': 'sum', 'Price': 'max', 'Value': 'max', 'InvValue': 'sum'}).reset_index().sort_values(
            ['Date', 'AccountID', 'InvValue'], ascending=[True, True, False])
            ldf['Cost'] = ldf['Price'] * ldf['Quantity']
            ldf.rename(columns={'Price': 'AvgPrice', 'Value': 'CurrPrice', 'InvValue': 'Value'}, inplace=True)
        else:
            ldf = pd.DataFrame(columns=['AvgPrice', 'CurrPrice', 'Value'])
        return ldf

    @staticmethod
    def force_columns(fdf: DataFrame):
        """
        Ensure we have the minimum status columns
        """
        for column in ['Trading', 'Value', 'Funding', 'Cost']:
            if column not in fdf.columns:
                fdf[column] = 0
                fdf[column + '_est'] = False
        return fdf

    def account_funding_dataframe(self, account_id: int):
        df = self.dates
        funding = DataFrame(Funding.objects.filter(account_id=account_id).values('date', 'value', 'id', 'note'))
        funding['Date'] = pd.to_datetime(funding['date'])
        funding.rename(columns={'id': 'funding_id', 'note': 'funding_note'}, inplace=True)
        cash = DataFrame(CashFlow.objects.filter(account_id=account_id).values('date', 'value', 'id', 'note'))
        cash['Date'] = pd.to_datetime(funding['date'])
        cash.rename(columns={'id': 'cash_id', 'note': 'cash_note'}, inplace=True)

        if self.scope == 'month':
            funding['Date'] = funding['Date'].dt.to_period('M').dt.to_timestamp()
            cash['Date'] = cash['Date'].dt.to_period('M').dt.to_timestamp()



        balance_df = self.df.loc[(self.df['AccountID'] == account_id) & (self.df['InvType'] == 'Cash')]

    def container_summary_values(self, ldf: DataFrame, run_date: Timestamp, is_portfolio=False) -> dict:
        """
        Return the summary dictionary based on the run_date with a value for:
        Value, Cash, EffectiveCost, TotalDividends, ID, Type, Name
        """
        if 'AccountName' not in ldf.columns:
            ldf = self.set_names(ldf)
        ldf = ldf.loc[ldf['Date'] == run_date]

        results = {'Value': ldf.loc[(ldf['InvType'] == 'Trading') | (ldf['InvType'] == 'Value')].agg({'InvValue': 'sum'}).item(),
                   'Cash': ldf.loc[ldf['InvType'] == 'Cash'].agg({'InvValue': 'sum'}).item(),
                   'EffectiveCost': ldf.loc[ldf['InvType'] == 'Funding'].agg({'InvValue': 'sum'}).item(),
                   'TotalDividends': ldf.loc[ldf['InvType'] == 'Trading'].agg({'DivAmount': 'sum'}).item(),
                   }
        if is_portfolio:
            results['Id'] = int(ldf['PortfolioID'].max())
            results['Type'] = 'Portfolio'
            results['Name'] = ldf['PortfolioName'].max()
        else:
            results['Id'] = int(ldf['AccountID'].max())  # todo: should find a better way then max to select ANY value - 20.3 us (micro seconds)
            results['Type'] = 'Account'
            results['Name'] = ldf['AccountName'].max()
        return results

    def summary_list_by_date(self, df: DataFrame, this_date: date = IOOMDates(build=False).day_end) -> list:
        """
        provide a list of Portfolio/Account summaries
        If the df contains only one (or no) Portfolios,  Accounts are listed
        """
        if df.empty:
            return []

        if self.scope == 'month':
            this_date = this_date.replace(day=1)
        this_date = Timestamp(this_date)

        df = self.set_names(df)

        results = []
        if len(df['PortfolioID'].unique()) > 1:
            for p in df['PortfolioID'].unique():
                if p != 0:  # 0 Is used to indicate a non-portfolio
                    results.append(self.container_summary_values(df.loc[df['PortfolioID'] == p], run_date=this_date, is_portfolio=True))

            df = df.loc[df['PortfolioID'] == 0]

        for a in df['AccountID'].unique():
            results.append(self.container_summary_values(df.loc[df['AccountID'] == a], run_date=this_date, is_portfolio=False))
        return results

    def today_summary(self, parsed_df: Union[DataFrame, None] = None):
        """
        based on last run_date,  and filtered by the AccountID and Symbols in parsed_df return the dictionary:
        return {'date': run_date, 'value': last, 'change': last - previous, 'percent': percent}
        """
        parsed_df = parsed_df if parsed_df else self.df
        daily_df = WealthDF(self.user, scope='day').df

        if 'AccountID' in parsed_df.columns:
            daily_df = daily_df[daily_df['AccountID'].isin(parsed_df['AccountID'].unique())]
        if 'Symbol' in parsed_df.columns:
            daily_df = daily_df[daily_df['Symbol'].isin(parsed_df['Symbol'].unique())]

        if daily_df.empty:
            run_date = Timestamp('today')
            last = previous = percent = 0
        else:
            daily_df = daily_df.groupby(['Date', 'InvType']).agg({'InvValue': 'sum'}).reset_index()
            daily_df = daily_df.pivot(index='Date', columns='InvType', values='InvValue').reset_index()
            daily_df.sort_values('Date', inplace=True)
            run_date = daily_df['Date'].iloc[-1]

            if 'Trading' in daily_df.columns and 'Value' in daily_df.columns:
                last = daily_df['Trading'].iloc[-1] + daily_df['Value'].iloc[-1]
                previous = daily_df['Trading'].iloc[-2] + daily_df['Value'].iloc[-2]
            elif 'Trading' in daily_df.columns:
                last = daily_df['Trading'].iloc[-1]
                previous = daily_df['Trading'].iloc[-2]
            elif 'Value' in daily_df.columns:
                last = daily_df['Value'].iloc[-1]
                previous = daily_df['Value'].iloc[-2]

            percent = (last - previous) / last * 100 if last != 0 else 100

        return {'date': run_date, 'value': last, 'change': last - previous, 'percent': percent}

    def update_cache(self, new_df: DataFrame):
        key = self.df_cache_key
        cache.delete(key)
        cache.set(key, new_df, timeout=CACHE_TTL)
