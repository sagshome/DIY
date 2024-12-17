"""
The models here,  are used to build a monthly snapshot of financial data.   To normalize data,  the last trading
day of the month is normalized to the first date of the month.
"""

# todo:  what should I do when someone trys to buy something via import or manual and they do not have the cash
#  1. Warning them and silently give them the cash ?  If they fix it up by doing a proper transaction,  how do I clear
#     old one.

import logging
import pandas as pd
import numpy as np

from enum import Enum
from typing import List, Dict
from datetime import datetime, date
from time import sleep
from pandas import DataFrame

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import QuerySet, Sum, Avg
from django.utils.functional import cached_property
from django.urls import reverse

from base.models import URL
from base.utils import normalize_date, normalize_today, next_date, cache_dataframe, clear_cached_dataframe,  get_cached_dataframe

logger = logging.getLogger(__name__)

AV_API_KEY = settings.ALPHAVANTAGEAPI_KEY


class DataSource(Enum):
    ADMIN = 10  # !
    ADJUSTED = 20 # F
    API = 30  # A
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
        return '.'


CURRENCIES = (
    ('CAD', 'Canadian Dollar'),
    ('USD', 'US Dollar')
)

EPOCH = datetime(2014, 1, 1).date()  # Before this date.   I was too busy working

AV_REGIONS = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
'''

# my_currency = 'CAD'  # todo: Should be set via a user profile
EQUITY_COL = ['Date', 'Equity',  # One record for each date we held the equity  todo: stop making records when equity is sold out
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

ACCOUNT_COL = ['Date', 'Funds', 'Redeemed']  # From Equities -> 'TotalDividends',  'Value',  Calculated: 'EffectiveCost',  ]


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
        result = URL.get('BOC',f'FXUSDCAD,FXCADUSD/json?start_date={first_str}&order_dir=desc')

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
        """
        first = EPOCH
        first_str = first.strftime('%Y-%m-%d')

        result = URL.get('BOC',f'STATIC_INFLATIONCALC/json?start_date={first_str}')
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


class Equity(models.Model):

    EQUITY_TYPES = (
        ('Equity', 'Equity/ETF'),
        ('ETF', 'Exchange Traded Fund'),
        ('MF', 'Mutual Fund'),
        ('MM', 'Value Account')
    )

    REGIONS = (
        ('Canada', 'Canada'),
        ('US', 'US'),
    )

    @classmethod
    def region_lookup(cls):
        result = {}
        for region in cls.REGIONS:
            result[region[0]] = region[1]
        return result

    symbol: str = models.CharField(max_length=32, verbose_name='Trading symbol')  # Symbol
    region: str = models.CharField(max_length=10, null=False, blank=False, default='Canada')

    name: str = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    equity_type: str = models.CharField(max_length=10, blank=True, null=True, choices=EQUITY_TYPES)
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='USD')
    last_updated: date = models.DateField(blank=True, null=True)
    deactived_date: date = models.DateField(blank=True, null=True)
    searchable: bool = models.BooleanField(default=False)  # Set to False, when this is data that was forced into being
    validated: bool = models.BooleanField(default=False)  # Set to True was validation is done

    class Meta:
        unique_together = ('symbol', 'region')

    @property
    def key(self):
        if self.region == 'Canada':
            return self.symbol + '.TRT'
        return self.symbol  # US does not get a region decorator via AV_URL

    def __str__(self):
        return f'{self.symbol} ({self.region}) - {self.name}'

    def save(self, *args, **kwargs):
        if 'update' in kwargs:
            do_update = kwargs.pop('update')
        else:
            do_update = False

        if not self.symbol.isupper():
            self.symbol = self.symbol.upper()

        if not self.validated and do_update:
            self.set_equity_data()

        super(Equity, self).save(*args, **kwargs)
        if self.searchable and do_update:
            self.update_external_equity_data(False)

    def set_equity_data(self):
        request = URL.get('AVURL', f'SYMBOL_SEARCH&keywords={self.key}&apikey={AV_API_KEY}')
        if request.status_code == 200:
            self.validated = True
            data = request.json()
            if 'bestMatches' in data and len(data['bestMatches']) > 0 and data['bestMatches'][0]['9. matchScore'] == '1.0000':
                self.name = data['bestMatches'][0]['2. name']
                self.equity_type = data['bestMatches'][0]['3. type']
                for region in self.REGIONS:
                    if data['bestMatches'][0]['4. region'] == region[1]:
                        self.region = region[0]
                        break
                self.currency = data['bestMatches'][0]['8. currency']
                self.searchable = True
        else:
            self.validated = False
            self.searchable = False

    def fill_equity_value_holes(self):
        """
        Look for months without an equity value,  and calculated a value based on direct rate of change.
        It is possible that values will need to be re-filled as data is populated via new transactions / sources
        """
        estimated = DataSource.ESTIMATE.value

        all_dates: Dict[date, float] = dict(EquityValue.objects.filter(equity=self).values_list('date', 'price'))
        set_dates: Dict[date, float] = dict(EquityValue.objects.filter(equity=self).exclude(source=estimated).values_list('date', 'price'))

        last_date: date = None
        last_price: float = 0  # just to stop the warnings,  it can't actually be used before its referenced
        for this_date in sorted(set_dates.keys()):
            if last_date and not this_date == next_date(last_date):  # We have a hole
                months = (this_date.year - last_date.year) * 12 + this_date.month - last_date.month  # How many
                change_increment = (set_dates[this_date] - last_price) / months
                for _ in range(months - 1):  # Fill holes up to this_date
                    next_month = next_date(last_date)
                    last_price = last_price + change_increment
                    if next_month not in all_dates:
                        EquityValue.objects.create(equity=self, real_date=next_month, price=last_price, source=estimated)
                    else:
                        if all_dates[next_month] != last_price:
                            e = EquityValue.objects.get(equity=self, date=next_month)
                            if not e.real_date:
                                e.real_date = next_month
                            e.price = last_price
                            e.save()
                    last_date = next_month

            last_date = this_date
            last_price = set_dates[this_date]

        try:
            last_entry = EquityValue.objects.filter(equity=self).exclude(source=estimated).order_by('-date')[0]
            current_date = normalize_today()
            date_value = next_date(last_entry.date)
            if not date_value >= current_date:
                price_value = last_entry.price
                while date_value <= current_date:
                    EquityValue.get_or_create(equity=self, real_date=date_value, price=price_value, source=DataSource.ESTIMATE.value)
                    date_value = next_date(date_value)
        except IndexError:
            logger.error('No EquityValue data for:%s' % self)

    def update_external_equity_data(self, force):
        if self.searchable:
            # Cleanup any cruff sucked in during an import.
            EquityEvent.objects.filter(equity=self, event_type='Dividend', source__gt=DataSource.API.value).delete()
            EquityValue.objects.filter(equity=self, source__gt=DataSource.API.value).delete()
            now = datetime.now().date()
            if now == self.last_updated and not force:
                logger.info('%s - Already updated %s' % (self, now))
            else:
                data_key = 'Monthly Adjusted Time Series'
                result = URL.get('AVURL', f'TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.key}&apikey={AV_API_KEY}')

                if not result.status_code == 200:
                    logger.warning('AVURL Result is %s - %s' % (result.status_code, result.reason))
                    return

                data = result.json()
                if data_key in data:  # if not,  we timed out our API key
                    for entry in data[data_key]:
                        try:
                            date_value = datetime.strptime(entry, '%Y-%m-%d').date()
                        except ValueError:
                            logger.error('Invalid date format in: %s' % entry)
                            return

                        if date_value >= EPOCH:
                            EquityValue.get_or_create(equity=self, source=DataSource.API.value, real_date=date_value,
                                                      price=float(data[data_key][entry]['4. close']))

                            dividend = float(data[data_key][entry]['7. dividend amount'])
                            if dividend != 0:
                                EquityEvent.get_or_create(equity=self, event_type='Dividend', real_date=date_value,
                                                          value=dividend, source=DataSource.API.value)
                    self.last_updated = now
                    self.save(update=False)
                else:
                    if 'Information' in data and data['Information'].startswith('Thank you for using'):
                        logger.warning("Too many calls to AVURL")
                        URL.pause("AVURL")
                    else:
                        logger.warning('Invalid Response: %s' % data)

    def update(self, force: bool = False, key: str = None):
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month).
        """
        if key:
            if not self.validated:
                self.set_equity_data()
                self.save()
            elif self.searchable:
                self.update_external_equity_data(force)
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

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    real_date: date = models.DateField(verbose_name='Recorded Date', null=True)
    date: date = models.DateField(verbose_name='Normalized Date')

    price: float = models.FloatField()
    source: int = models.IntegerField(choices=DataSource.choices(), default=DataSource.ESTIMATE.value)

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
                obj.save()
            elif obj.source == kwargs['source'] and (not obj.real_date or obj.real_date < real_date):
                obj.price = kwargs['price']
                obj.real_date = real_date
                obj.save()
            elif obj.source == kwargs['source'] and obj.real_date == real_date:
                obj.price = kwargs['price']
                obj.save()

        except EquityValue.DoesNotExist:
            kwargs['date'] = norm_date
            obj = cls.objects.create(**kwargs)
            created = True
        return obj, created

    @classmethod
    def lookup_price(cls, equity: Equity, this_date) -> float:
        try:
            value = cls.objects.get(equity=equity, date=this_date).price

        except EquityValue.DoesNotExist:
            value = 0
        return value

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.real_date)
        super(EquityValue, self).save(*args, **kwargs)


class EquityEvent(models.Model):
    """
    Track an equities dividends
    """

    objects = None
    EVENT_TYPES = (('Dividend', 'Dividend'),  # Automatically created as part of 'Update' action
                   ('SplitAD', 'Stock Split with Adjusted Dividends'),  # Historic dividends adjusted
                   ('Split', 'Stock Split'))

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    real_date: date = models.DateField(verbose_name='Recorded Date', null=True)
    date: date = models.DateField(verbose_name='Normalized Date')

    value = models.FloatField()
    event_type = models.TextField(max_length=10, choices=EVENT_TYPES)
    source: int = models.IntegerField(choices=DataSource.choices(), default=DataSource.ADMIN.value)

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
        if self.event_type == 'SplitAD':
            logger.info('Adjusting Dividends for %s' % self.equity)
            for event in EquityEvent.objects.filter(equity=self.equity, event_type='Dividend', date__lt=self.date):
                event.value = event.value * self.value
                event.save()
        if self.event_type.startswith('Split'):
            logger.info('Adjusting Shares for %s' % self.equity)
            for transaction in Transaction.objects.filter(equity=self.equity, date__lt=self.date):
                Transaction.objects.create(account=transaction.account,
                                           equity=self.equity, price=0,
                                           quantity=transaction.quantity, xa_action=Transaction.BUY, real_date=self.real_date)


class BaseContainer(models.Model):

    name: str = models.CharField(max_length=128, primary_key=False, help_text='Enter a unique name for this account')
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='USD')

    class Meta:
        abstract = True

    def __str__(self):
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

    @cached_property
    def p_pd(self) -> DataFrame:
        raise NotImplementedError

    @cached_property
    def e_pd(self) -> DataFrame:
        raise NotImplementedError

    @property
    def summary(self) -> dict:
        """
        Return a dictionary of the current values of this account
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
        return Equity.objects.filter(symbol__in=Transaction.objects.filter(account__portfolio=self).values('equity__symbol')).order_by('symbol')

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

    @cached_property
    def p_pd(self) -> DataFrame:
        new = get_cached_dataframe(self.p_key)
        try:
            if not new.any:
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

    @cached_property
    def e_pd(self) -> DataFrame:
        new = get_cached_dataframe(self.e_key)
        try:
            if not new.any:
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


class AccountSummary:

    def __init__(self, key, name: str, xas: QuerySet, equity_pd: pd, currency: str, managed: bool = False):
        self.cache_key = key
        self.name = name
        self.xas = xas
        self.epd = equity_pd
        self.currency = currency

    ACCOUNT_COL = ['Date', 'Funds', 'Redeemed', 'Effective']  # From Equities -> 'TotalDividends',  'Value',  Calculated: 'EffectiveCost',  ]

    @property
    def pd(self) -> DataFrame:
        new = get_cached_dataframe(self.cache_key)
        try:
            if not new.any:
                return new
        except AttributeError:
            logger.debug('Not cached %s' % self.cache_key)
            pass   # get may return None

        new = pd.DataFrame(columns=ACCOUNT_COL)
        if not self.xas:  # Account is new/empty
            return new

        trades: QuerySet = self.xas.filter(xa_action__in=[Transaction.FUND, Transaction.REDEEM]).order_by('date')
        if not trades.exists():
            logger.error('Transaction set:  No Funding/Withdraws in transaction data for %s' % self.name)
            return new
        this_date = trades.earliest('date').date
        final_date = normalize_today()

        xa_dates = list(self.xas.values_list('date', flat=True).distinct())
        funding = redeemed = 0
        while this_date <= final_date:
            if this_date in xa_dates:
                funds = trades.filter(xa_action=Transaction.FUND, date=this_date).aggregate(Sum('value'))['value__sum']
                funding += funds if funds else 0
                withdraw = trades.filter(xa_action=Transaction.REDEEM, date=this_date).aggregate(Sum('value'))['value__sum']
                redeemed += withdraw if withdraw else 0

            new.loc[len(new.index)] = [this_date, funding, redeemed]
            this_date = next_date(this_date)

        new['Date'] = pd.to_datetime(new['Date'])
        cache_dataframe(self.cache_key, new)
        return new


class AccountEquitySummary:
    """
    Non-DB class that will calculate the historic information regarding equities in an account.    We purposefully do
    not reference raw account or transaction data.   This is done so that we can compare / create speculative data
    """

    def __init__(self, key, name: str, xas: QuerySet, currency: str, managed: bool = False,
                 fake_equity: Equity = None, real_equity: Equity = None):
        self.cache_key = key
        self.name = name
        self.xas = xas
        self.currency = currency
        self.managed = managed  # We do not extract dividends
        self.fake_equity = fake_equity
        self.real_equity = real_equity
        self.inflation_rates: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))

    def process_equity(self, equity: Equity, df: DataFrame) -> DataFrame:
        """ New """
        dividends: Dict[date, float]
        moneys: Dict[date, float]
        entry: EquityValue
        trades: QuerySet = self.xas.filter(equity=equity, xa_action__in=Transaction.SHARE_TRANSACTIONS).exclude(xa_action=Transaction.REDIV).order_by('date')

        if len(trades) == 0:  # pragma: no cover
            logger.error('Transaction set %s:  No Trades in transaction data' % equity)
            return df
        trade_dates = list(trades.order_by('date').values_list('date', flat=True).distinct())
        first = trades.earliest('date').date

        equity_values = EquityValue.objects.filter(date__gte=first, equity=equity).order_by('date')
        dividends = dict(EquityEvent.objects.filter(date__gte=first, equity=equity, event_type='Dividend').values_list('date', 'value'))
        # moneys = dict(Transaction.objects.filter(date__gte=first, equity=equity, xa_action__in=[Transaction.FEES, Transaction.INTEREST]).values_list('date', 'value'))
        redivs: dict[date, float] = dict(Transaction.objects.filter(date__gte=first, equity=equity, xa_action=Transaction.REDIV).values_list('date', 'quantity'))
        rediv_value: dict[date, float] = dict(Transaction.objects.filter(date__gte=first, equity=equity, xa_action=Transaction.REDIV).values_list('date', 'currency_value'))

        if len(redivs) > 0 and not self.managed:
            logger.error('Account %s has REDIVS but is not managed - The realized gains may be double counted')

        # warning - we may record dividends (via the API) a month earlier then the REDIV, seems they hold onto our money
        shares = cost = total_dividends = realized_gain = unrealized_gain = unrelgp = relgp = total_spend = total_redeem = avg_cost = 0
        for entry in equity_values:  # This is over every month you owned this equity.
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

            # Step 3, Update Dividends for non-managed
            if not self.managed:
                dividend = dividends[entry.date] * cf * shares if entry.date in dividends else 0
                total_dividends += dividend
                realized_gain += dividend
            else:
                dividend = 0

            # Step 2,  Update shares and buy cost of any reinvested dividends for this month
            if self.managed and entry.date in redivs:
                shares += redivs[entry.date]  # update shares
                total_spend += rediv_value[entry.date]  # We did buy them
                realized_gain += rediv_value[entry.date]
                cost += rediv_value[entry.date]

            if shares < 1 and start_shares != 0:  # Do this once
                if shares:
                    logger.debug('%s:%s - %s Negative shares %s' % (self.name, equity, entry.date, shares))
                value = entry.price * start_shares * cf
                relgp = (start_cost - realized_gain) * 100 / start_cost if start_cost else 0
                unrealized_gain = total_redeem - total_spend
                unrelgp = unrealized_gain * 100 / start_cost if start_cost else 0
                shares = dividend = value = cost = 0
            else:
                value = entry.price * shares * cf
                relgp = 100 - (cost - realized_gain) * 100 / cost if cost else 0
                unrealized_gain = value - total_spend + total_redeem if value else 0
                unrelgp = unrealized_gain * 100 / cost if unrealized_gain else 0

            avg_cost = total_spend / shares if shares or shares > 0 else 0  # Update average cost

            df.loc[len(df.index)] = [entry.date, equity.key, shares, cost, entry.price, dividend, total_dividends, value, total_spend, total_redeem, realized_gain, unrealized_gain, relgp, unrelgp, avg_cost]
        return df

    @property
    def pd(self) -> pd:
        '''
        Historic data for each equity in a account
        :return:  panda.Dataframe
        '''
        new = get_cached_dataframe(self.cache_key)
        try:
            if new.any:
                return new
        except AttributeError:
            pass  # Get may return None

        now = datetime.now()
        new = pd.DataFrame(columns=EQUITY_COL)
        inflation_rates: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))
        try:
            portfolio_start = self.xas.order_by('date')[0].date
        except IndexError:  # pragma: no cover
            return new

        for equity in Equity.objects.filter(transaction__in=self.xas).distinct():
            if self.real_equity:
                if self.real_equity == equity:
                    self.process_equity(equity, new)
            else:
                self.process_equity(equity, new)

        # new['Value'] = new['Shares'] * new['Price']
        new['AvgCost'] = new['Cost'] / new['Shares']
        new.replace([np.inf, -np.inf], 0, inplace=True) # Can not divide by 0 !
        new['Date'] = pd.to_datetime(new['Date'])
        logger.warning('Created Equity DataFrame for %s in %s' % (self.name, (datetime.now() - now).seconds))
        cache_dataframe(self.cache_key, new)
        return new


class Account(BaseContainer):
    """
    Name - Will need to be unique based on future user attribute
    Explicit Name - Used for importing,  This allows to rename (of name) without losing source
    Currency - Base currency of the account,  can be CAN or USD

    """

    class Meta:
        unique_together = (('account_name', 'user'),)

    ACCOUNT_TYPES = (('Investment', 'Investment'),
                     ('Holding', 'Holding'))
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

    def reset(self):
        super(Account, self).reset()
        if self.portfolio:
            self.portfolio.reset()

    @property
    def start(self):
        return self._start

    @property
    def end(self):
        return self._end

    @property
    def cost(self) -> int:
        return self._cost

    @property
    def value(self) -> int:
        return self._value

    @property
    def dividends(self) -> int:
        return self._dividends

    def save(self, *args, **kwargs):
        if not self.account_name:
            self.account_name = self.name
        super(Account, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('account_details', kwargs={'pk': self.pk})

    @property
    def closed(self) -> bool:
        return self.end is None

    @property
    def e_pd(self) -> DataFrame:
        # self.pd.loc[self.pd['Date'] == normalize_today()].sort_values(['Equity'])
        return AccountEquitySummary(self.e_key, str(self.name), self.transactions, self.currency, managed=self.managed).pd

    @property
    def p_pd(self) -> DataFrame:
        '''
        Regardless of the equities,  how is the account doing based on money in,  money out
        :return:
        '''
        return AccountSummary(self.p_key, str(self.name), self.transactions, self.e_pd, self.currency, managed=self.managed).pd

    @property
    def summary(self) -> dict:
        summary = super().summary
        summary['Type'] = 'Account'
        summary['Id'] = self.id
        return summary

    def switch(self, new_equity: Equity, original: Equity = None) -> DataFrame:
        return AccountEquitySummary(self.e_key, str(self.name),
                                    self.transactions,
                                    self.currency,
                                    managed=self.managed,
                                    fake_equity=new_equity,
                                    real_equity=original).pd

    @property
    def equities(self) -> QuerySet[Equity]:
        return Equity.objects.filter(symbol__in=Transaction.objects.filter(account=self).values('equity__symbol')).order_by('symbol')

    @property
    def equity_keys(self):
        # return sorted(self.e_pd['Equity'].unique())
        values = []
        # Equity.objects.filter()
        for equity in Equity.objects.filter(id__in=Transaction.objects.filter(xa_action__in=Transaction.SHARE_TRANSACTIONS, account=self).values_list('equity__id', flat=True).distinct()):
            values.append(equity.key)
        return values

    @property
    def symbol_count(self) -> int:
        return len(self.equities)

    @property
    def transactions(self) -> QuerySet['Transaction']:
        return Transaction.objects.filter(account=self)

    def trade_dates(self, equity) -> List[date]:
        return list(
            Transaction.objects.filter(account=self,
                                       equity=equity,
                                       xa_action__in=[Transaction.BUY, Transaction.REDIV, Transaction.SELL]).values_list(
                'date', flat=True).order_by('date'))

    def trade_details(self, equity, trade_date) -> [float, float]:
        result = self.transactions.filter(equity=equity, date=trade_date,
                                 xa_action__in=[Transaction.BUY, Transaction.REDIV, Transaction.SELL]).aggregate(Sum('quantity'),
                                                                                              Avg('price'))
        quantity = round(result['quantity__sum'], 2) if result['quantity__sum'] else 0
        price = round(result['price__avg'], 2) if result['price__avg'] else 0
        return quantity, price

    def update(self):
        """
        Ensure that each of my equities is updated
        :return:
        """
        for equity in self.equities:
            if equity.update():
                sleep(2)  # Any faster and my free API will fail

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

        self._cost = self.get_pattr('Funds')
        self._dividends = self.get_eattr('TotalDividends')
        self._value = self.get_eattr('Value')
        if len(self.p_pd) != 0:
            self._start = self.p_pd['Date'].min()
        elif len(self.e_pd) != 0:
            self._start = self.e_pd['Date'].min()
        self.save()

    def update_values(self, start: date = None, equity: Equity = None):
        """
        Update the summary values
        """
        acct_values = {}
        equity_values = {}
        for item in AccountSummary.objects.filter(account=self).order_by('date').values():
            acct_values[item[date]] = item
        for eq_item in AccountSummary.objects.filter(acct_summary_id=item['id']).order_by('date').values():
            pass


class Transaction(models.Model):
    """
    Track changes made to an equity on a account
    """

    FUND = 1
    BUY = 2
    REDIV = 3
    SELL = 4
    REDEEM = 5
    INTEREST = 6  # Used for anything that alters cash balance but is not tied an equity
    FEES = 7
    TRANS_IN = 8
    TRANS_OUT = 9

    SHARE_TRANSACTIONS = [BUY, REDIV, SELL, TRANS_IN, TRANS_OUT]
    MONEY_TRANSACTIONS = [FUND, REDEEM, INTEREST, FEES]
    def get_choices(self):
        choices = list()

        for choice in Equity.objects.all():
            name = f'{choice.key} - {choice.equity_type}'
            if choice.region:
                name = f'{name} ({Equity.region_lookup()[choice.region]})'
            choices.append((choice.id, name))
        return sorted(choices)

    TRANSACTION_TYPE = ((FUND, 'Fund'),
                        (BUY, 'Buy'),
                        (REDIV, 'Reinvested Dividend'),
                        (SELL, 'Sell'),
                        (INTEREST, 'Dividends/Interest'),
                        (REDEEM, 'Redeem'),
                        (FEES, 'Sold for Fees'),
                        (TRANS_IN, 'Transferred In'),
                        (TRANS_OUT, 'Transferred Out')
                        )

    TRANSACTION_MAP = dict(TRANSACTION_TYPE)

    account: Account = models.ForeignKey(Account, on_delete=models.CASCADE)
    equity: Equity = models.ForeignKey(Equity, null=True, blank=True, on_delete=models.CASCADE)

    real_date: date = models.DateField(verbose_name='Transaction Date', null=True)
    date: date = models.DateField(verbose_name='Normalized Date')
    price: float = models.FloatField()
    quantity: float = models.FloatField()
    value: float = models.FloatField(null=True, blank=True)
    currency_value: float = models.FloatField(null=True, blank=True)
    xa_action: int = models.IntegerField(help_text="Select a Account", choices=TRANSACTION_TYPE)
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    estimated = models.BooleanField(default=False)

    @classmethod
    def transaction_value(cls, xa_string: str) -> int:
        for key, value in cls.TRANSACTION_TYPE:
            if value == xa_string:
                return key
        raise AssertionError(f'Invalid transaction string: {xa_string}')

    @property
    def action_str(self):
        if self.xa_action in self.TRANSACTION_MAP:
            return self.TRANSACTION_MAP[self.xa_action]
        else:
            value = 'Unknown'
        return value

    def __str__(self):
        try:
            xa_str = self.TRANSACTION_MAP[self.xa_action]
        except KeyError:
            xa_str = 'DATA CORRUPTION'

        return f'{self.account}:{self.equity}:{self.date.strftime("%Y-%m-%d")}:{xa_str}: {self.price} {self.quantity} {self.value}'  # pragma: no cover

    @property
    def is_major(self) -> bool:
        if self.xa_action in [self.FUND, self.BUY, self.SELL, self.REDEEM, self.TRANS_IN, self.TRANS_OUT] or \
                (self.value and self.value > 100 and self.xa_action != self.REDIV):
            return True
        return False

    def save(self, *args, **kwargs):

        clear = True if 'standalone' in kwargs else False

        self.date = normalize_date(self.real_date) if self.real_date else None
        reported_price = 0 if not self.price else self.price

        if self.xa_action == self.REDIV:
            self.price = 0  # On Dividends
        else:
            self.price = abs(reported_price)

        if self.quantity:
            self.quantity = abs(self.quantity)
            if self.xa_action in [self.SELL, self.TRANS_OUT]:
                self.quantity = self.quantity * -1
        else:
            self.quantity = 0

        if not self.value:
            self.value = self.price * self.quantity

        self.value = abs(self.value)
        if self.xa_action in [self.SELL, self.TRANS_OUT]:
            self.value = self.value * -1

        if self.equity:
            cf = currency_factor(self.date, self.equity.currency, self.account.currency)
            self.currency_value = self.value * cf
        else:
            self.currency_value = self.value

        super(Transaction, self).save(*args, **kwargs)

        if self.price != 0 and self.equity and not self.equity.searchable:
            try:
                ev = EquityValue.objects.get(equity=self.equity, date=self.date)
                if ev.source > DataSource.UPLOAD.value:
                    ev.price = self.price
                    ev.real_date = self.real_date
                    ev.source = DataSource.UPLOAD.value
                    ev.save()
            except EquityValue.DoesNotExist:
                EquityValue.objects.create(source=DataSource.UPLOAD.value, equity=self.equity, price=self.price, real_date=self.real_date, date=self.date)

            for account in Account.objects.filter(id__in=Transaction.objects.filter(equity=self.equity).values_list('account', flat=True).distinct()):
                account.reset()

        self.account.reset()
