import logging
import pandas as pd
import requests

from datetime import datetime, timedelta, UTC, date
from dateutil.relativedelta import relativedelta

from decimal import Decimal, InvalidOperation
from phonenumber_field.modelfields import PhoneNumberField
from requests.exceptions import ConnectTimeout, ConnectionError
from requests.models import Response
from typing import Dict, Union
from tzlocal import get_localzone

from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError


from .utils import BoolReason
from .ioom_dates import IOOMDates

# We can not import CURRENCIES since it will be an import loop - from stocks.models import CURRENCIES
CURRENCIES = (
    ('CAD', 'Canadian Dollar'),
    ('USD', 'US Dollar')
)

logger = logging.getLogger(__name__)

COLORS = ['#FF6F61', '#6B8E23', '#4A90E2', '#F5A623', '#46f0f0', '#9013FE', '#E4C1D9', '#8B572A',
          '#FEC89A', '#F5E6CC', '#FFD8B1', '#B5EAD7', '#C3B1E1', '#FFF4B1', '#D4A5E6', '#CBE8F0', '#000075', '#808080', '#50E3C2',
          '#ffffff', '#000000']

PALETTE = {'green': '#2ECC71',
           'coral': '#FF6F61',
           'olive': '#6B8E23',
           'blue': '#4A90E2',
           'turquoise': '#50E3C2',
           'yellow': '#F5A623',
           'purple': '#9013FE',
           'rose': '#E4C1D9',
           'brown': '#8B572A',
           'orange': '#FEC89A',
           'cost': '#000000',
           'value': '#2ECC71',
           'dividends': '#4A90E2',
           }

# FF6F61 (Coral Red) and #6B8E23 (Olive Drab) are complementary because they are on opposite sides of the color wheel, creating a striking contrast.
# 4A90E2 (Sky Blue) and #F5A623 (Golden Yellow) provide a warm-cool color pairing, which is visually dynamic but not jarring.
# 50E3C2 (Turquoise) complements #9013FE (Purple), providing a balance of cool hues with a slight pop of vivid color.
# D0021B (Red) and #8B572A (Chestnut Brown) create a grounded, earthy combination that feels organic and balanced.

COUNTRIES = [('CA', 'Canada'),
             ('US', 'United States'),]


DIY_EPOCH = datetime(2014, 1, 1).date()  # Before this date.   I was too busy working


class DataSource(models.IntegerChoices):
    ADMIN = 10, "Admin"
    ADJUSTED = 20, "Adjusted"
    SYSTEM = 25, "Generated"
    API = 30, "API"
    RECONCILED = 35, "Reconciled"
    UPLOAD = 40, "Uploaded"
    IMPORT = 45, "Imported"
    USER = 50,  "Manual"
    ESTIMATE = 60, "Estimated"

    @classmethod
    def get_label(cls, value):
        try:
            return cls(value).label
        except ValueError:
            return 'Invalid DataSource'


class NormalizedDataManager(models.Manager):
    """
    Standard methods for NormalizedDataModel
    """
    def update_or_create(self, defaults=None, **kwargs):
        """
        Generic function for all date based classes.
        kwarg - by_month  - set to True will be stripped from kwargs and cause search only be year/month
        kwarg - type='month'  - same as by_month but will be kept in the search criteria
        kwarg - type='day' - search on year/month/day instead of datetime

        defaults + kwargs are the creation fields,  defaults are the update fields

        FOO.objects.update_or_create('date'=<some_date>, 'FOO_value'=<somevalue>, defaults={'FOO_value2':<x>, 'FOO_value3':<y>})
        """

        defaults = defaults or {}
        cls = self.model  # the concrete subclass

        if 'source' in kwargs:  # Do not search or source
            defaults['source'] = kwargs.pop('source')
        elif 'source' not in defaults:
            defaults['source'] = DataSource.ESTIMATE.value

        try:
            obj = self.get(**kwargs)
        except cls.DoesNotExist:
            # must create
            try:
                obj, created = super().update_or_create(defaults=defaults, **kwargs)
                return obj, created, "New instance has been created"
            except ValidationError as e:
                logger.error('Validation Error:%s:%s - %s' % (kwargs, defaults, e))
                return None, False, 'Validation Error:%s - %s' % (self, e)

        # we must have already existed
        if defaults['source'] < obj.source:
            return obj, False, f"Update ignored - Existing Data Source({obj.source}) is not more precise ({defaults['source']})"

        obj, created = super().update_or_create(defaults=defaults, **kwargs)
        return obj, created, '"Updated - Data Source is more precise"'


class NormalizedDataModel(models.Model):
    """
    Abstract class providing date, date and source.   Includes self.save() and cls.objects.update_or_create

    from django.db.models.functions import Cast
    from django.db.models.fields import DateField

    qs = MyModel.objects.annotate(date_only=Cast('created_at', DateField()))
    returning 1000 objects was 33 uS, vs 37 uS with Cast - This is good
    """

    date: date = models.DateField(null=False, blank=False)
    source: int = models.IntegerField(choices=DataSource.choices, default=DataSource.ESTIMATE)
    class Meta:
        abstract = True

    objects = NormalizedDataManager()

    @property
    def source_str(self):
        return DataSource(self.source).name.capitalize()

    def save(self, *args, **kwargs):
        preserve = kwargs.pop('preserve') if 'preserve' in kwargs else 'keep'

        if not preserve == 'off':
            normalized = IOOMDates.align_day(self.date, keep_month=(preserve == 'keep'))
            if normalized != self.date:
                try:
                    if normalized != self.date.date():
                        logger.info('Date %s has been realigned to %s' % (self.date, normalized))
                except:
                    pass
                self.date = normalized
        super().save(*args, **kwargs)

class ExchangeRate(NormalizedDataModel):
    """
        Store both the US to CAN and the CAN to US conversion rates for each month.   Always use the last
        value for the month.
    """

    us_to_can: float = models.DecimalField(max_digits=4, decimal_places=2)
    can_to_us: float = models.DecimalField(max_digits=4, decimal_places=2)

    # Class variables - a simple cache
    US_TO_CAN: Dict[datetime.date, Decimal] = {}
    CAN_TO_US: Dict[datetime.date, Decimal] = {}

    def __str__(self):  # pragma: no cover
        return f'{self.date}({DataSource(self.source).name}) US:{self.us_to_can} CAN:{self.can_to_us}'

    @classmethod
    def us_to_can_rate(cls, target_date) -> Decimal:
        if len(cls.US_TO_CAN) == 0:
            cls.US_TO_CAN = dict(ExchangeRate.objects.all().values_list('date', 'us_to_can'))
        try:
            return cls.US_TO_CAN[target_date]
        except KeyError:
            cls.US_TO_CAN[target_date] = Decimal(1.0)
        return Decimal(1.0)

    @classmethod
    def can_to_us_rate(cls, target_date) -> Decimal:
        if len(cls.CAN_TO_US) == 0:
            cls.CAN_TO_US = dict(ExchangeRate.objects.all().values_list('date', 'can_to_us'))
        try:
            return cls.CAN_TO_US[target_date]
        except KeyError:
            # logger.debug('CAN_TO_US - KeyError on date:%s' % target_date)
            cls.CAN_TO_US[target_date] = Decimal(1.0)
        return Decimal(1.0)

    @classmethod
    def _reset(cls):
        cls.CAN_TO_US = {}
        cls.US_TO_CAN = {}

    @classmethod
    def update(cls):
        """
        Update Exchange Rates,   since this is daily,  I will take the last rate of the month as the normalized
        value for the month
        """
        first_str = DIY_EPOCH.strftime('%Y-%m-%d')
        result = API.get('BOC', f'FXUSDCAD,FXCADUSD/json?start_date={first_str}&order_dir=desc')

        if not result.status_code == 200:  # pragma: no cover
            logger.error('BOC: failure: %s - %s' % (result.status_code, result.reason))
            return

        data = result.json()
        existing = {item['date']: item for item in ExchangeRate.objects.values('date', 'date', 'source')}
        month_date = can_rate = us_rate = None  # Cheat the scope, so I can use the variables outside my loop
        for record in range(len(data['observations'])):
            this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
            month_date = datetime(this_date.year, this_date.month, 1).date()
            if (month_date not in existing) or (existing[month_date]['date'] >= this_date):
                can_rate = data['observations'][record]['FXCADUSD']['v']
                us_rate = data['observations'][record]['FXUSDCAD']['v']
                ExchangeRate.objects.update_or_create(date=this_date, source=DataSource.API.value, defaults={'can_to_us': can_rate, 'us_to_can': us_rate})

        if month_date:  # Fill in future months
            month_date = month_date + relativedelta(months=1)
            while month_date <= datetime.now().date():  # Until we have better data, use that last
                ExchangeRate.objects.update_or_create(date=month_date, source=DataSource.ESTIMATE.value, defaults={'can_to_us': can_rate, 'us_to_can': us_rate})
                month_date = month_date + relativedelta(months=1)

        ExchangeRate._reset()  # Clear any cached values


class Inflation(NormalizedDataModel):
    """
    Class to capture a months worth of inflation.   BOC,  Bank of Canada's CPI (Consumer Price Index) is the data source.
    """

    cost = models.DecimalField(max_digits=6, decimal_places=2)       # CPI cost for month over month basket of goods
    inflation = models.DecimalField(max_digits=5, decimal_places=2)  # Based on last month's CPI

    def __str__(self):  # pragma: no cover
        return f'{self.date}({DataSource(self.source).name}) Cost:{self.cost} Inflation:{self.inflation}'

    @classmethod
    def update(cls):
        """
        Update Inflation values
        Since the current month(s) is not in the value we need to add it at the end
        """
        first: date = DIY_EPOCH
        first_str: str = first.strftime('%Y-%m-%d')

        result = API.get('BOC', f'STATIC_INFLATIONCALC/json?start_date={first_str}')
        if not result.status_code == 200:  # pragma: no cover
            logger.error('BOC failure: %s - %s' % (result.status_code, result.reason))
            return

        data = result.json()
        existing = {item['date']: item for item in cls.objects.values('date', 'date', 'source')}
        this_inflation = 0
        last_cost = this_cost = 0
        month_date = None
        for record in range(len(data['observations'])):
            this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
            month_date = datetime(this_date.year, this_date.month, 1).date()
            try:
                this_cost = Decimal(data['observations'][record]['STATIC_INFLATIONCALC']['v'])
            except InvalidOperation:  # pragma: no cover
                logger.error('Received invalid cost (%s) from BOC' % Decimal(data['observations'][record]['STATIC_INFLATIONCALC']['v']))
                pass  # Let this cost be the last cost if we ever get an error

            if last_cost:
                this_inflation = ((this_cost - last_cost) * 100) / last_cost
            else:
                try:
                    previous = Inflation.objects.get(date=this_date - relativedelta(months=1))
                    this_inflation = ((this_cost - previous.cost) * 100) / previous.cost
                except Inflation.DoesNotExist:  # pragma: no cover
                    pass

            if month_date not in existing or existing[month_date]['date'] >= this_date:
                Inflation.objects.update_or_create(date=this_date, source=DataSource.API.value,
                                                   defaults={'cost': this_cost, 'inflation': this_inflation})
                last_cost = this_cost

        if month_date:  # Fill in future months
            month_date = month_date + relativedelta(months=1)
            while month_date <= datetime.now().date():  # Until we have better data, use that last
                Inflation.objects.update_or_create(date=month_date, source=DataSource.ESTIMATE.value,
                                                   defaults={'cost': this_cost, 'inflation': this_inflation})
                month_date = month_date + relativedelta(months=1)

    @classmethod
    def inflated(cls, value: Decimal, from_date: date, to_date: date) -> Decimal:
        """
        calculate the cost based on inflation of value,  between date and date,
        """
        try:
            from_value = Inflation.objects.get(date=from_date.replace(day=1)).cost
        except Inflation.DoesNotExist:
            return value

        try:
            to_value = Inflation.objects.get(date=to_date.replace(day=1)).cost
        except Inflation.DoesNotExist:
            return value

        return value + value * (to_value - from_value) / from_value

    @classmethod
    def as_dataframe(cls, df: pd.DataFrame = pd.DataFrame(), scope: str = 'month') -> pd.DataFrame:

        #1 Get the raw data
        query = cls.objects.all()
        if not df.empty:
            query = query.filter(date__gte=df['Date'].min(), date__lte=df['Date'].max())

        idf = pd.DataFrame(list(query.values('date', 'cost')))
        idf['Date'] = pd.to_datetime(idf['date'])
        idf['CPICost'] = idf["cost"].astype("float64")
        idf = idf.drop(columns=['date', 'cost'])

        if scope == 'month':
            idf = idf.groupby(pd.Grouper(key="Date", freq="ME")).agg({'CPICost': 'last'}).reset_index()
            idf["Date"] = idf["Date"].values.astype("datetime64[M]")  # Normalize date to the 1st

        if df.empty:
            if scope == 'month':
                df = IOOMDates(build=True, start=idf['Date'].min()).months_df
            else:
                df = IOOMDates(force=True, build=True, start=idf['Date'].min()).days_df

        df = df[['Date']].merge(idf, on='Date', how='left')

        df['CPICost'] = df['CPICost'].transform(
            lambda s: s.interpolate()
        )
        df['CPICost'] = df['CPICost'].bfill()  # Required since CPI data is monthly and we may not have a day before
        return df

class Profile(models.Model):
    user: User = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = PhoneNumberField(blank=True, null=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='CAD')
    address1 = models.CharField(max_length=100, blank=True, null=True)
    address2 = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=2, blank=True, null=True)
    state = models.CharField(max_length=2, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    av_api_key = models.CharField(max_length=24, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.user.username


class API(models.Model):
    """
    Support making an API offline and catch some traps and return a valid / invalid response
    """
    DEFAULT_FAIL_LENGTH: int = 60 * 60 * 3  # 3 Hours
    name = models.CharField(primary_key=True, null=False, blank=False, max_length=32)
    base = models.CharField(null=True, blank=True, max_length=132)
    fail_reason = models.CharField(null=False, blank=False, max_length=132, default='Manual Suspension')  # Via the admin tool
    fail_length: int = models.IntegerField(null=True, blank=True, default=DEFAULT_FAIL_LENGTH)  # Increase via admin tool if so desired
    _active = models.BooleanField(default=True)
    _last_fail: date = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls, name, extra=None):   # return a get.result or None
        try:
            url = cls.objects.get(name=name)
            test = url.ready_or_reset()
            if test:
                try:
                    return requests.get(url.base + extra)
                except ConnectTimeout:
                    reason = 'Connection Timeout'
                except ConnectionError:
                    reason = 'Connection Error'
                cls.pause(name, reason)
            else:
                reason = str(test)
        except API.DoesNotExist:
            reason = 'Configuration Error'
        # API did not work,  return an error
        result = Response()
        result.status_code = 500
        result.reason = reason
        return result

    @property
    def is_active(self):
        return self._active

    @property
    def last_fail(self):
        return DIY_EPOCH if not self._last_fail else self._last_fail

    @classmethod
    def pause(cls, name, reason='Undefined'):
        try:
            url = cls.objects.get(name=name)
            if url._active:
                url._active = False
                url._last_fail = datetime.now()
                url.fail_length = cls.DEFAULT_FAIL_LENGTH
                url.fail_reason = reason
                url.save()
        except cls.DoesNotExist:
            logger.warning('Trying to pause invalid url named:' % name)

    def ready_or_reset(self):
        if self.is_active:
            return BoolReason(True, 'API is Active')
        if self.last_fail < datetime.now(UTC) - timedelta(seconds=self.fail_length):
            self._active = True
            self.save()
            return BoolReason(True, 'API has been reset')

        return BoolReason(False, f'API is inactive since {self._last_fail.astimezone(get_localzone())}')

    @classmethod
    def status(cls, name):
        try:
            api = cls.objects.get(name=name)
            return api.ready_or_reset()
        except cls.DoesNotExist:
            return BoolReason(False, 'Configuration Error')
