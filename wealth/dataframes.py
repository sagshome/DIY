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
from typing import Union, Dict, List

from itertools import groupby

from django.core.cache import cache
from django.contrib.auth.models import User

from django.db.models import QuerySet, OuterRef, Subquery
from django.db.models.functions import Trunc, TruncDay, TruncMonth
from django.db.models import F, Window, Q, Max
from django.db.models.functions import TruncMonth, RowNumber

from base.models import Inflation
from base.utils import df_start, to_utc_midnight
from base.ioom_dates import IOOMDates, IOOM_RANGES
from wealth.models import Account, CashFlow, Portfolio, Dividend, DividendAmount, Funding, Investment, Position, Value

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

        self._positions = Position.objects.filter(investment__in=self._investments, account__in=self._accounts)

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

    @staticmethod
    def coerce_positions_df(queryset: QuerySet, values: List) -> pd.DataFrame:
        extend_values = values.append('month')
        df = pd.DataFrame((
            queryset
                .annotate(month=TruncMonth("date"))
                .annotate(
                    row_number=Window(
                        expression=RowNumber(),
                        partition_by=[
                            F("month"),
                            F('account'),
                            F('investment')
                        ],
                        order_by=F("date").desc(),
                    )
                )
                .filter(row_number=1)
                .order_by("date")
            ).values(*values)
        )
        df["posDate"] = pd.to_datetime(df["date"])
        df["Date"] = pd.to_datetime(df["month"])
        return df

    @staticmethod
    def coerce_values_df(queryset: QuerySet, values: List) -> pd.DataFrame:
        extend_values = values.append('month')
        df = pd.DataFrame((
            queryset
                .annotate(month=TruncMonth("date"))
                .annotate(
                    row_number=Window(
                        expression=RowNumber(),
                        partition_by=[
                            F("month"),
                            F('investment')
                        ],
                        order_by=F("date").desc(),
                    )
                )
                .filter(row_number=1)
                .order_by("date")
            ).values(*values)
        )
        df["posDate"] = pd.to_datetime(df["date"])
        df["Date"] = pd.to_datetime(df["month"])
        return df

    @staticmethod
    def coerce_values_df2(queryset: QuerySet, values: List) -> pd.DataFrame:
        extend_values = values.append('month')
        df = pd.DataFrame((
            queryset
                .annotate(month=TruncMonth("date"))
                .values('investment', 'month')
                .annotate(last_date=Max('date'))
                .order_by('investment', 'month')
            ).values(*values)
        )
        return df

    @property
    def df(self) -> DataFrame:
        if self.dates.empty:
            logger.warning('No position data exists for user:%s, scope:%s' % (self.user, self.scope))
            return DataFrame()
        logger.debug("Get DF for user:%s scope:%s" % (self.user, self.scope))
        base_key = self.df_cache_key

        try:
            day_df = cache.get_or_set(
                f"{base_key}_day",
                lambda: self.build_dataframe(),
                timeout=CACHE_TTL,
            )

            month_df = cache.get_or_set(
                f"{base_key}_month",
                lambda: self.get_month_scoped_df(day_df),
                timeout=CACHE_TTL,
            )
            month_df["Date"] = month_df["Date"].values.astype("datetime64[M]")  # Normalize date to the 1st
            logger.debug("GOT DF for user:%s scope:%s" % (self.user, self.scope))

            if self.scope == 'day':
                return day_df
            else:
                return month_df

        except Exception as e:
            logger.error("Failed - dataframe user:%s Error:%s" % (self.user, e))


         
        return DataFrame()

    @staticmethod
    def get_month_scoped_df(df: DataFrame) -> DataFrame:
        '''
        Given a dataframe based on days,  return a version which is formatted to be month
        todo: maybe do a bit of checking ?
        '''
        return (
            df.groupby(
                ["AccountID", "Symbol", pd.Grouper(key="Date", freq="ME")]
            )
            .agg(
            {
                "Quantity": "last",
                "Price": "last",
                "Value": "last",
                "DivAmount": "sum",
                "InvValue": "last",
                "DivTotal": "last",
                "PortfolioID": "last",
                "ValueEstimated": "last",  # Avoid false positive if any day in the month was a bank holiday
                "QuantityEstimated": "last",  # Missing Data
                "InvType": "last",
                "EX_Div": "sum",
            }
        )
        .reset_index()
        )

    def build_dataframe(self) -> DataFrame:
        """
        This is the "blessed" (and tested) way to build a DataFrame for IOOM representation.
        scope - either day or month
        account: A set or not of all the accounts you want included (filters Positions)
        investment: A set or not of all the Investments you want included (filter Positions) - Special note Funding and Cash need to be excluded if not wanted
        include_dividends: bool - False,  included with each row any dividends that would be earned

        start is used to build a dates_df dataframe from the very first possible date.
        """
        logger.debug('Set DF for user:%s scope:%s' % (self.user, self.scope))

        df = self.build_positions_df_v3()
        logger.debug('positions DF for user:%s scope:%s' % (self.user, self.scope))

        df = self.add_values_df_v3(df)
        logger.debug('values DF for user:%s scope:%s' % (self.user, self.scope))

        div_df = self.build_dividends_df_v2(df)
        logger.debug('dividend DF for user:%s scope:%s' % (self.user, self.scope))

        result = df.merge(div_df[['Date', 'AccountID', 'Symbol', 'DivAmount']], on=['Date', 'AccountID', 'Symbol'], how='left')

        # Fix things up
        result['InvValue'] = result['Quantity'] * result['Value']
        result['DivAmount'] = result['DivAmount'].fillna(0)

        result.sort_values(["AccountID", "Symbol", "Date"], inplace=True)
        result["DivTotal"] = result.groupby(["AccountID", "Symbol"])["DivAmount"].cumsum()
        result.dropna(subset=["AccountID", "Symbol"], inplace=True)  # todo: is this even necessary

        result["Symbol"] = result["Symbol"].str.split("~").str[-1]  # Cleanup alias names - this is SLOW
        result.to_csv(f'debug_dump_{self.scope}_{self.user}.csv')  # todo: remove this
        logger.debug("Done Set DF for user:%s scope:%s" % (self.user, self.scope))
        return result


    def build_dividends_df_v2(self, positions_df: DataFrame) -> pd.DataFrame:

        """
        Build a dataframe based on Dividend data overlaid with TimeSeries data appropriate for the scope
        Columns for the dataframe are:
            columns = ['Date', 'Symbol', 'Value']
        Any DateTime without a Value will be set to 0
        audit: is used when building a DataFrame for the population of CashFlow records (see DividendAmount)
        """
        start = positions_df['Date'].min()
        columns = ['Datetime', 'Symbol', 'Dividend']

        div_df = pd.DataFrame(
            DividendAmount.objects.filter(
                cash_record__date__gte=start,
                cash_record__account__user=self.user,
            ).order_by('-cash_record__date', 'cash_record__account', 'dividend__investment__symbol').values(
                "dividend__date",
                "dividend__investment__symbol",
                "cash_record__account",
                "dividend__value",
                "cash_record__date",
                "altered",
                "cash_record__value",
                "cash_record__note",
            )
        )
        
        if div_df.empty:
            return pd.DataFrame(columns=columns)

        div_df.rename(columns={"cash_record__date": "Paid_Date", "dividend__date": "EX_Date", "dividend__value": "DivValue",
                           "cash_record__note": "Note", 'cash_record__value': 'DivAmount', 'dividend__investment__symbol': 'Symbol',
                               "cash_record__account": "AccountID"}, inplace=True)
        div_df['Date'] = pd.to_datetime(div_df['Paid_Date'])
        div_df["Date"] = div_df["Date"]+ pd.offsets.BDay(0)  # todo: Is this really necessary?
        div_df['DivAmount'] = div_df['DivAmount'].astype('float64')
        return div_df


    def build_positions_df_v3(self) -> DataFrame:
        """
        V3,  not currently used.   Avoid the HUGE dataframe for scope = day.   100 Invesments * 250 days * 20 years
        Trying to extract all and join via FFILL maybe instead I could pull the earlier and collect the last value per investment to the first row

        Build a dataframe based on Position data overlaid with TimeSeries data appropriate for the scope and subclass
        force_start will cause the dataframe to span to the first Position date (based on account and investment parameters)
        requires
        """
        db_columns = ['date', 'account_id', 'account__portfolio', 'investment_id', 'investment__inv_type', 'quantity', 'price']
        df_columns = ['Date', 'AccountID', 'PortfolioID', 'Symbol', 'Quantity', 'Price']

        df = DataFrame.from_records(list(self._positions.values(*db_columns)))
        if df.empty:
            logger.warning('No position data exists for user:%s' % (self.user))
            return DataFrame(columns=df_columns)

        master = IOOMDates(force=True, start=df['date'].min()).days_df

        df.rename(columns={"account_id": "AccountID", "account__portfolio": "PortfolioID", "investment_id": "Symbol",
                           "investment__inv_type": "InvType", "quantity": "Quantity", "price": "Price"}, inplace=True)
        df["Date"] = pd.to_datetime(df["date"])

        # from chatgpt
        results = []
        today = pd.Timestamp.today().normalize()
        for (inv, acct), group in df.groupby(["Symbol", "AccountID"]):
            start = group["Date"].min()
            end = group["Date"].max()
            end = end if group.loc[group['Date'] == end]['Quantity'].iloc[0] == 0 else today
            dates = master[(master["Date"] >= start) & (master["Date"] <= end)].copy()

            dates["Symbol"] = inv
            dates["AccountID"] = acct

            result = dates.merge(
                group, on=["Symbol", "AccountID", "Date"], how="left"
            )

            results.append(result)

        merged = pd.concat(results, ignore_index=True)
        merged.sort_values(['AccountID', 'Symbol', 'Date'], inplace=True)

        merged['InvType'] = merged.groupby(['AccountID', 'Symbol'])['InvType'].ffill()
        merged['PortfolioID'] = merged.groupby(['AccountID'])['PortfolioID'].ffill()
        # merged.dropna(subset=["InvType"], inplace=True)  # Not requred with incremental approach,  50.1 MB drops to 967 KB
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
        merged['QuantityEstimated'] = False
        merged.loc[merged['Quantity'].isna() == True, 'QuantityEstimated'] = True
        merged.loc[mask, 'Quantity'] = (
            merged.loc[mask]
            .groupby(['AccountID', 'Symbol'])['Quantity']
            .transform(lambda x: x.interpolate(method='linear'))
        )

        # What ever is left can be forward filled,  or set to 0
        merged[['Quantity', 'Price']] = merged[['Quantity', 'Price']].ffill().fillna(0)
        merged['PortfolioID'] = pd.to_numeric(merged['PortfolioID'], errors='coerce').fillna(0)  # Set to 0, accounts outside of portfolios can be filtered
        merged = merged.drop(columns=['date'])  # No longer required
        return merged


    def add_values_df_v3(self, df) -> DataFrame:
        """
        Build a dataframe based on Value data overlaid with TimeSeries data appropriate for the scope
        Columns for the dataframe are:
            columns = ['DateTime', 'Symbol', 'Value']
        Any DateTime without a Value will be set to 0

        """
        df_columns = ['Date', 'Symbol', 'Value', 'ValueEstimated', 'ExDividend']
        db_columns = ['date', 'investment', 'value', 'ex_dividend']


        results = []
        # today = pd.Timestamp.today().normalize()
        for inv, group in df.loc[df['InvType'] == 'Trading'].groupby("Symbol"):
            start = group["Date"].min()
            # todo: Why did I take out end ?  Because I would merge in symbol multiple times
            # end = group["Date"].max()
            # end = end if group.loc[group['Date'] == end]['Quantity'].iloc[0] == 0 else today
            results.append(DataFrame.from_records(
                    list(
                        Value.objects.filter(investment__symbol=inv, date__gte=start).
                        values(*db_columns))))
        if not results:
            return DataFrame(columns=df_columns)

        values_df = pd.concat(results)
        values_df['Date'] = pd.to_datetime(values_df['date'])
        values_df.rename(columns={"investment": "Symbol", "value": "Value", 'ex_dividend': 'EX_Div'}, inplace=True)
        values_df['Value'] = values_df['Value'].astype("float64")
        values_df.drop(columns=['date'], inplace=True)

        df = df.merge(values_df, on=['Date', 'Symbol'], how='left')  # todo: what about inner ?
        df.loc[~df['InvType'].eq('Trading'), 'Value'] = 1  # Set fake investment values

        df['ValueEstimated'] = False
        df.loc[df['Value'].isna() == True, 'ValueEstimated'] = True
        df['Value'] = df.groupby(['AccountID', 'Symbol'])['Value'].transform(
            lambda s: s.interpolate().ffill()
        )
        df["EX_Div"] = df["EX_Div"].astype("float64").fillna(0)
        return df


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

    @classmethod
    def container_values_by_date_df(cls, idf):
        """
        Return a dataframe, that has the ordered list of summary values (Cash, Funding, Trading, Value) ordered by
        Date (newest to oldest), with ESTimated values
        """
        data_columns = set(['Funding', 'Value', 'Cash', 'Trading'])
        if not idf.empty:
            ldf = idf.groupby(['Date', 'InvType']).agg({'InvValue': 'sum', 'ValueEstimated': 'last', 'QuantityEstimated': 'any'}).reset_index()
            g1 = ldf.pivot(index='Date', columns='InvType', values='InvValue').reset_index()
            for missing in data_columns - set(g1.columns):
                g1[missing] = 0
            g1 = g1.fillna(0)  # todo:  How can we have NA values?
            g2 = ldf.groupby('Date').agg({'ValueEstimated': 'last', 'QuantityEstimated': 'last'})

            df = g1.merge(g2, on='Date', how='left')

            # Create the Totals
            # todo:  When calculating QuantityEstimated - be smarter - Funding is never estimated,  Value account'd
            # don't have cash so   ValueEstimated should be used unless it is cash where is CashEstimated
            df['Total'] = df['Trading'] + df['Value']
            df['TotalEstimated'] = df['ValueEstimated'] | df['QuantityEstimated']
            df.sort_values('Date', ascending=False, inplace=True)

        return df

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

    def container_summary_values(self, idf: DataFrame, run_date: Timestamp, is_portfolio=False) -> dict:
        """
        Return the summary dictionary based on the run_date with a value for:
        Value, Cash, EffectiveCost, TotalDividends, ID, Type, Name
        """
        if 'AccountName' not in idf.columns:
            idf = self.set_names(idf)  # Set AccountName and PortfolioName columns
        ldf = idf.loc[idf['Date'] == run_date]

        results = {'Value': ldf.loc[(ldf['InvType'] == 'Trading') | (ldf['InvType'] == 'Value')].agg({'InvValue': 'sum'}).item(),
                   'Cash': ldf.loc[ldf['InvType'] == 'Cash'].agg({'InvValue': 'sum'}).item(),
                   'EffectiveCost': ldf.loc[ldf['InvType'] == 'Funding'].agg({'InvValue': 'sum'}).item(),
                   'TotalDividends': ldf.loc[ldf['InvType'] == 'Trading'].agg({'DivTotal': 'sum'}).item(),
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

        df = self.set_names(df)  # Add column Account

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

    @staticmethod
    def dated_summary_df(df: DataFrame) -> DataFrame:
        """
        Prepare a DataFrame what will have the following Columns:
            Date Cash Funding Trading Value TotalValue
        Input DataFrame must have
            Date InvValue InvType
        """
        output_columns = ['Date', 'Cash', 'Funding', 'Trading', 'Value', 'TotalValue']
        input_columns = ['Date', 'InvType', 'InvValue']
        if df.empty or not set(input_columns) & set(df.columns) == set(input_columns):
            logger.error('Invalid dataframe supplied - %s' % df.columns)
            return DataFrame(columns=output_columns)

        ldf = df.groupby(["Date", "InvType"]).agg({"InvValue": "sum"}).reset_index()
        ldf = ldf.pivot(index='Date', columns='InvType', values='InvValue').reset_index()
        ldf['Trading'] = ldf['Trading'].fillna(0)
        ldf['Value'] = ldf['Value'].fillna(0)
        ldf['TotalValue'] = ldf['Value'] + ldf['Trading']

        return ldf
