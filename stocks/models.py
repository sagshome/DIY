"""
The models here,  are used to build a monthly snapshot of financial data.   To normalize data,  the last trading
day of the month is normalized to the first date of the month.
"""
"""
Equity should be renamed to Fund,  so we have Fund.Equity, Fund.Value, Fund.Cash
Equity Types: Equity, Cash, Value
Account Types: Investment, Cash, Value
Investment accounts can hold any number of Equity.equitys
Cash accounts hold one equity.cash equity
Value accounts hold on equity.value equity

Accounts (and Portfolios) have 'Funds' and 'Gains'
   Funds come from 'Deposit' actions making Fund records
   Gains come from 'Transfer In' actions making TransIn records
   
   Withdraw actions
       Remove Funds first then Gains
       
   Transfer To activities can be generated as Transactions or Closing of account
   When Transfer to of Stocks
        current value = x
        avg cost value = y
        1. Generate a Sell XA (at current value)  - Increases Cash by X
        2. Reduce Funds (and/or Gains) by the current value      
        3. Generate Funding (and/or Transfer in) of months market value
        4. Generate a Buy XA (at current value)


For Equity.Equity:
   Fund / Redeem Transaction are rolled up to EPD to calculate Funds, Redeemed, Effective (Funds - Redeemed)  Cost
   Buy / Sell create Transactions that allow us to rollup value based on shares * price at a date
For Equity.Value
    Fund / Redeem Transaction are rolled up to EPD to calculate Funds, Redeemed, Effective (Funds - Redeemed)  Cost
    Buy / Sell create FundValue Records the are rolled up like transactions,  share count is always 1,  price is 0
    Value Transaction create FundValue records to account for growth  / loss
For Equity.Cash
    Fund / Redeem are the only Transactions - The are derived from Balance transaction and we estimate months with wholes
    Value Transaction create FundValue records to account for growth  / loss - but they should match Fund/Redeem
   
"""
# todo:  what should I do when someone trys to buy something via import or manual and they do not have the cash
#  1. Warning them and silently give them the cash ?  If they fix it up by doing a proper transaction,  how do I clear
#     old one.

import logging
import pandas as pd
import numpy as np
import yfinance as yf

from dateutil.relativedelta import relativedelta
from decimal import Decimal
from enum import Enum
from typing import List, Dict
from datetime import datetime, date
from time import sleep
from pandas import DataFrame

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import QuerySet, Sum, Avg, Q, F
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear

from django.urls import reverse

from base.models import API, DIY_EPOCH
from base.utils import BoolReason,  normalize_date, normalize_today, next_date, cache_dataframe, clear_cached_dataframe,  get_cached_dataframe, clear_simple_cache, get_simple_cache, set_simple_cache

logger = logging.getLogger(__name__)

AV_API_KEY = settings.ALPHAVANTAGEAPI_KEY


class DataSource(Enum):
    ADMIN = 10  # !
    ADJUSTED = 20 # F
    API = 30  # A
    RECONCILED = 35
    UPLOAD = 40  # U
    USER = 50  # M
    ESTIMATE = 60  # E

    @classmethod
    def choices(cls):
        return tuple((i.value, i.name) for i in cls)

    @classmethod
    def source_key(cls, value):
        if value == cls.ADMIN.value:
            return '!'
        if value == cls.ADJUSTED.value:
            return 'F'
        if value == cls.API.value:
            return 'A'
        if value == cls.UPLOAD.value:
            return 'U'
        if value == cls.USER.value:
            return 'M'
        if value == cls.ESTIMATE.value:
            return 'E'
        if value == cls.RECONCILED.value:
            return 'R'

        return '.'


CURRENCIES = (
    ('CAD', 'Canadian Dollar'),
    ('USD', 'US Dollar')
)

EPOCH = DIY_EPOCH

AV_REGIONS = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
'''

# my_currency = 'CAD'  # todo: Should be set via a user profile
EQUITY_COL = ['Date',
              'Equity',  # One record for each date we held the equity  todo: stop making records when equity is sold out
              'Object_ID',
              'Object_Type',
              'Shares',  # The number of shares we hold on this date.  It can not be less than 1 (should be 0 but float value screw that up)
              'Cost',  # We paid for the shares, less what we got back
              'Price',  # The price on that date
              'Dividends',  # Cash dividends recorded in the ledgers for managed equities
              'TotalDividends',  # A running accumulation for Dividends
              'Value',  # The value on that date
              'TBuy',  # The total of all spends, including REDIVS,  not used in equities but used in rollups for accounts and profiles
              'TSell',  # The total of all sells, not used in equities but used in rollups for accounts and profiles
              'RelGain',  # This is the money extracted via sales and dividends on non managed accounts
              'UnRelGain',  # The value of Value - TBuy + TSell
              'RelGainPct',  # RelGain * 100 / Tbuy = Tsell
              'UnRelGainPct',  # Value
              'AvgCost'  # Monthly tracking of Average cost per share
              ]
# todo:  How do I do shares/Cost/Price for things that are transferred in/out.

#ACCOUNT_COL = ['Date', 'Funds', 'Withdraws', 'Cash', 'Effective']  # From Equities -> 'TotalDividends',  'Value',  Calculated: 'EffectiveCost',  ]
ACCOUNT_COL = ['Date', 'Funds', 'Redeemed', 'TransIn', 'TransOut', 'NewCash', 'Cash', 'Effective']  # From Equities -> 'TotalDividends',  'Value',  Calculated: 'EffectiveCost',  ]


def currency_factor(exchange_date: date, input_currency: str, my_currency: str) -> float:
    """
    :param exchange_date:
    :param input_currency:
    :return:
    """
    # todo:  why do I have the twice
    if input_currency and my_currency:
        if not input_currency == my_currency:
            if input_currency == 'USD':
                return ExchangeRate.us_to_can_rate(exchange_date)
            elif input_currency == 'CAD':
                return ExchangeRate.can_to_us_rate(exchange_date)
            else:
                raise Exception(f'Unexpected input_currency {input_currency}')
    return 1


class ExchangeRate(models.Model):
    """
        Store both the US to CAN and the CAN to US conversion rates for each month.   Always use the last
        value for the month.
    """

    date: date = models.DateField()
    us_to_can: float = models.FloatField()
    can_to_us: float = models.FloatField()
    source: int = models.PositiveIntegerField(choices=DataSource.choices(), default=DataSource.ESTIMATE.value)

    # Class variables - a simple cache
    US_TO_CAN: Dict[datetime.date, float] = {}
    CAN_TO_US: Dict[datetime.date, float] = {}

    def __str__(self):  # pragma: no cover
        return f'{self.date}({DataSource(self.source).name}) US:{self.us_to_can} CAN:{self.can_to_us}'

    @classmethod
    def us_to_can_rate(cls, target_date) -> float:
        if len(cls.US_TO_CAN) == 0:
            logger.debug('Fetching exchange rates for us_to_can')
            cls.US_TO_CAN = dict(ExchangeRate.objects.all().values_list('date', 'us_to_can'))
        try:
            return cls.US_TO_CAN[target_date]
        except KeyError:
            cls.US_TO_CAN[target_date] = 1
            return 1

    @classmethod
    def can_to_us_rate(cls, target_date) -> float:
        if len(cls.CAN_TO_US) == 0:
            logger.debug('Fetching exchange rates for us_to_can')
            cls.CAN_TO_US = dict(ExchangeRate.objects.all().values_list('date', 'can_to_us'))
        try:
            return cls.CAN_TO_US[target_date]
        except KeyError:
            # logger.debug('CAN_TO_US - KeyError on date:%s' % target_date)
            cls.CAN_TO_US[target_date] = 1
            return 1

    @classmethod
    def _reset(cls):
        cls.CAN_TO_US = {}
        cls.US_TO_CAN = {}

    @classmethod
    def create_or_update(cls, **kwargs):
        """
        update if source is more specific
        :param kwargs:
        :return:
        """
        logger.debug('Going after %s' % kwargs['date'])
        try:
            obj = cls.objects.get(date=kwargs['date'])
            if 'source' in kwargs and obj.source > kwargs['source']:
                logger.debug('Going to update the DB')
                obj.source = kwargs['source']
                obj.can_to_us = kwargs['can_to_us']
                obj.us_to_can = kwargs['us_to_can']
                obj.save()
            else:
                changed = False
                if not obj.can_to_us == kwargs['can_to_us']:
                    obj.can_to_us = kwargs['can_to_us']
                    changed = True
                if not obj.us_to_can == kwargs['us_to_can']:
                    obj.us_to_can = kwargs['us_to_can']
                    changed = True
                if changed:
                    logger.debug('I updated the DB')
                    obj.save()
        except cls.DoesNotExist:
            logger.debug('I created a record')
            cls.objects.create(**kwargs)

    @classmethod
    def update(cls):
        """
        Update Exchange Rates,   since this is daily,  I will take the first rate of the month as the normalized
        value for the last month
        """
        first_str = EPOCH.strftime('%Y-%m-%d')
        result = API.get('BOC', f'FXUSDCAD,FXCADUSD/json?start_date={first_str}&order_dir=desc')

        if not result.status_code == 200:  # pragma: no cover
            logger.error('BOC: failure: %s - %s' % (result.status_code, result.reason))
            return

        data = result.json()
        months = {}

        for record in range(len(data['observations'])):
            this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
            record_date = datetime(this_date.year, this_date.month, 1).date()
            if record_date not in months:  # This will be the last day of the month so use it.
                can_rate = data['observations'][record]['FXCADUSD']['v']
                us_rate = data['observations'][record]['FXUSDCAD']['v']
                ExchangeRate.create_or_update(date=record_date, can_to_us=can_rate, us_to_can=us_rate,
                                              source=DataSource.API.value)
                months[record_date] = this_date

        ExchangeRate._reset()  # Clear any cached values


class Inflation(models.Model):
    """
    Class to capture a months worth of inflation
    """

    date = models.DateField()
    cost = models.FloatField()
    inflation = models.FloatField()
    source: int = models.PositiveIntegerField(choices=DataSource.choices(), default=DataSource.ESTIMATE.value)

    def __str__(self):
        return f'{self.date}({DataSource(self.source).name}) {self.inflation}'

    @classmethod
    def get_or_create(cls, **kwargs):
        """
        update if source is more specific
        :param kwargs:
        :return:
        """
        created = False
        try:
            obj = cls.objects.get(date=kwargs['date'])
            if 'source' in kwargs and obj.source > kwargs['source']:
                obj.source = kwargs['source']
                obj.cost = kwargs['cost']
                obj.inflation = kwargs['inflation'] if 'inflation' in kwargs else 0
                obj.save()
        except cls.DoesNotExist:
            obj = cls.objects.create(**kwargs)
            created = True
        return obj, created

    @classmethod
    def update(cls, force: bool = False):
        """
        Update Inflation values
        Since the current month is not in the value we need to add it at the end
        """
        first = EPOCH
        first_str = first.strftime('%Y-%m-%d')

        result = API.get('BOC', f'STATIC_INFLATIONCALC/json?start_date={first_str}')
        if not result.status_code == 200:
            logger.error('BOC failure: %s - %s' % (result.status_code, result.reason))
        else:
            # Pass 1 - Get all the inflation CPI values
            data = result.json()
            this_inflation = 0
            last_cost = None
            for record in range(len(data['observations'])):
                this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
                this_cost = float(data['observations'][record]['STATIC_INFLATIONCALC']['v'])
                if last_cost:
                    this_inflation = ((this_cost - last_cost) * 100) / last_cost

                Inflation.get_or_create(date=this_date, cost=this_cost, inflation=this_inflation, source=DataSource.API.value)
                last_cost = this_cost

            Inflation.get_or_create(date=normalize_today(), cost=this_cost, inflation=0, source=DataSource.ESTIMATE.value)
            clear_simple_cache('ioom_inflation')

    @classmethod
    def inflated(cls, value: float, from_date: date, to_date: date) -> float:
        """
        calculate the cost based on inflation of value,  between date and date,
        """
        all_values = get_simple_cache('ioom_inflation')
        if all_values == None:
            all_values = dict(Inflation.objects.all().values_list('date', 'cost'))
            set_simple_cache('ioom_inflation', all_values)

        to_value = all_values[to_date] if to_date in all_values else 0
        from_value = all_values[from_date] if from_date in all_values else 0
        if to_value == 0 or from_value == 0:
            return value
        result = value + value * (to_value - from_value) / from_value
        return result


class Equity(models.Model):

    EQUITY_TYPES = (('Equity', 'Equity/ETF'),
                    ('Cash', 'Bank Accounts'),
                    ('Value', 'Value Account'))
    REGIONS = (('Canada', 'Canada'),
               ('US', 'US'))

    # API sources
    ypfinance = 1
    alphavantage = 2
    no_api = 99

    @classmethod
    def region_lookup(cls):
        result = {}
        for region in cls.REGIONS:
            result[region[0]] = region[1]
        return result

    # Symbol is 'acct_id:<str>' for Cash and Value types
    symbol: str = models.CharField(max_length=32, verbose_name='Trading symbol')  # Symbol
    region: str = models.CharField(max_length=10, null=False, blank=False, default='Canada')

    name: str = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    equity_type: str = models.CharField(max_length=10, blank=True, null=True, choices=EQUITY_TYPES, default='Equity')
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='CAD')
    last_updated: date = models.DateField(blank=True, null=True)
    deactived_date: date = models.DateField(blank=True, null=True)
    searchable: bool = models.BooleanField(default=False)  # Set to False, when this is data that was forced into being
    validated: bool = models.BooleanField(default=False)  # Set to True was validation is done

    class Meta:
        unique_together = ('symbol', 'region')

    @property
    def key(self):
        key = self.symbol
        if self.equity_type == 'Cash':
            key = f'Cash-Account:{self.id}'
        elif self.equity_type == 'Value':
            key = f'Value-Account:{self.id}'
        return key  # US does not get a region decorator via APIs

    def __str__(self):
        if self.equity_type == 'Value' or self.equity_type == 'Cash':
            account_key = self.symbol.split('-')[1]
            account_key = account_key.split(':')[0]
            try:
                account_id = int(account_key)
                try:
                    return Account.objects.get(id=account_id).name
                except Account.DoesNotExist:
                    pass  # Just use the default string
            except ValueError:
                pass # Just use the default string
        return f'{self.symbol} ({self.region}) - {self.name}'

    def save(self, *args, **kwargs):
        if 'update' in kwargs:
            do_update = kwargs.pop('update')
        else:
            do_update = False

        if self.equity_type == 'Equity':
            if not self.symbol.isupper():
                self.symbol = self.symbol.upper()

            if not self.validated and do_update:
                self.set_equity_data()
        else:
            self.symbol = self.symbol[:31]

        super(Equity, self).save(*args, **kwargs)
        if self.searchable and do_update:
            self.update_external_equity_data()

    def av_set_data(self):
        request = API.get('AVURL', f'SYMBOL_SEARCH&keywords={self.key}&apikey={AV_API_KEY}')
        if request.status_code == 200:
            self.validated = True
            data = request.json()
            if 'bestMatches' in data and len(data['bestMatches']) > 0 and data['bestMatches'][0]['9. matchScore'] == '1.0000':
                self.name = data['bestMatches'][0]['2. name']
                for region in self.REGIONS:
                    if data['bestMatches'][0]['4. region'] == region[1]:
                        self.region = region[0]
                        break
                self.currency = data['bestMatches'][0]['8. currency']
                return True

    def yp_set_data(self):
        try:
            data = yf.Ticker(self.key).info
        except AttributeError:  # Call to yf failed
            return False
        try:
            self.region = data['country'] if 'country' in data else data['region']  # What do you expect with free data
            self.currency = data['currency']
            self.name = data['shortName']
        except KeyError:
            logger.error('Lookup via YF failed on %s' % self.key)
            return False
        return True

    def set_equity_data(self):
        set_data = self.yp_set_data()
        if not set_data:
            set_data = self.av_set_data()
        if not set_data:
            self.searchable = False
        else:
            self.searchable = True
        self.validated = True

    def fill_equity_value_holes(self):
        """
        Look for months without an equity value,  and calculated a value based on direct rate of change.
        It is possible that values will need to be re-filled as data is populated via new transactions / sources
        """
        estimated = DataSource.ESTIMATE.value

        if self.equity_type == 'Equity':
            all_dates: Dict[date, float] = dict(EquityValue.objects.filter(equity=self).values_list('date', 'price'))
            valid_dates: Dict[date, float] = dict(EquityValue.objects.filter(equity=self).exclude(source=estimated).values_list('date', 'price'))
        else:
            all_dates: Dict[date, float] = dict(FundValue.objects.filter(fund=self).values_list('date', 'value'))
            valid_dates: Dict[date, float] = dict(FundValue.objects.filter(fund=self).exclude(source=estimated).values_list('date', 'value'))

        last_date: date = None
        last_price: float = 0  # just to stop the warnings,  it can't actually be used before its referenced
        for this_date in sorted(valid_dates.keys()):
            if last_date and not this_date == next_date(last_date):  # We have a hole
                months = (this_date.year - last_date.year) * 12 + this_date.month - last_date.month  # How many
                change_increment = (valid_dates[this_date] - last_price) / months
                for _ in range(months - 1):  # Fill holes up to this_date
                    next_month = next_date(last_date)
                    last_price = last_price + change_increment
                    if next_month not in all_dates:
                        if self.equity_type == 'Equity':
                            EquityValue.objects.create(equity=self, real_date=next_month, date=next_month, price=last_price, source=estimated)
                        else:
                            FundValue.objects.create(fund=self, real_date=next_month, date=next_month, value=last_price, source=estimated)
                    else:  # We may have estimated this before
                        if all_dates[next_month] != last_price:
                            if self.equity_type == 'Equity':
                                e = EquityValue.objects.get(equity=self, date=next_month)
                                e.price = last_price
                                e.save()
                            else:
                                e = FundValue.objects.get(fund=self, date=next_month)
                                e.value = last_price
                                e.save()
                    last_date = next_month

            last_date = this_date
            last_price = valid_dates[this_date]

        try:
            if self.equity_type == 'Equity':
                last_entry = EquityValue.objects.filter(equity=self).latest('date')
            else:
                last_entry = FundValue.objects.filter(fund=self).latest('date')
            current_date = normalize_today()
            date_value = next_date(last_entry.date)
            if date_value <= current_date:
                price_value = last_entry.price if self.equity_type == 'Equity' else last_entry.value
                while date_value <= current_date:
                    logger.debug('Adding %s on date %s' % (self, date_value))
                    if self.equity_type == 'Equity':
                        EquityValue.objects.create(equity=self, real_date=date_value, date=date_value, price=price_value, source=DataSource.ESTIMATE.value)
                    else:
                        FundValue.objects.create(fund=self, real_date=date_value, date=date_value, value=price_value, source=DataSource.ESTIMATE.value)
                    date_value = next_date(date_value)
        except IndexError:
            logger.error('No EquityValue data for:%s' % self)
        except FundValue.DoesNotExist:
            logger.error('No Fund data for %s' % self)
        except EquityValue.DoesNotExist:
            logger.error('No Equity value data for %s' % self)

    def get_dividend_dates(self) -> dict[date: date]:
        if API.status('ypfinance'):
            if self.equity_type == 'Equity':
                series = yf.Ticker(self.key).get_dividends()
                if isinstance(series, pd.Series) and not series.empty:
                    return {normalize_date(dt.date()): dt.date() for dt in series.to_dict().keys()}
        return {}

    def yp_update(self, period='1y') -> Dict[date, List]:
        """
        Build a dictionary key on Date with two values [close price,  dividends per share]
        kwargs
            period: str default = "1y",   How many months of data to retrieve
        """
        result ={}
        if API.status('ypfinance'):  # Currently set manually in admin tool
            if self.equity_type == 'Equity':
                df = yf.Ticker(self.key).history(interval='1mo', period=period, auto_adjust=False)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    data = df[['Close', 'Dividends']].to_records()
                    if len(data):
                        for record in data:
                            if len(record) == 3:
                                result[record[0].date()] = (float(record[1]), float(record[2]))
        else:
            logger.info('ypfinance API is down:%s' % API.status('ypfinance'))
        return result

    def av_update(self, key: str, force:bool = False) -> Dict[date, List]:
        """
        Build a dictionary key on Date with two values [close price,  dividends per share]
        args:
            0 - api key, used for alphavantage
        kwargs
            force: bool default = False,   setting to True will force an update even if this equity was already updated today

        """
        results = {}
        if key and self.equity_type == 'Equity' and self.searchable:
            now = datetime.now().date()
            if now == self.last_updated and not force:
                logger.info('%s - Already updated %s' % (self, now))
                return results
            else:
                data_key = 'Monthly Adjusted Time Series'
                result = API.get('AVURL', f'TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.key}&apikey={key}')
                if not result.status_code == 200:
                    logger.warning('AVURL Result is %s - %s' % (result.status_code, result.reason))
                    return results
                data = result.json()
                if data_key in data:  # if not,  we timed out our API key
                    for entry in data[data_key]:
                        try:
                            date_value = datetime.strptime(entry, '%Y-%m-%d').date()
                        except ValueError:
                            logger.error('Invalid date format in: %s' % entry)
                            return results
                        if date_value >= EPOCH:
                            price = float(data[data_key][entry]['4. close'])
                            dividend = float(data[data_key][entry]['7. dividend amount'])
                            results[date_value] = (price, dividend)
                else:
                    if 'Information' in data and data['Information'].startswith('Thank you for using'):
                        logger.warning("Too many calls to AVURL")
                        API.pause("AVURL")
                    else:
                        logger.warning('Invalid Response: %s' % data)
        return results

    def update_external_equity_data(self, force: bool = False, key: str = None, daily: bool = False):
        """
        Go to either Yahoo Finance or www.alphavantage to update equity and dividend data.

        kwargs:
           force: boolean default False, When True,  20 years of Yahoo Finance data is retrieved,
                                         When True will also use alphavantage data even if we already update today.
           key:  str default None, The API key for alphavantage if it is not provided then we will never try alphavantage
           daily:  boolean default False,  When True will set the last update value (used to limit alphavantage API calls)

        side effect:
            All records (EquityValue and EquityEvent (Dividend) records not source by an API or lower, are deleted

        safety check:
            if not an equity,  or not searchable nothing is done
        """

        if self.equity_type != 'Equity' or not self.searchable:
            logger.debug('Safety Valve: Can not update non "Equity" equities or not searchable values')
            return

        # Since this is searchable,  get rid of any data populated by means lesser than an API
        EquityEvent.objects.filter(equity=self, event_type='Dividend', source__gt=DataSource.API.value).delete()
        EquityValue.objects.filter(equity=self, source__gt=DataSource.API.value).delete()

        if force:
            period = '20y'
        else:
            period = '1y'

        results_api = self.ypfinance
        results = self.yp_update(period=period)
        if not results and key:
            results_api = self.alphavantage
            results = self.av_update(key, force=force)

        if results:
            existing_price = {e['date']: e for e in EquityValue.objects.filter(equity=self).values('date', 'price', 'api', 'split_fixed')}
            existing_dividends = {e['date']: e for e in EquityEvent.objects.filter(equity=self, event_type='Dividend').values('date', 'real_date', 'value', 'api', 'split_fixed')}
            dividend_dates = self.get_dividend_dates()
            for result_key in results:
                if result_key in existing_price:
                    #  has not been 'fixed' and used api is better or equal to existing api AND existing price != new API price
                    if not existing_price[result_key]['split_fixed'] and results_api <= existing_price[result_key]['api'] and results[result_key][0] != existing_price[result_key]['price']:
                        EquityValue.objects.filter(date=result_key, equity=self).update(price=results[result_key][0], api=results_api)
                else:
                    EquityValue.objects.create(date=result_key, equity=self, real_date=result_key,
                                               source=DataSource.API.value, api=results_api, price=results[result_key][0])

                if result_key in existing_dividends:
                    real_date = dividend_dates[result_key] if result_key in dividend_dates else existing_dividends[result_key]['real_date']  # If our search for a real_date worked,  use it else keep the same
                    if not existing_dividends[result_key]['split_fixed'] and results_api <= existing_dividends[result_key]['api'] and results[result_key][1] != existing_dividends[result_key]['value']:
                        EquityEvent.objects.filter(date=result_key, equity=self, event_type='Dividend').update(value=results[result_key][1], real_date=real_date, api=results_api)
                    elif real_date != existing_dividends[result_key]['real_date']:
                        EquityEvent.objects.filter(date=result_key, equity=self, event_type='Dividend').update(real_date=real_date)
                else:  # This is a new record
                    if results[result_key][1] != 0:  # if we got a useful dividend - aka not 0
                        real_date = dividend_dates[result_key] if result_key in dividend_dates else result_key  # If our search for a real_date worked, use it else use the normalized date
                        EquityEvent.objects.create(date=result_key, equity=self, event_type='Dividend', api=results_api,
                                                   real_date=real_date, source=DataSource.API.value, value=results[result_key][1])
            if daily:
                self.last_updated = datetime.now().date()
                self.save()

    def update(self, force: bool = False, key: str = None, daily=True):
        """
        Update the stocks closing price for the last day of the month (current day of current month)
        Update the dividend paid per share
        kwargs:
           force: boolean Default False - Add the force attribute.
                Force with alphavantage will try the update even if it is the same date as today
                Force with yfinance will try and take 20 years of data instead of 1 year.
           key: string Default None - the alphavantage API key
           daily: boolean Default True - Update the last update value on the equity

        The yfinance API is always tried first

        """
        logger.debug('Updating %s' % self)
        if self.equity_type == 'Equity':
            if not self.validated:
                self.set_equity_data()
                self.save()
            elif self.searchable:
                self.update_external_equity_data(force=force, key=key, daily=daily)
        self.fill_equity_value_holes()

    def event_dict(self, start_date: datetime.date = None, event: str = None) -> Dict[datetime.date, float]:
        queryset = EquityEvent.objects.filter(equity=self)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if event:
            queryset = queryset.filter(event_type=event)
        else:
            queryset = queryset.filter(event_type='Dividend')
        return dict(queryset.values_list('date', 'value'))

    def value_dict(self, start_date: datetime.date = None) -> Dict[datetime.date, float]:
        if not start_date:
            return dict(EquityValue.objects.filter(equity=self).values_list('date', 'price'))
        else:
            return dict(EquityValue.objects.filter(equity=self, date__gte=start_date).values_list('date', 'price'))


class EquityAlias(models.Model):
    '''
    This is needed to support the various imports.
    Example when manulife XLU trust reports dividends under symbol S007135.    The only way I can find that is to
    match on the name 'SELECT SECTOR SPDR TRUST THE UTILITIES SELECT SECTOR SPDR TRUST W...'
    which I match the divided to name 'SELECT SECTOR SPDR TRUST THE UTILITIES SELECT SECTOR SPDR TRUST C...

    when I first find XLU in a manulife import,  I will make an alias record using the name we import as'
    I can later match the dividend (and create an alias) for that two.
    '''

    objects = None
    symbol: str = models.CharField(max_length=32, verbose_name='Trading symbol')  # Symbol
    region: str = models.CharField(max_length=10, null=False, blank=False, default='Canada')
    name = models.TextField()
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.symbol} : {self.equity.symbol} - {self.name}'

    @staticmethod
    def find_equity(description: str, region: str) -> Equity:

        try:
            alias = EquityAlias.objects.get(name=description, region=region)
            return alias.equity
        except EquityAlias.DoesNotExist:
            pass  # Try it the hard way

        """        
        score: int = 0
        matched: bool = False
        match: EquityAlias = None
        for alias in EquityAlias.objects.filter(region=region):
            new_score = 0
            limit = len(alias.name) - 1
            for index in range(len(description) - 1):
                if index > limit:
                    break
                if description[index] != alias.name[index]:
                    break
                new_score += 1
            if new_score > score:
                score = new_score
                matched = True
                match = alias
        if matched:
            return match.equity
        """
        return None


class EquityValue(models.Model):
    """
    Track an equities value
    """

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE, limit_choices_to={'equity_type': 'Equity'})
    real_date: date = models.DateField(verbose_name='Recorded Date', null=True, validators=[MinValueValidator(datetime(1961, 1, 1).date()),
                                                                                            MaxValueValidator(datetime(2100, 1, 1).date())])
    date: date = models.DateField(verbose_name='Normalized Date')

    price: float = models.FloatField()
    source: int = models.IntegerField(choices=DataSource.choices(), default=DataSource.ESTIMATE.value)
    api: int = models.IntegerField(default=Equity.no_api)
    split_fixed: bool = models.BooleanField(default=False)

    def __str__(self):
        output = f'{self.equity} - {self.date}: {self.price} {DataSource(self.source).name}'
        return output

    @classmethod
    def get_or_create(cls, **kwargs):
        """
        update if source is more specific
        :param kwargs:
        :return:
        """
        created = False
        real_date = kwargs['real_date']
        norm_date = normalize_date(real_date)
        try:
            obj = cls.objects.get(equity=kwargs['equity'], date=norm_date)
            if obj.source > kwargs['source']:
                obj.source = kwargs['source']
                obj.price = kwargs['price']
                obj.real_date = real_date
                logger.debug('Better source - Updated %s' % obj)
                obj.save()
            elif obj.source == kwargs['source'] and (not obj.real_date or obj.real_date < real_date):
                obj.price = kwargs['price']
                obj.real_date = real_date
                logger.debug('More recent date - Updated %s' % obj)
                obj.save()
            elif obj.source == kwargs['source'] and obj.real_date == real_date:
                if obj.price != kwargs['price']:
                    logger.debug('Same Date price change- Updated %s' % obj)
                    obj.price = kwargs['price']
                    obj.save()
            else:
                logger.debug('Update is not worthy of a change')
        except EquityValue.DoesNotExist:
            kwargs['date'] = norm_date
            obj = cls.objects.create(**kwargs)
            created = True
            logger.debug('Created %s' % obj)
        return obj, created

    @classmethod
    def lookup_price(cls, equity: Equity, this_date) -> float:
        try:
            value = cls.objects.get(equity=equity, date=this_date).price

        except EquityValue.DoesNotExist:
            value = 0
        return value

    def save(self, *args, **kwargs):
        if self.real_date:
            self.date = normalize_date(self.real_date)
        elif self.date:
            self.real_date = self.date
            self.date = normalize_date(self.date)
        else:
            self.real_date = datetime.now().date()
            self.date = normalize_date(self.real_date)

        super(EquityValue, self).save(*args, **kwargs)


class FundValue(models.Model):
    """
    Track an AccountFunds value
    """

    fund = models.ForeignKey(Equity, on_delete=models.CASCADE, limit_choices_to={'equity_type': 'Value'})
    real_date: date = models.DateField(verbose_name='Recorded Date', null=True, validators=[MinValueValidator(datetime(1961, 1, 1).date()),
                                                                                            MaxValueValidator(datetime(2100, 1, 1).date())])
    date: date = models.DateField(verbose_name='Normalized Date')

    value: float = models.FloatField()
    source: int = models.IntegerField(choices=DataSource.choices(), default=DataSource.USER.value)

    class Meta:
        unique_together = (('fund', 'date'),)

    def __str__(self):
        output = f'{self.fund} - {self.date}: {self.value} {DataSource(self.source).name}'
        return output

    @property
    def lookup(self):
        try:
            _, account_id = self.fund.symbol.split('-')
            return Account.objects.get(id=account_id)
        except Account.DoesNotExist:
            logger.error('%s - value set to 0 get account based on fund %s' % (self, self.fund.symbol))
        except ValueError:
            logger.error('%s - value set to 0 get account cant parse fund %s' % (self, self.fund.symbol))
        return None

    @classmethod
    def plug_holes(cls, start_record, end_record, all_records=None):
        logger.debug('Start: %s End: %s' % (start_record, end_record))
        if not all_records:
            all_records = {d.date: d for d in FundValue.objects.filter(fund=start_record.fund, date__gt=start_record.date, date__lt=end_record.date)}

        diff = (end_record.date.year - start_record.date.year) * 12 + (end_record.date.month - start_record.date.month)
        if diff > 1:
            rate = (end_record.value - start_record.value) / diff
            value = start_record.value
            plug_date = normalize_date(start_record.date) + relativedelta(months=1)
            while plug_date < end_record.date:
                value += rate
                if plug_date in all_records:
                    if all_records[plug_date].value != value:
                        all_records[plug_date].value = value
                        all_records[plug_date].save(fix_holes=False)
                else:  # Create the record
                    FundValue(value=value, date=plug_date, real_date=plug_date, fund=start_record.fund, source=DataSource.ESTIMATE.value).save(fix_holes=False)
                plug_date = plug_date + relativedelta(months=1)

    def fix_holes(self):
        """
        Fix any missing dates (called with save)
        """
        try:
            earlier_date = FundValue.objects.filter(fund=self.fund, date__lt=self.date).exclude(source=DataSource.ESTIMATE.value).latest('date')
        except FundValue.DoesNotExist:
            earlier_date = None

        try:
            later_date = FundValue.objects.filter(fund=self.fund, date__gt=self.date).exclude(source=DataSource.ESTIMATE.value).earliest('date')
        except FundValue.DoesNotExist:
            try:
                later_date = later_date = FundValue.objects.filter(fund=self.fund, date__gt=self.date).earliest('date')
            except FundValue.DoesNotExist:
                later_date = None

        if earlier_date:
            FundValue.plug_holes(earlier_date, self)
        if later_date:
            FundValue.plug_holes(self, later_date)

        last_record = FundValue.objects.filter(fund=self.fund).exclude(source=DataSource.ESTIMATE.value).latest('date')
        self.plug_forward(last_record.value, increment=False)
        logger.debug('Plugging complete')

    def plug_forward(self, value, increment=True, account=None, all_records=None):
        '''
        Update all future
        '''

        if not account:
            account = self.lookup
        logger.debug('Pluging forward on account:%s' % account)
        end_date = account.end if account and account.end else normalize_today()
        FundValue.objects.filter(fund=self.fund, date__gt=end_date).delete()

        last_record = FundValue.objects.filter(fund=self.fund).exclude(source=DataSource.ESTIMATE.value).latest('date')

        if not all_records:
            all_records = {d.date: d for d in FundValue.objects.filter(fund=self.fund, date__gt=last_record.date)}

        plug_date = last_record.date + relativedelta(months=1)
        while plug_date <= end_date:
            if plug_date in all_records:
                if all_records[plug_date].value != value:
                    all_records[plug_date].value = value
                    all_records[plug_date].save(fix_holes=False)
            else:  # Create the record
                FundValue(value=value, date=plug_date, real_date=plug_date, fund=self.fund, source=DataSource.ESTIMATE.value).save(fix_holes=False)
            plug_date = plug_date + relativedelta(months=1)
        logger.debug('Plugging complete')

    @classmethod
    def fix_all_holes(cls, account):
        try:
            fund = Equity.objects.get(symbol=account.f_key)
        except Equity.DoesNotExist:
            logger.error('Failed to lookup equity %s for %s' % (account.f_key, account))
            return

        valid_records = list(FundValue.objects.filter(fund=fund).exclude(source=DataSource.ESTIMATE.value).order_by('date'))
        all_records = {d.date: d for d in FundValue.objects.filter(fund=fund)}
        if len(valid_records) > 1:
            this_record = valid_records[0]
            for next_record in valid_records[1:]:
                if this_record.date + relativedelta(months=1) != next_record.date:
                    FundValue.plug_holes(this_record, next_record, all_records=all_records)
                this_record = next_record

        last_record: FundValue = valid_records[len(valid_records) -1]
        last_record.plug_forward(last_record.value, increment=False,account=account, all_records=all_records)

    def save(self, *args, **kwargs):
        """
        Fix_holes if true, which is the default.   This change will be reflected between the last and next actual non-estimated value.
        Increment, if true the value was the incremental change to this record and that value will applied to future records
        """
        if 'fix_holes' in kwargs:
            fix_holes = kwargs.pop('fix_holes')
        else:
            fix_holes = True

        if 'increment' in kwargs:
            increment = kwargs.pop('increment')
            if increment and isinstance(increment, float) or isinstance(increment, int) or isinstance(increment, Decimal):
                increment = float(increment)
                fix_holes = False
            else:
                increment = 0
        else:
            increment = 0

        if self.real_date and not self.date:
            self.date = normalize_date(self.real_date)
        elif self.date and not self.real_date:
            self.real_date = self.date
            self.date = normalize_date(self.date)
        elif self.real_date and self.date:
            self.date = normalize_date(self.date)
        super(FundValue, self).save(*args, **kwargs)

        if self.value == 0:  # remove cruff going forward
            FundValue.objects.filter(date__gt=self.date, fund=self.fund).delete()
            try:
                _, account_id = self.fund.symbol.split('-')
                account = Account.objects.get(id=account_id)
                account.close(self.real_date)
            except Account.DoesNotExist:
                logger.error('%s - value set to 0 get account %s based on fund %s' % (self, account_id, self.fund.equity.symbol))
            except ValueError:
                logger.error('%s - value set to 0 get account cant parse fund %s' % (self, self.fund.equity.symbol))

        if fix_holes:
            self.fix_holes()
        if increment:
            self.plug_forward(increment, True)


class EquityEvent(models.Model):
    """
    Track an equities dividends
    Issue is alphavantage honour original price but adjusts Dividends
    whereas yahoo adjusts both.   I think I need to update the records Event/Value to record who set this value.

    """

    EVENT_TYPES = (('Dividend', 'Dividend'),  # Automatically created as part of 'Update' action
                   ('Split', 'Stock Split Dividend and Pricing will be adjusted based on API used'))

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    real_date: date = models.DateField(verbose_name='Recorded Date', null=True, validators=[MinValueValidator(datetime(1961, 1, 1).date()),
                                                                                            MaxValueValidator(datetime(2100, 1, 1).date())])
    date: date = models.DateField(verbose_name='Normalized Date')

    value = models.FloatField()
    event_type = models.TextField(max_length=10, choices=EVENT_TYPES)
    source: int = models.IntegerField(choices=DataSource.choices(), default=DataSource.ADMIN.value)
    api: int = models.IntegerField(default=Equity.no_api)
    split_fixed: bool = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.equity} - {self.date}:{self.event_type} {DataSource(self.source).name}'

    @classmethod
    def get_or_create(cls, **kwargs):
        """
        update if source is more specific
        :param kwargs:
        :return:
        """
        created = False
        obj = None
        equity = kwargs['equity']
        source = kwargs['source'] if 'source' in kwargs else DataSource.ESTIMATE.value
        real_date = kwargs['real_date']
        norm_date = normalize_date(real_date)

        if not equity.searchable or source <= DataSource.API.value:
            try:
                obj = cls.objects.get(equity=kwargs['equity'], date=norm_date, event_type=kwargs['event_type'])
                if 'source' in kwargs and obj.source > kwargs['source']:
                    obj.source = kwargs['source']
                    obj.value = kwargs['value']
                    obj.real_date = real_date
                    obj.save()
            except cls.MultipleObjectsReturned:
                logger.error('Multiple records for %s %s %s' % (kwargs['equity'], norm_date, kwargs['event_type']))
            except cls.DoesNotExist:
                kwargs['date'] = norm_date
                obj = cls.objects.create(**kwargs)
                created = True
        return obj, created

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.real_date)
        super(EquityEvent, self).save(*args, **kwargs)
        if self.event_type == 'Split':
            logger.info('Adjusting Dividends for %s' % self.equity)
            for event in EquityEvent.objects.filter(equity=self.equity, event_type='Dividend', date__lt=self.date, api=Equity.ypfinance, split_fixed=False):
                event.value *= self.value
                event.split_fixed = True
                event.save()
            for value in EquityValue.objects.filter(equity=self.equity, date__lt=self.date, api=Equity.ypfinance, split_fixed=False):
                value.price *= self.value
                value.split_fixed = True
                value.save


class BaseContainer(models.Model):

    name: str = models.CharField(max_length=128, primary_key=False, help_text='The name to display for this Account/Portfolio')
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='USD')

    class Meta:
        abstract = True

    def __str__(self):
        if self.__class__.__name__ == 'Account':
            return self.name

        return '%s:%s' % (self.__class__.__name__, self.name)

    @property
    def start(self):
        raise NotImplementedError

    @property
    def end(self):
        raise NotImplementedError

    @property
    def cost(self) -> int:
        raise NotImplementedError

    @property
    def container_type(self):
        raise NotImplementedError

    @property
    def dividends(self) -> int:
        raise NotImplementedError

    @property
    def value(self) -> int:
        raise NotImplementedError

    @property
    def growth(self) -> int:
        if self.value and self.cost:
            return self.value - self.cost
        else:
            return 0

    @property
    def p_key(self):
        return f'{self.__class__.__name__}:{self.id}:Container'

    @property
    def e_key(self):
        return f'{self.__class__.__name__}:{self.id}:Components'

    def reset(self):
        clear_cached_dataframe(self.e_key)
        clear_cached_dataframe(self.p_key)

    @property
    def p_pd(self) -> DataFrame:
        raise NotImplementedError

    @property
    def e_pd(self) -> DataFrame:
        raise NotImplementedError

    @property
    def summary(self) -> dict:
        """
        Return a dictionary of the current values of this container
        """
        this_date = np.datetime64(normalize_today())
        summary = self.e_pd.loc[self.e_pd['Date'] == this_date].agg(
            {'Cost': 'sum', 'TotalDividends': 'sum', 'Value': 'sum', 'RelGain': 'sum', 'UnRelGain': 'sum',
             'TBuy': 'sum', 'TSell': 'sum'}).to_dict()
        summary['Holdings'] = self.equities.distinct().count()
        summary['Name'] = self.name
        summary['Start'] = self.start
        summary['End'] = self.end
        if summary['Value'] == 0:  # Closed Account
            summary['UnRelGainPct'] = 0
            summary['RelGainPct'] = summary['RelGain'] * 100 / summary['TBuy'] if summary['TBuy'] else 0
        else:
            summary['RelGainPct'] = (summary['RelGain']) * 100 / summary['Cost'] if summary['Cost'] else 0  # todo: what if cost is 0 since we made some much
            summary['UnRelGainPct'] = summary['UnRelGain'] * 100 / summary['Cost'] if summary['Cost'] else 0
        return summary

    def get_eattr(self, key, query_date=normalize_today(), symbol=None):
        query_date = pd.Timestamp(query_date)
        try:
            if not symbol:
                return self.e_pd.loc[self.e_pd['Date'] == query_date][key].agg(['sum']).item()
            else:
                return self.e_pd.loc[(self.e_pd['Date'] == query_date) & (self.e_pd['Equity'] == symbol)][key].agg(['sum']).item()
        except ValueError:
            return 0

    def get_pattr(self, key, query_date=normalize_today()):
        return self.p_pd.loc[self.p_pd['Date'] == pd.to_datetime(query_date)][key].agg(['sum']).item()

    @property
    def transactions(self):
        raise NotImplementedError

    def equity_dataframe(self, equity: Equity) -> DataFrame:
        df = self.e_pd.loc[self.e_pd['Object_ID'] == equity.id].groupby(['Date']).agg(
            {'Shares': 'sum', 'Cost': 'sum', 'Price': 'max', 'TotalDividends': 'sum', 'TBuy': 'sum', 'TSell': 'sum'}).reset_index()
        df['Value'] = df['Shares'] * df['Price']
        df['AvgCost'] = df['Cost'] / df['Shares']
        df['UnRelGain'] = df['Value'] - df['Cost']
        df['AdjValue'] = df['Value'] + df['TotalDividends']
        return df


class Portfolio(BaseContainer):
    """
    new = df.groupby(['Date', 'Equity']).agg({'Shares': 'sum',  'Cost': 'sum', 'Price': 'max' , 'Dividends': 'max', 'TotalDividends': 'sum', 'Value': 'sum', 'AvgCost': 'max'}).reset_index()
    new = df.loc[df['Date'] == '2024-12-1'].groupby(['Date', 'Equity']).agg({'Shares': 'sum',  'Cost': 'sum', 'Price': 'max' , 'Dividends': 'max', 'TotalDividends': 'sum', 'Value': 'sum', 'AvgCost': 'max'}).reset_index()
    new = df.groupby('Date').agg({'Value': 'sum', 'Cost': 'sum'})
    new.index.to_list()
    new['Value'].to_list()
    new.round(2)
    """

    class Meta:
        unique_together = (('name', 'user'),)

    @property
    def start(self):
        try:
            return Account.objects.filter(portfolio=self).earliest('_start')._start
        except Account.DoesNotExist:
            pass  # Normal
        return None

    @property
    def end(self):
        if not Account.objects.filter(portfolio=self, _end__isnull=True).exists():
            try:
                return Account.objects.filter(portfolio=self).latest('_end')._end
            except Account.DoesNotExist:
                pass  # Likely
        return None

    @property
    def container_type(self):
        return 'Portfolio'

    @property
    def cost(self):
        try:
            return Account.objects.filter(portfolio=self).aggregate(Sum('_cost'))['_cost__sum']
        except KeyError:
            pass
        return None

    @property
    def dividends(self):
        try:
            return Account.objects.filter(portfolio=self).aggregate(Sum('_dividends'))['_dividends__sum']
        except KeyError:
            pass
        return None

    @property
    def value(self):
        try:
            return Account.objects.filter(portfolio=self).aggregate(Sum('_value'))['_value__sum']
        except KeyError:
            pass
        return None

    @property
    def equities(self) -> QuerySet[Equity]:
        return Equity.objects.filter(
            id__in=Transaction.objects.filter(account__portfolio=self, xa_action__in=Transaction.SHARE_TRANSACTIONS).values('equity__id')).order_by('symbol')

    @property
    def equity_keys(self):
        values = []
        for equity in Equity.objects.filter(id__in=Transaction.objects.filter(xa_action__in=Transaction.SHARE_TRANSACTIONS, account__in=Account.objects.filter(portfolio=self)).values_list('equity__id', flat=True).distinct()):
            values.append(equity.key)
        return values

    @property
    def transactions(self) -> QuerySet['Transaction']:
        """
        Cache and return a
        'equity1' : [xa1, xa2,...],
        'equity2' : [xa1,]
        :return:
        """
        return Transaction.objects.filter(account__portfolio=self)

    @property
    def p_pd(self) -> DataFrame:
        new = get_cached_dataframe(self.p_key)
        try:
            if not new.empty:
                return new
        except AttributeError:
            pass  # get may return None

        alist = []
        new = pd.DataFrame(columns=ACCOUNT_COL)
        for account in self.account_set.all():
            alist.append(account.p_pd)
        if len(alist):
            new = pd.concat(alist).groupby('Date').sum().reset_index()
        cache_dataframe(self.p_key, new)
        return new

    @property
    def e_pd(self) -> DataFrame:
        new = get_cached_dataframe(self.e_key)
        try:
            if not new.empty:
                return new
        except AttributeError as e:
            pass   # get may return None
        first = True
        new = pd.DataFrame(columns=EQUITY_COL)
        for account in self.account_set.all():
            if first:
                if not account.e_pd.empty and not account.e_pd.isna().all().all():
                    new = account.e_pd
                    first = False
            else:
                if not account.e_pd.empty and not account.e_pd.isna().all().all():
                    new = pd.concat([new, account.e_pd], axis=0)
                else:
                    logger.debug('Something fishing with account id %s' % account.id)
            pass
        cache_dataframe(self.e_key, new)
        return new

    @property
    def summary(self) -> dict:
        summary = super().summary
        summary['Type'] = 'Portfolio'
        summary['Id'] = self.id
        return summary


class Account(BaseContainer):
    """
    Name - Will need to be unique based on future user attribute
    Explicit Name - Used for importing,  This allows to rename (of name) without losing source
    Currency - Base currency of the account,  can be CAN or USD

    """

    class Meta:
        unique_together = (('account_name', 'user'),)

    ACCOUNT_TYPES = (('Investment', 'Investment'),
                     ('Cash', 'Bank'),
                     ('Value', 'Value'))
    account_type = models.TextField(max_length=12, choices=ACCOUNT_TYPES, default='Investment')
    account_name: str = models.CharField(max_length=128, null=True, blank=True, help_text='The name as imported')
    managed: bool = models.BooleanField(default=True, help_text="Set when Dividends will be reinvested")
    portfolio = models.ForeignKey(Portfolio, blank=True, null=True, on_delete=models.SET_NULL)

    # These Values are updated to allow for a quick loading of portfolio_list
    _cost: int = models.IntegerField(null=True, blank=True)  # Effective cost of all shares ever purchased
    _value: int = models.IntegerField(null=True, blank=True)  # of shares owned as of today
    _dividends: int = models.IntegerField(null=True, blank=True)  # Total dividends ever received
    _start: date = models.DateField(null=True, blank=True)
    _end: date = models.DateField(null=True, blank=True, help_text='Date this account was Closed')
    last_import: date = models.DateField(null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super(Account, self).__init__(*args, **kwargs)
        self._last_import = self.last_import

    class Meta:
        unique_together = (('account_name', 'user'),)

    def can_close(self, close_date: date, transfer_to=None) -> BoolReason:
        if self.closed:
            return BoolReason(False, 'Account is already closed')

        try:
            last_date = self.transactions.latest('real_date')
        except Transaction.DoesNotExist:
            return BoolReason(False, 'Can not close an account with no transactions - Delete instead')

        if last_date.real_date > close_date:
            return BoolReason(False, f'Close date must be later then {last_date.real_date}')

        if transfer_to:
            try:
                account = Account.objects.get(id=transfer_to.id, user=self.user)
                df = self.e_pd
                this_date = np.datetime64(close_date)
                shares = df.loc[(df['Date'] == this_date) & (df['Shares'] != 0)]
                if not shares.empty:
                    if account.portfolio != self.portfolio:
                        return BoolReason(False, 'Can not Transfer to shares between different portfolios')
            except Account.DoesNotExist:
                return BoolReason,(False, 'Can not Transfer to non-existing account')
        elif self.get_eattr('Value', close_date) != 0:
            return BoolReason(False, f'Can not close this account,  it still has active equities')
        return BoolReason(True, 'Ready to Close')

    def close(self, close_date: date, transfer_to=None):
        """
        Close an Account and adjust values as required.

        args:
            close_date: date - The date the account is being closed (No transactions can exist after this date)
        kwargs:
            transfer_to: Account - Default None, if set, this is where the balances will be moved to
            when doing a transfer to,  we update Funds so no contributions are lost,  we update TransIn so we can get a true picture how this account is doing.
        """

        test = self.can_close(close_date, transfer_to=transfer_to)
        if not test:
            logger.debug('Close of %s on %s (to %s) failed:%s' % (self, date, transfer_to, str(test)))
            return

        normalized = normalize_date(close_date)
        if transfer_to:
            account = Account.objects.get(id=transfer_to.id, user=self.user)
            df = self.e_pd
            this_date = np.datetime64(normalized)
            shares = df.loc[(df['Date'] == this_date) & (df['Shares'] != 0)]

            if not shares.empty:
                cash = self.get_pattr('Cash', normalized)

                for shares_dict in shares.to_dict(orient='records'):
                    cash += shares_dict['Value']

                    Transaction.objects.create(account=self, real_date=close_date, user=self.user, xa_action=Transaction.SELL,
                                               equity_id=shares_dict['Object_ID'], price=shares_dict['AvgCost'], quantity=shares_dict['Shares'])
                    Transaction.objects.create(account=account, real_date=close_date, user=self.user, xa_action=Transaction.BUY,
                                               equity_id=shares_dict['Object_ID'], price=shares_dict['AvgCost'], quantity=shares_dict['Shares'])

                funding = self.get_pattr('Funds', normalized) + self.get_pattr('Redeemed', normalized)  # Using addition because Redeemed is always negative
                actual = self.get_pattr('Actual', normalized)
                transfer_amount = funding - actual
                Transaction.objects.create(account=self, real_date=close_date, user=self.user, xa_action=Transaction.REDEEM, value=funding)
                Transaction.objects.create(account=account, real_date=close_date, user=self.user, xa_action=Transaction.FUND, value=funding)
                if transfer_amount:
                    Transaction.objects.create(account=self, real_date=close_date, user=self.user, xa_action=Transaction.TRANS_OUT, value=transfer_amount)
                    Transaction.objects.create(account=account, real_date=close_date, user=self.user, xa_action=Transaction.TRANS_IN, value=transfer_amount * -1)

        self._end = close_date
        self.save()
        self.update_static_values()

    @property
    def closed(self) -> bool:
        return self.end is not None

    @property
    def container_type(self):
        return 'Account'

    @property
    def cost(self) -> int:
        return self._cost

    @property
    def dividends(self) -> int:
        return self._dividends

    @property
    def end(self):
        return self._end

    @property
    def equities(self) -> QuerySet[Equity]:
        return Equity.objects.filter(Q(id__in=Transaction.objects.filter(account=self, equity__isnull=False).values_list('equity__id', flat=True).distinct()) |
                                     Q(symbol=self.f_key)).order_by('symbol')

    def extend_equity_df(self, equity: Equity, df: DataFrame) -> DataFrame:
        """ New """
        dividends: Dict[date, float]
        entry: EquityValue
        xas = self.transactions.filter(equity=equity)
        try:
            first = xas.earliest('date').date
        except Transaction.DoesNotExist:
            try:
                first = FundValue.objects.filter(fund=equity).earliest('date').date
            except FundValue.DoesNotExist:
                logger.error('Transaction/Funds %s:  No data' % self)
                return df

        trades: QuerySet = xas.filter(xa_action__in=Transaction.SHARE_TRANSACTIONS).exclude(xa_action=Transaction.REDIV).order_by('date')
        trade_dates = list(trades.order_by('date').values_list('date', flat=True).distinct())
        redivs: dict[date, float] = dict(xas.filter(date__gte=first, equity=equity, xa_action=Transaction.REDIV).values_list('date', 'quantity'))
        rediv_value: dict[date, float] = dict(xas.filter(date__gte=first, equity=equity, xa_action=Transaction.REDIV).values_list('date', 'currency_value'))

        if equity.equity_type == 'Equity':
            values = EquityValue.objects.filter(date__gte=first, equity=equity).order_by('date')
        else:
            values = FundValue.objects.filter(fund=equity).order_by('date')

        funded = dict(xas.filter(xa_action__in=[Transaction.FUND,]).annotate(month=TruncMonth('date')).values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))
        redeemed = dict(xas.filter(xa_action__in=[Transaction.REDEEM,]).annotate(month=TruncMonth('date')).values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))
        dividends = dict(EquityEvent.objects.filter(real_date__gte=first, equity=equity, event_type='Dividend').values_list('date', 'value'))
        equity_dividends = {e['date']: e for e in EquityEvent.objects.filter(equity=equity, event_type='Dividend').values('date', 'real_date', 'value')}
        shares_df = self.shares_df(equity)
        if len(redivs) > 0 and not self.managed:
            logger.error('Account %s has REDIVS but is not managed - The realized gains may be double counted')

        # warning - we may record dividends (via the API) a month earlier then the REDIV, seems they hold onto our money
        shares = cost = total_dividends = realized_gain = total_spend = total_redeem = avg_cost = 0
        for entry in values:  # This is over every month you owned this equity.
            cf = currency_factor(entry.date, equity.currency, self.currency)
            start_cost = cost
            start_shares = shares

            # Step 1,  Update shares based on trades
            if entry.date in trade_dates:  # We did something on this normalized day
                for trade in trades.filter(date=entry.date):  # Over each trade on this day
                    shares += trade.quantity
                    if trade.currency_value > 0:
                        total_spend += trade.currency_value
                    else:
                        if avg_cost != 0:
                            realized_gain += (trade.currency_value * -1) - (trade.quantity * - 1 * avg_cost)
                        else:
                            realized_gain += (trade.currency_value * -1) - (trade.quantity * -1 * trade.price)
                        total_redeem += trade.currency_value * -1
                    cost += trade.currency_value

            # Step 2, Update Dividends for non-managed
            if not self.managed:
                if entry.date in equity_dividends:
                    on_date = self.shares_on_date(shares_df, equity_dividends[entry.date]['real_date'])
                    dividend = equity_dividends[entry.date]['value'] * cf * on_date
                else:
                    dividend = 0
                total_dividends += dividend
                realized_gain += dividend
            else:
                dividend = 0

            # Step 3,  Update shares and buy cost of any reinvested dividends for this month
            if self.managed and entry.date in redivs:
                shares += redivs[entry.date]  # update shares
                total_spend += rediv_value[entry.date]  # We did buy them
                realized_gain += rediv_value[entry.date]
                cost += rediv_value[entry.date]

            if equity.equity_type == 'Value' or equity.equity_type == 'Cash':
                if equity.equity_type == 'Value':
                    if entry.date in funded:
                        cost += funded[entry.date]
                        total_spend += funded[entry.date]
                    if entry.date in redeemed:
                        cost -= redeemed[entry.date]
                        total_redeem += redeemed[entry.date]
                    value = entry.value
                else:  # Cost
                    value = entry.value
                    cost = value
                    total_redeemed = 0
                    total_cost = 0
                this_price = 0
                shares = 1
            else:
                this_price = entry.price

            if shares < 1 and start_shares != 0:  # Do this once, less than 1 because floats sometimes give crazy .000000001 values for 0
                if shares:
                    logger.debug('%s:%s - %s Negative shares %s' % (self.name, equity, entry.date, shares))
                value = entry.price * start_shares * cf if equity.equity_type == 'Equity' else value
                relgp = (start_cost - realized_gain) * 100 / start_cost if start_cost else 0
                unrealized_gain = total_redeem - total_spend
                unrelgp = unrealized_gain * 100 / start_cost if start_cost else 0
                shares = dividend = value = cost = 0
            else:
                value = entry.price * shares * cf if equity.equity_type == 'Equity' else value
                relgp = 100 - (cost - realized_gain) * 100 / cost if cost else 0
                unrealized_gain = value - total_spend + total_redeem if value else 0
                unrelgp = unrealized_gain * 100 / cost if unrealized_gain  and cost else 0

            avg_cost = total_spend / shares if shares or shares > 0 else 0  # Update average cost

            df.loc[len(df.index)] = [entry.date, equity.key, equity.id, 'Equity', shares, cost, this_price, dividend, total_dividends, value, total_spend, total_redeem, realized_gain, unrealized_gain, relgp, unrelgp, avg_cost]
        return df

    @property
    def e_pd(self) -> DataFrame:
        df = get_cached_dataframe(self.e_key)
        try:
            if not df.empty:
                return df
        except AttributeError:
            pass  # Get may return None

        now = datetime.now().date()
        df = pd.DataFrame(columns=EQUITY_COL)

        for equity in self.equities:
            df = self.extend_equity_df(equity, df)

        # new['Value'] = new['Shares'] * new['Price']
        df['AvgCost'] = df['Cost'] / df['Shares']
        df.replace([np.inf, -np.inf], 0, inplace=True) # Can not divide by 0 !
        try:
            df['Date'] = pd.to_datetime(df['Date'])
        except:
            logger.debug('DataFrame exception on date:%s' % df)
        cache_dataframe(self.e_key, df)

    # self.pd.loc[self.pd['Date'] == normalize_today()].sort_values(['Equity'])
        return df

    @property
    def f_key(self) -> str:
        return f'{self.account_type}-{self.id}'

    @property
    def p_pd(self) -> DataFrame:
        '''
        Regardless of the equities,  how is the account doing based on money in,  money out

        :return:
        '''

        df = get_cached_dataframe(self.p_key)
        try:
            if not df.empty:
                return df
        except AttributeError:
            pass   # get may return None

        df = pd.DataFrame(columns=ACCOUNT_COL)
        if not self.transactions:  # Account is new/empty
            return df

        # From chatgpt - most efficient method to build a dictionary of dividends received.
        dividends_df = self.e_pd.groupby('Date', as_index=False)['Dividends'].sum()
        dividends_df['Date'] = dividends_df['Date'].dt.date
        dividends = dict(zip(dividends_df['Date'], dividends_df['Dividends']))

        this_date = self.transactions.earliest('date').date
        final_date = normalize_date(self.end) if self.end else normalize_today()
        xas = self.transactions
        xa_dates = list(self.transactions.values_list('date', flat=True).distinct())
        funds = trans_in = withdraw = trans_out = cash = 0
        last_date = None
        while this_date <= final_date:
            new_cash = delta = 0
            if this_date in xa_dates:  # Maybe this should be more explicit since REDEEM on some accounts is monthly
                new_funds = xas.filter(xa_action=Transaction.FUND, date=this_date).aggregate(Sum('value'))['value__sum'] or 0
                new_cash = xas.filter(xa_action=Transaction.INTEREST, date=this_date).aggregate(Sum('value'))['value__sum'] or 0
                new_trans_in = xas.filter(xa_action=Transaction.TRANS_IN, date=this_date).aggregate(Sum('value'))['value__sum'] or 0
                new_withdraw = xas.filter(xa_action=Transaction.REDEEM, date=this_date).aggregate(Sum('value'))['value__sum'] or 0
                new_trans_out = xas.filter(xa_action=Transaction.TRANS_OUT, date=this_date).aggregate(Sum('value'))['value__sum'] or 0
                delta = xas.filter(xa_action__in=[Transaction.BUY, Transaction.SELL], date=this_date).aggregate(Sum('value'))['value__sum'] or 0

                funds += new_funds
                trans_in += new_trans_in
                withdraw += new_withdraw
                trans_out += new_trans_out
                delta *= -1  # delta is used to calculate cash,  and since buy is + and sell is - when need to negate the results
                new_cash += new_funds + new_withdraw + delta

                #new_gain = trans_in - trans_out
                #new_funding = funds - withdraw
                #cash += new_cash + new_gain + new_funding + delta

                #funding += new_funding
                #if funding < 0:
                #    gains += funding
                #    funding = 0
                #gains += new_gain
            dividend = dividends[this_date] if this_date in dividends else 0
            new_cash += dividend
            cash += new_cash
            # logger.debug('%s:funds:%s trans_in:%s withdraw:%s transout:%s delta:%s new:%s dividends: %s cash:%s' % (this_date, funds, trans_in, withdraw, trans_out, delta, new_cash, dividend, cash))
            # Clear up floating errors
            cash = 0 if (0 > cash < 1) or self.account_type != 'Investment' else cash
            # if funds or gains or cash:  # Skip empty rows
            #    if last_date:
            #        eff_funding = Inflation.inflated(eff_funding, last_date, this_date)
            #        eff_gains = Inflation.inflated(eff_gains, last_date, this_date)
            #    last_date = this_date
            #    eff_funding += new_funding
            #    eff_gains += new_gain
            #    # ['Date', 'Funds', 'Redeemed', 'TransIn', 'TransOut', 'NewCash', 'Cash', 'Effective']  # From Equities -> 'TotalDividends',  'Value',  Calculated: 'Effe
            df.loc[len(df.index)] = [this_date, funds, withdraw, trans_in, trans_out, new_cash, cash,  delta ]
            this_date = next_date(this_date)

        df['Date'] = pd.to_datetime(df['Date'])

        df = df.merge(self.e_pd.groupby(['Date']).agg({'Cost': 'sum', 'TotalDividends': 'sum', 'Dividends': 'sum', 'Value': 'sum'}).reset_index(), on='Date',
                                 how='left')
        #print(df)
        #df.fillna(0).infer_objects(copy=False)

        #df['Cost'] = df['Cost'].fillna(0)
        #df['Value'] = df['Value'].fillna(0)
        #df['TotalDividends'] = df['TotalDividends'].fillna(0)
        #df['Dividends'] = df['Dividends'].fillna(0)

        df.replace(np.nan, 0, inplace=True)
        df['Actual'] = df['Cash'] + df['Value']
        cache_dataframe(self.p_key, df)
        return df

    def reset(self):
        super(Account, self).reset()
        if self.portfolio:
            self.portfolio.reset()

    def save(self, *args, **kwargs):
        if not self.account_name:
            self.account_name = self.name
        super(Account, self).save(*args, **kwargs)

    def set_value(self, this_value, this_date, increment : bool = False) -> BoolReason:
        '''
        account.set_value(value, real_date, increment=False)
        '''
        increment = this_value if increment else 0
        datasource = DataSource.ESTIMATE.value if increment else DataSource.USER.value  # Estimate means we had a funding record vs explicit value
        logger.debug('Setting a value:%s on %s for %s' % (self, this_date, this_value))
        try:
            equity = Equity.objects.get(symbol=self.f_key)
            if FundValue.objects.filter(fund=equity, date=normalize_date(this_date)).exists():
                existing = FundValue.objects.get(fund=equity, date=normalize_date(this_date))
                if existing.real_date <= this_date or existing.source == DataSource.ESTIMATE.value:
                    existing.real_date = this_date
                    existing.value = this_value + existing.value if increment else this_value
                    existing.source = datasource

                    existing.save(increment=increment)
                else:
                    return BoolReason(False, "You have a later date already recorded for this action,  try Edit Transaction")
            else:
                existing = FundValue(fund=equity, value=this_value, real_date=this_date, source=datasource)
                existing.save(increment=increment)
        except Equity.DoesNotExist:
            return BoolReason(False, "This account has not been setup correctly")
        return BoolReason(True)

    @staticmethod
    def shares_on_date(shares_df: DataFrame, on_date=datetime.now().date()) -> float:
        """
        Based on a shares_df,  which is dataframe with a index thats a date and a value which is the number of shares on that date,  return the value for you
        """
        if shares_df.empty or on_date < shares_df.head(1).index.item():
            return 0

        try:
            return shares_df[shares_df.index <= on_date].iloc[-1].item()
        except IndexError:
            return 0

    def shares_df(self, equity: Equity) -> DataFrame:
        """
        Create a DataFrame based on number of shares held on each day of share trades
        Accessed with 'shares_on_date(shares_df, date=normalize_today)
        """
        result = {}
        shares = 0
        for xa in self.transactions.filter(equity=equity, quantity__isnull=False).order_by('real_date'):
            shares += xa.quantity
            result[xa.real_date] = shares
        if result:
            return pd.DataFrame.from_dict(result, orient='index')
        else:
            return pd.DataFrame()

    @property
    def start(self):
        try:
            return self.transactions.earliest('date').date
        except Transaction.DoesNotExist:
            if self._start:
                return self._start
            if len(self.p_pd) != 0:
                return self.p_pd['Date'].min()
            if len(self.e_pd) != 0:
                return self.e_pd['Date'].min()
        return normalize_today()

    @property
    def summary(self) -> dict:
        summary = super().summary
        summary['Type'] = 'Account'
        summary['Id'] = self.id
        summary['Closed'] = 'Closed' if self.closed else 'Open'
        summary['End'] = self.end

        return summary

    @property
    def symbol_count(self) -> int:
        return len(self.equities)

    def trade_details(self, equity, trade_date) -> [float, float]:
        result = self.transactions.filter(equity=equity, date=trade_date,
                                          xa_action__in=[Transaction.BUY, Transaction.REDIV, Transaction.SELL]).aggregate(Sum('quantity'), Avg('price'))
        quantity = round(result['quantity__sum'], 2) if result['quantity__sum'] else 0
        price = round(result['price__avg'], 2) if result['price__avg'] else 0
        return quantity, price

    def trade_dates(self, equity) -> List[date]:
        return list(
            Transaction.objects.filter(account=self,
                                       equity=equity,
                                       xa_action__in=[Transaction.BUY, Transaction.REDIV, Transaction.SELL]).values_list(
                'date', flat=True).order_by('date'))

    @property
    def transactions(self) -> QuerySet['Transaction']:
        return Transaction.objects.filter(account=self)

    def update(self):
        """
        Ensure that each of my equities is updated
        :return:
        """
        key = self.user.profile.av_api_key if self.user.profile.av_api_key else None
        for equity in self.equities:
            if equity.update(force=False, key=key):
                sleep(2)  # Any faster and my free API will fail
        self.reset()

    def update_static_values(self):
        """
        Ensure that each of my equities is updated
        :return:
            cost: int = models.IntegerField(null=True, blank=True)  # Total cost of all shares ever purchased
            value: int = models.IntegerField(null=True, blank=True)  # of shares owned as of today
            growth: int = models.IntegerField(null=True, blank=True)  # PV - cost + redeemed values
            dividends: int = models.IntegerField(null=True, blank=True)  # Total dividends ever received
            start: date = models.DateField(null=True, blank=True)
            end: date = models.DateField(null=True, blank=True)

        """
        if self.account_type == 'Cash':
            self._cost = 0
            self._value = self.get_eattr('Cost')
            self._dividend = 0
        else:
            self._cost = self.get_pattr('Funds')
            self._value = self.get_pattr('Actual')
            self._dividends = self.get_eattr('TotalDividends')

        if len(self.p_pd) != 0:
            self._start = self.p_pd['Date'].min()
        elif len(self.e_pd) != 0:
            self._start = self.e_pd['Date'].min()
        self.save()

    @property
    def value(self) -> int:
        return self._value


class Transaction(models.Model):
    """
    Track changes made to an equity on a account
    """

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

    SHARE_TRANSACTIONS = [BUY, REDIV, SELL, TRANS_IN, TRANS_OUT]
    MONEY_TRANSACTIONS = [FUND, REDEEM, INTEREST, FEES]

    def get_choices(self):
        """
            likely too much logic here
        """
        choices = list()

        for choice in Equity.objects.all():
            name = f'{choice.key} - {choice.equity_type}'
            if choice.region:
                name = f'{name} ({Equity.region_lookup()[choice.region]})'
            choices.append((choice.id, name))
        return sorted(choices)

    TRANSACTION_TYPE = ((FUND, 'Deposit'),                  # Value only and always positive
                        (BUY, 'Buy'),                       # Price and Quantity
                        (REDIV, 'Reinvested Dividend'),     # Price and Quantity but Price is set to 0
                        (SELL, 'Sell'),
                        (INTEREST, 'Dividends/Interest'),
                        (REDEEM, 'Withdraw'),
                        (FEES, 'Fees Paid'),
                        (TRANS_IN, 'Transferred In'),
                        (TRANS_OUT, 'Transferred Out'),
                        (VALUE, 'Value'),
                        (BALANCE, 'Balance')
                        )

    TRANSACTION_MAP = dict(TRANSACTION_TYPE)

    account: Account = models.ForeignKey(Account, on_delete=models.CASCADE)
    equity: Equity = models.ForeignKey(Equity, null=True, blank=True, on_delete=models.CASCADE)
    real_date: date = models.DateField(verbose_name='Transaction Date', null=True, validators=[MinValueValidator(datetime(1961, 1, 1).date()),
                                                                                               MaxValueValidator(datetime(2100, 1, 1).date())])
    date: date = models.DateField(verbose_name='Normalized Date')
    price: float = models.FloatField()
    quantity: float = models.FloatField()
    value: float = models.FloatField(null=True, blank=True)
    currency_value: float = models.FloatField(null=True, blank=True)
    xa_action: int = models.IntegerField(help_text="Select a Account", choices=TRANSACTION_TYPE)
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    estimated = models.BooleanField(default=False)

    def __str__(self):
        try:
            xa_str = self.TRANSACTION_MAP[self.xa_action]
        except KeyError:
            xa_str = 'DATA CORRUPTION'
        return f'{self.account}:{self.equity}:{self.real_date.strftime("%Y-%m-%d")}:{xa_str}: {self.price} {self.quantity} {self.value}'  # pragma: no cover

    @property
    def action_str(self):
        if self.xa_action in self.TRANSACTION_MAP:
            return self.TRANSACTION_MAP[self.xa_action]
        else:
            value = 'Unknown'
        return value

    @classmethod
    def edit_choices(cls, input_action):
        """
        Used by the TransactionForm,  only certain actions are changeable
        """
        if input_action == cls.FUND or input_action == cls.TRANS_IN:
            return [(cls.FUND, cls.TRANSACTION_MAP[cls.FUND]),
                    (cls.TRANS_IN, cls.TRANSACTION_MAP[cls.TRANS_IN])]
        if input_action == cls.BUY or input_action == cls.TRANS_IN:
            return [(cls.BUY, cls.TRANSACTION_MAP[cls.BUY]),
                    (cls.TRANS_IN, cls.TRANSACTION_MAP[cls.TRANS_IN])]
        if input_action == cls.SELL or input_action == cls.TRANS_OUT:
            return [(cls.SELL, cls.TRANSACTION_MAP[cls.SELL]),
                    (cls.TRANS_OUT, cls.TRANSACTION_MAP[cls.TRANS_OUT])]
        if input_action == cls.REDEEM or input_action == cls.TRANS_OUT:
            return [(cls.REDEEM, cls.TRANSACTION_MAP[cls.REDEEM]),
                    (cls.TRANS_OUT, cls.TRANSACTION_MAP[cls.TRANS_OUT])]
        if input_action:
            return [(input_action, cls.TRANSACTION_MAP[input_action])]
        else:
            return []

    @property
    def is_major(self) -> bool:
        if self.xa_action in [self.FUND, self.BUY, self.SELL, self.REDEEM, self.TRANS_IN, self.TRANS_OUT] or \
                (self.value and self.value > 100 and self.xa_action != self.REDIV):
            return True
        return False

    def save(self, *args, **kwargs):
        """
        Do the logic to make sure value have the correct value
        """

        do_reset = False if 'reset' not in kwargs else kwargs.pop('reset')
        source = DataSource.ESTIMATE.value if 'source' not in kwargs else kwargs.pop('source')

        if self.real_date:
            self.date = normalize_date(self.real_date)
        elif self.date:
            self.real_date = self.date
            self.date = normalize_date(self.date)
        else:
            self.real_date = datetime.now().date()
            self.date = normalize_date(self.real_date)

        self.price = 0 if not self.price else abs(self.price)
        self.quantity = 0 if not self.quantity else self.quantity
        self.value = self.value if self.value else self.price * self.quantity

        if self.xa_action == self.REDIV:
            self.price = 0  # On Dividends

        elif self.xa_action in [self.SELL, self.REDEEM, self.FEES]:
            self.quantity = abs(self.quantity) * -1
            self.value = abs(self.value) * -1
        elif self.xa_action in [self.BUY, self.FUND]:
            self.quantity = abs(self.quantity)
            self.value = abs(self.value)

        if self.equity:
            cf = currency_factor(self.date, self.equity.currency, self.account.currency)
            self.currency_value = self.value * cf
        else:
            self.currency_value = self.value
        super(Transaction, self).save(*args, **kwargs)

        if self.price != 0 and self.equity and not self.equity.searchable:
            try:
                ev = EquityValue.objects.get(equity=self.equity, date=self.date)
                if ev.source > source or (ev.source == source and ev.real_date < self.real_date):
                    ev.price = self.price
                    ev.real_date = self.real_date
                    ev.source = source
                    ev.save()
            except EquityValue.DoesNotExist:
                EquityValue.objects.create(source=source, equity=self.equity, price=self.price, real_date=self.real_date, date=self.date)

            if do_reset:
                if self.equity:
                    for account in Account.objects.filter(id__in=Transaction.objects.filter(equity=self.equity).values_list('account', flat=True).distinct()):
                        account.reset()

        else:
            if do_reset:
                self.account.reset()

    @classmethod
    def transaction_value(cls, xa_string: str) -> int:
        for key, value in cls.TRANSACTION_TYPE:
            if value == xa_string:
                return key
        raise AssertionError(f'Invalid transaction string: {xa_string}')
