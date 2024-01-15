import logging
import pandas as pd
import requests

from django.urls import reverse
from django.db import models
from django.db.models import QuerySet, F, Value, Sum, Avg
from django.utils.functional import cached_property

from diy.settings import ALPHAVANTAGEAPI_KEY as AV_API_KEY
from typing import List, Dict
from datetime import datetime, date
from time import sleep
from pandas import DataFrame

from stocks.utils import normalize_date, normalize_today, next_date, last_date

logger = logging.getLogger(__name__)
CURRENCIES = (('CAD', 'Canadian Dollar'), ('USD', 'US Dollar'))

epoch = datetime(2014, 1, 1).date()  # Before this date.   I was too busy working
av_url = 'https://www.alphavantage.co/query?function='
boc_url = 'https://www.bankofcanada.ca/valet/observations/'
av_regions = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
    
Bank of Canada
imp
https://www.bankofcanada.ca/valet/observations/STATIC_INFLATIONCALC/json?recent_months=96&order_dir=asc
   - above to calculate inflatin
'''

my_currency = 'CAD'  # Should be set via a user profile
EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value','TotalDividends', 'EffectiveCost', 'InflatedCost']
PortfolioColumns = ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost', 'Cash']


class ExchangeRate(models.Model):
    '''
    The API returns Daily,  too much detail for me.
    '''
    date: date = models.DateField()
    us_to_can: float = models.FloatField()
    can_to_us: float = models.FloatField()

    US_TO_CAN: Dict[datetime.date, float] = {}
    CAN_TO_US: Dict[datetime.date, float] = {}

    def __str__(self):
        return f'{self.date} US:{self.us_to_can} CAN:{self.can_to_us}'

    @classmethod
    def us_to_can_rate(cls, target_date, reset=False) -> float:
        if reset:
            cls.US_TO_CAN = {}
        if len(cls.US_TO_CAN) == 0:
            logger.debug('Fetching exchange rates for us_to_can')
            cls.US_TO_CAN = dict(ExchangeRate.objects.all().values_list('date', 'us_to_can'))
        try:
            return cls.US_TO_CAN[target_date]
        except KeyError:
            logger.debug('US_TO_CAN - Error on date:%s' % target_date)
            return 1

    @classmethod
    def can_to_us_rate(cls, target_date, reset=False) -> float:
        if reset:
            cls.CAN_TO_US = {}
        if len(cls.CAN_TO_US) == 0:
            logger.debug('Fetching exchange rates for us_to_can')
            cls.CAN_TO_US = dict(ExchangeRate.objects.all().values_list('date', 'can_to_us'))
        try:
            return cls.CAN_TO_US[target_date]
        except KeyError:
            logger.debug('CAN_TO_US - Error on date:%s' % target_date)
            return 1

    @classmethod
    def update(cls, force: bool = False):
        """
        Update Exchange Rates,   since this is daily,  I will take the first rate of the month as the normalized
        value for the last month
        """
        first = EquityValue.objects.all().order_by('date')[0].date
        first_str = first.strftime('%Y-%m-%d')

        url = f'{boc_url}FXUSDCAD,FXCADUSD/json?start_date={first_str}&order_dir=asc'
        result = requests.get(url)
        if not result.status_code == 200:
            logger.error('BOC %s failure: %s - %s' % (url, result.status_code, result.reason))
        else:
            data = result.json()
            previous_date: date = None
            for record in range(len(data['observations'])):
                this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
                if previous_date and previous_date.month != this_date.month:
                    can_rate = data['observations'][record]['FXCADUSD']['v']
                    us_rate = data['observations'][record]['FXUSDCAD']['v']
                    record_date = datetime(this_date.year, this_date.month, 1).date()
                    if not ExchangeRate.objects.filter(date=record_date, can_to_us=can_rate, us_to_can=us_rate).exists():
                        try:
                            this_record = ExchangeRate.objects.get(date=record_date)
                        except ExchangeRate.DoesNotExist:
                            this_record = ExchangeRate(date=record_date)
                        this_record.can_to_us = can_rate
                        this_record.us_to_can = us_rate
                        this_record.save()
                previous_date = this_date
            # Well since we have been normailizing dates to the end of the month,  but with exchange rates it is to the
            # start of the month,  we need to add a value for today (which is next month really...)
            last = data['observations'][len(data['observations']) - 1]
            ExchangeRate.objects.create(date=normalize_today(),
                                        can_to_us=last['FXCADUSD']['v'],
                                        us_to_can=last['FXUSDCAD']['v'])


class Inflation(models.Model):
    """
    Class to capture a months worth of inflation
    """
    date = models.DateField()
    cost = models.FloatField()
    inflation = models.FloatField()
    estimated = models.BooleanField(default=True)


    def __str__(self):
        return f'{self.date} {self.inflation}'

    @classmethod
    def update(cls, force: bool = False):
        """
        Update Inflation values
        """
        first = Transaction.objects.all().order_by('date')[0].date
        first = first
        first_str = first.strftime('%Y-%m-%d')
        url = f'{boc_url}STATIC_INFLATIONCALC/json?start_date={first_str}'
        result = requests.get(url)
        if not result.status_code == 200:
            logger.error('BOC %s failure: %s - %s' % (url, result.status_code, result.reason))
        else:
            # Pass 1 - Get all the inflation CPI values
            data = result.json()
            for record in range(len(data['observations'])):
                this_date = datetime.strptime(data['observations'][record]['d'], '%Y-%m-%d').date()
                if not Inflation.objects.filter(date=this_date, estimated=False).exists():
                    Inflation.objects.create(date=this_date,
                                             cost=data['observations'][record]['STATIC_INFLATIONCALC']['v'],
                                             inflation=0,
                                             estimated=False)

            # Pass 2 - Calculate monthly inflation rates
            last_date = last_cost = last_inflation = None
            for record in Inflation.objects.filter(estimated=False).order_by('date'):
                if last_date:
                    last_inflation = ((record.cost - last_cost) * 100) / last_cost
                    if record.inflation != last_inflation:
                        record.inflation = last_inflation
                        record.save()
                last_date = record.date
                last_cost = record.cost
            # Pass three make sure we have values until the current normalized date.
            this_date = normalize_today()
            last_date = next_date(last_date)
            while last_date <= this_date:
                try:
                    record = Inflation.objects.get(date=last_date)
                except Inflation.DoesNotExist:
                    record = Inflation(date=last_date)
                record.estimated = True
                record.cost = last_cost
                record.inflation = last_inflation
                record.save()
                last_date = next_date(last_date)


class Equity(models.Model):

    EQUITY_TYPES = (
        ('Equity', 'Equity/Stock'),
        ('ETF', 'Exchange Traded Fund'),
        ('MF', 'Mutual Fund'),
        ('MM', 'Money Market')
    )
    REGIONS = (('TRT', 'Toronto'), ('', 'United States'))

    @classmethod
    def region_lookup(cls):
        result = {}
        for region in cls.REGIONS:
            result[region[0]] = region[1]
        return result

    symbol: str = models.CharField(max_length=32, verbose_name='Trading symbol')  # Symbol
    name: str = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    equity_type: str = models.CharField(max_length=10, blank=True, null=True, choices=EQUITY_TYPES)
    region: str = models.CharField(max_length=10, null=False, blank=False, choices=REGIONS, default='TRT')
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='CAD')
    last_updated: date = models.DateField(blank=True, null=True)
    searchable: bool = models.BooleanField(default=True)  # Set to False, when this is data that was forced into being
    validated: bool = models.BooleanField(default=False)  # Set to True was validation is done

    @property
    def key(self):
        return self.symbol

    def __str__(self):
        return self.symbol

    def save(self, *args, **kwargs):
        if 'update' in kwargs:
            do_update = kwargs.pop('update')
        else:
            do_update = True

        self.symbol = self.symbol.upper()
        if self._state.adding and do_update:
            if not self.validated:
                self.searchable = self.set_equity_data(self.symbol)
            self.validated = True

        if do_update and self.searchable:
            self.update()
        super(Equity, self).save(*args, **kwargs)

    @staticmethod
    def lookup(key: str) -> List[Dict]:
        """
        Given a key,   use the API to find the best stock matches.   Not used but should be
        :param key:  The search key string
        :return:  A list of dictionary values (top 10) that match - The API is lacking it would be great if it
                  supported wild cards (request was sent)
        """
        search = av_url + 'SYMBOL_SEARCH&keywords=' + key + '&apikey=' + AV_API_KEY
        data = requests.get(search).json()
        logger.debug(search)
        if 'bestMatches' in data:
            return data['bestMatches']
        return []

    @staticmethod
    def get_equity_data(ticker: str) -> Dict:
        ticker_set = Equity.lookup(ticker)
        if ticker_set:
            if not len(ticker_set) == 1:
                if not ticker_set[0]['9. matchScore'] == '1.0000':
                    return {}
            return ticker_set[0]
        return {}

    def set_equity_data(self, ticker: str) -> bool:
        validated = self.get_equity_data(ticker)
        if validated:
            self.name = validated['2. name']
            self.equity_type = validated['3. type']
            for region in self.REGIONS:
                if validated['4. region'] == region[1]:
                    self.region = region[0]
                    break
            self.currency = validated['8. currency']
            return True
        return False

    def fill_equity_holes(self):
        last_date: date = None
        last_price: float = 0  # just to stop the warnings,  it can't actually be used before its referenced
        date_values: dict[date, float] = dict(
            EquityValue.objects.filter(equity=self).values_list('date', 'price').order_by('date'))
        for value in date_values:
            if last_date and not value == next_date(last_date):  # We have a hole
                months = (value.year - last_date.year) * 12 + value.month - last_date.month
                change_increment = (date_values[value] - last_price) / months
                for _ in range(months):
                    next_month = next_date(last_date)
                    last_price = last_price + change_increment
                    if not EquityValue.objects.filter(equity=self, date=next_month).exists():
                        EquityValue.objects.get_or_create(equity=self, date=next_month,
                                                          price=last_price, estimated=True)
                    last_date = next_month

            last_date = value
            last_price = date_values[value]
        try:

            last_entry = EquityValue.objects.filter(equity=self).order_by('-date')[0]
            current_date = normalize_today()
            date_value = next_date(last_entry.date)
            if not date_value >= current_date:
                price_value = last_entry.price
                while date_value <= current_date:
                    EquityValue.objects.create(equity=self, date=date_value, price=price_value, estimated=True)
                    date_value = next_date(date_value)
        except IndexError:
            logger.error('No EquityValue data for:%s' % self)

    def _update_validate(self):
        self.save(update=False)
        self.searchable = self.set_equity_data(self.symbol)
        self.validated = True
        self.save(update=False)

    def _update_equity_data(self, force):
        now = datetime.now().date()
        if now == self.last_updated and not force:
            logger.info('%s - Already updated %s' % (self, now))
        else:
            url = f'{av_url}TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.symbol}&apikey={AV_API_KEY}'
            data_key = 'Monthly Adjusted Time Series'
            this_day = normalize_date(datetime.now())
            logger.debug(url)
            result = requests.get(url)
            if not result.status_code == 200:
                logger.warning('%s Result is %s - %s' % (url, result.status_code, result.reason))
                return

            data = result.json()
            if data_key in data:
                for entry in data[data_key]:
                    try:
                        date_value = normalize_date(datetime.strptime(entry, '%Y-%m-%d'))
                    except ValueError:
                        logger.error('Invalid date format in: %s' % entry)
                        return

                    if date_value >= epoch:
                        if date_value == this_day or not EquityValue.objects.filter(equity=self,
                                                                                    estimated=False,
                                                                                    date=date_value).exists():
                            try:
                                ev_record = EquityValue.objects.get(equity=self, date=date_value)
                            except EquityValue.DoesNotExist:
                                ev_record = EquityValue(equity=self, date=date_value)
                            ev_record.estimated = False
                            ev_record.price = float(data[data_key][entry]['4. close'])
                            ev_record.save()
                            dividend = float(data[data_key][entry]['7. dividend amount'])
                            if dividend != 0 and not EquityEvent.objects.filter(equity=self,
                                                                                event_type='Dividend',
                                                                                date=date_value).exists():
                                EquityEvent.objects.create(equity=self, event_type='Dividend',
                                                           date=date_value, value=dividend, event_source='api')

            self.last_updated = now
            self.save(update=False)

    def update(self, force: bool = False) -> bool:
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month).
        """
        logger.warning('Updating %s' % self)
        if not self.validated:
            self._update_validate()

        if self.searchable:
            # Get rid of any uploaded dividend data,  it may be duplicated based on off month processing
            try:
                EquityEvent.objects.filter(equity=self, event_source='upload', event_type='Dividend').delete()
                EquityValue.objects.filter(equity=self, estimated=True).delete()
            except ValueError:
                pass
            self._update_equity_data(force)

        self.fill_equity_holes()
        return True


class EquityAlias(models.Model):
    '''
    This is needed to support the various imports.
    Example when manulife XLU trust reports dividends under symbol S007135.    The only way I can find that is to
    match on the name 'SELECT SECTOR SPDR TRUST THE UTILITIES SELECT SECTOR SPDR TRUST W...'
    which I match the divided to name 'SELECT SECTOR SPDR TRUST THE UTILITIES SELECT SECTOR SPDR TRUST C...

    when I first find XLU in a manulife import,  I will make an alias record using the name we import as'
    I can later match the dividend (and create an alias) for that two.
    '''
    symbol = models.TextField()
    name = models.TextField()
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.symbol} : {self.equity.symbol} - {self.name}'

    @staticmethod
    def find_equity(description: str) -> [Equity | None]:
        score: int = 0
        matched: bool = False
        match: EquityAlias | None = None
        for alias in EquityAlias.objects.all():
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
        return None


class EquityValue(models.Model):
    """
    Track an equities value
    """
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date: date = models.DateField()
    price: float = models.FloatField()
    estimated: bool = models.BooleanField(default=False)

    def __str__(self):
        output = f'{self.equity} - {self.date}: {self.price}'
        if self.estimated:
            output = f'{output} ?'
        return output

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super(EquityValue, self).save(*args, **kwargs)


class EquityEvent(models.Model):
    """
    Track an equities dividends
    """
    EVENT_TYPES = (('Dividend', 'Dividend'),  # Automatically created as part of 'Update' action
                   ('SplitAD', 'Stock Split with Adjusted Dividends'),  # Historic dividends adjusted
                   ('Split', 'Stock Split'))
    EVENT_SOURCE = (('manual', 'Manual'), ('api', 'API'), ('upload', 'Upload'))

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date: date = models.DateField()
    value = models.FloatField()
    event_type = models.TextField(max_length=10, choices=EVENT_TYPES)
    event_source = models.TextField(max_length=6, choices=EVENT_SOURCE)

    def __str__(self):
        return f'{self.equity} - {self.date}: {self.value} {self.event_type} {self.event_source}'

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        if not self.event_source:
            self.event_source = 'manual'
        super(EquityEvent, self).save(*args, **kwargs)
        if self.event_type == 'SplitAD':
            logger.info('Adjusting Dividends for %s' % self.equity)
            for event in EquityEvent.objects.filter(equity=self.equity, event_type='Dividend', date__lt=self.date):
                event.value = event.value * self.value
                event.save()
        if self.event_type.startswith('Split'):
            logger.info('Adjusting Shares for %' % self.equity)
            for transaction in Transaction.objects.filter(equity=self.equity, date__lt=self.date):
                Transaction.objects.create(portfolio=transaction.portfolio,
                                           equity=self.equity, price=0,
                                           quantity=transaction.quantity, xa_action=Transaction.BUY, date=self.date)


class PortfolioSummary:

    def __init__(self, name: str, xas: QuerySet, equity_pd: pd, currency: str, managed: bool = False):
        self.name = name
        self.xas = xas
        self.epd = equity_pd
        self.currency = currency

    def currency_factor(self, exchange_date: date, input_currency: str) -> float:
        """
        :param exchange_date:
        :param input_currency:
        :return:
        """
        if not input_currency == self.currency:
            if input_currency == 'USD':
                return ExchangeRate.us_to_can_rate(exchange_date)
            elif input_currency == 'CAD':
                return ExchangeRate.can_to_us_rate(exchange_date)
            else:
                raise Exception(f'Unexpected input_currency {input_currency}')
        return 1

    @property
    def pd(self) -> DataFrame:
        now = datetime.now()
        monthly_inflation: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))
        this_date = self.xas.order_by('date')[0].date
        final_date = normalize_today()
        new = pd.DataFrame(columns=PortfolioColumns)

        """
        funding = list(self.xas.filter(xa_action__in=[Transaction.FUND, Transaction.REDEEM]).
                       values_list('date', flat=True).distinct())
        sales = list(self.xas.filter(xa_action__in=[Transaction.BUY, Transaction.SELL]).
                     values_list('date', flat=True).distinct())
        """

        xa_dates = list(self.xas.values_list('date', flat=True).distinct())
        effective_cost = inflated_cost = cash = 0
        while this_date <= final_date:
            if this_date in xa_dates:
                this_funding = self.xas.filter(xa_action__in=[Transaction.FUND, Transaction.REDEEM], date=this_date).\
                    aggregate(Sum('value'))['value__sum']
                if this_funding:
                    effective_cost += this_funding
                    inflated_cost += this_funding
                    cash += this_funding
                    logger.debug('%s:Change: Cost:%s ConvCost:%s Cash:%s Value:%s' % (
                        this_date, this_funding, this_funding, cash,
                        self.epd.loc[self.epd['Date'] == this_date]['Value'].sum()))

                for equity_id in (self.xas.filter(date=this_date).exclude(equity__isnull=True).values_list(
                        'equity', flat=True).distinct()):

                    e: Equity = Equity.objects.get(id=equity_id)
                    cf = self.currency_factor(this_date, e.currency)
                    
                    xa_costs = self.xas.filter(xa_action__in=[Transaction.BUY, Transaction.SELL],
                                               date=this_date, equity=e).aggregate(Sum('value'))['value__sum']
                    converted_cost = xa_costs * cf
                    if xa_costs:  # for debug else next line
                        cash -= xa_costs * cf  # for debug else next line
                    # cash -= xa_costs * cf if xa_costs else 0
                        logger.debug('%s:Trade: Cost:%s ConvCost:%s Cash:%s Value:%s Equity:%s' % (
                            this_date, xa_costs, converted_cost, cash,
                            self.epd.loc[self.epd['Date'] == this_date]['Value'].sum(), e.symbol))

                    interest = self.xas.filter(xa_action=Transaction.INTEREST,
                                               date=this_date).aggregate(Sum('value'))['value__sum']

                    cash += interest * cf if interest else 0

                    reinvest = self.xas.filter(xa_action__in=[Transaction.DIV], equity=e, date=this_date). \
                        aggregate(Sum('value'))['value__sum']
    
                    if reinvest:
                        effective_cost += reinvest * cf   # Will reduce the effective cost
                        inflated_cost += reinvest * cf  # Will reduce the inflated cost
                        logger.debug('%s:REInvest: Cost:%s ConvCost:%s Cash:%s Value:%s' % (
                            this_date, 0, 0, cash,
                            self.epd.loc[self.epd['Date'] == this_date]['Value'].sum()))


            dividends = self.epd.loc[self.epd['Date'] == this_date]['Dividend'].sum()
            if dividends:
                cash += dividends
                logger.debug('%s:Dividends: Cost:%s ConvCost:%s Cash:%s Value:%s' % (
                    this_date, dividends, dividends, cash,
                    self.epd.loc[self.epd['Date'] == this_date]['Value'].sum()))

            new.loc[len(new.index)] = [this_date, effective_cost,
                                       self.epd.loc[self.epd['Date'] == this_date]['Value'].sum(),
                                       self.epd.loc[self.epd['Date'] == this_date]['TotalDividends'].sum(),
                                       inflated_cost, cash]
            if this_date in monthly_inflation:  # Edge case incase inflation tables were not updated
                inflated_cost += monthly_inflation[this_date] / 100 * inflated_cost
            this_date = next_date(this_date)
        logger.debug('Created Portfolio DataFrame for %s in %s' % (self.name, (datetime.now() - now).seconds))

        return new


class PortfolioEquitySummary:
    """
    Non-DB class that will calculate the historic information regarding equities in a  portfolio.    We purposefully do
    not reference raw portfolio or transaction data.   This is done so that we can compare / create speculative data
    """

    def __init__(self, name: str, xas: QuerySet, currency: str, managed: bool = False, fakequity: Equity = None):
        self.name = name
        self.xas = xas
        self.currency = currency
        self.managed = managed  # We do not extract dividends
        self.fakequity = fakequity
        self.inflation_rates: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))

    def currency_factor(self, exchange_date: date, input_currency: str) -> float:
        """
        :param exchange_date:
        :param input_currency:
        :return:
        """
        if not input_currency == self.currency:
            if input_currency == 'USD':
                return ExchangeRate.us_to_can_rate(exchange_date)
            elif input_currency == 'CAD':
                return ExchangeRate.can_to_us_rate(exchange_date)
            else:
                raise Exception(f'Unexpected input_currency {input_currency}')
        return 1

    def process_equity(self, eq: Equity, df: DataFrame) -> DataFrame:
        dividends: Dict[date, float]
        value: EquityValue
        trades = self.xas.filter(equity=eq, xa_action__in=[Transaction.BUY, Transaction.DIV, Transaction.SELL])
        if len(trades) == 0:
            logger.warning('Transaction set %s:  No Trades in transaction data' % eq)
            return df

        search_equity = self.fakequity if self.fakequity else eq
        xa_dates = list(trades.order_by('date').values_list('date', flat=True))
        first = xa_dates[0]

        equity_values = EquityValue.objects.filter(date__gte=first,
                                                   equity=search_equity).order_by('date')
        dividends = dict(EquityEvent.objects.filter(date__gte=first,
                                                     equity=search_equity,
                                                     event_type='Dividend').values_list('date','value'))

        shares = effective_cost = total_dividends = inflation = 0
        for value in equity_values:  # This is over every month you owned this equity.
            cf = self.currency_factor(value.date, search_equity.currency)
            dividend = dividends[value.date] * cf if value.date in dividends else 0
            change_cost: float = 0
            if value.date in xa_dates:  # We did something on this normalized day
                change = trades.filter(date=value.date).aggregate(Sum('quantity'), Sum('value'))
                if change['quantity__sum']:  # Off chance, we bought and sold on the same normalised day
                    trade_value = change['value__sum'] * cf
                    if trade_value == 0:  # Gifted some shares (split or dividends)
                        if not self.fakequity:
                            shares += change['quantity__sum']
                        else:
                            if self.managed:
                                shares += trade_value / value.price
                    else:
                        change_cost = change['value__sum'] * cf if change['value__sum'] else 0
                        shares += trade_value / value.price if self.fakequity else change['quantity__sum']
                    effective_cost += change_cost

            if effective_cost < 0:
                effective_cost = 0

            inflation += (inflation * self.inflation_rates[value.date] / 100) + change_cost

            this_dividend = shares * dividend if not self.managed else 0
            total_dividends += this_dividend
            this_value = value.price * shares

            df.loc[len(df.index)] = [value.date, search_equity.symbol, shares, this_dividend,
                                               value.price * cf,
                                               this_value, total_dividends, effective_cost, inflation]
        return df

    @cached_property
    def pd(self) -> pd:
        '''
        Historic data for each equity in a portfolio
        :return:  panda.Dataframe
        '''
        now = datetime.now()
        new = pd.DataFrame(columns=EquityColumns)
        inflation_rates: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))
        try:
            portfolio_start = self.xas.order_by('date')[0].date
        except IndexError:
            return new

        for equity in Equity.objects.filter(transaction__in=self.xas).distinct():
            self.process_equity(equity, new)
        logger.warning('Created Equity DataFrame for %s in %s' % (self.name, (datetime.now() - now).seconds))
        return new

    def fetch(self, fetch_date: date, symbol: str | Equity = None, data: str = None) -> float:
        """
        A flexible way to extract data from an Equity DataFrame
        :param fetch_date:
        :param symbol:
        :param data:
        :return:
        """

        if symbol and isinstance(symbol, Equity):
            symbol = symbol.symbol


        v = self.pd.loc[(self.pd['Date'] == fetch_date) & (df['Equity'] == symbol)]['Value']
        return 0


class Portfolio(models.Model):
    """
    Name - Will need to be unique based on future user attribute
    Explicit Name - Used for importing,  This allows to rename (of name) without losing source
    Currency - Base currency of the portfolio,  can be CAN or USD

    """

    name: str = models.CharField(max_length=128, unique=True, primary_key=False,
                                 help_text='Enter a unique name for this portfolio')

    explicit_name: str = models.CharField(max_length=128, null=True, blank=True, unique=True,
                                          help_text='The name as imported')
    managed: bool = models.BooleanField(default=True)
    currency: str = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='CAD')

    # These Values are updated to allow for a quick loading of portfolio_list
    cost: int = models.IntegerField(null=True, blank=True)  # Effective cost of all shares ever purchased
    value: int = models.IntegerField(null=True, blank=True)  # of shares owned as of today
    dividends: int = models.IntegerField(null=True, blank=True)  # Total dividends ever received
    start: date = models.DateField(null=True, blank=True)
    end: date = models.DateField(null=True, blank=True, help_text='Date this portfolio was Closed')
    last_import: date = models.DateField(null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super(Portfolio, self).__init__(*args, **kwargs)
        self._last_import = self.last_import

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.explicit_name:
            self.explicit_name = self.name
        super(Portfolio, self).save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.pk})

    @cached_property
    def e_pd(self) -> DataFrame:
        # self.pd.loc[self.pd['Date'] == normalize_today()].sort_values(['Equity'])
        return PortfolioEquitySummary(str(self.name), self.transactions, self.currency, managed=self.managed).pd

    @cached_property
    def p_pd(self) -> DataFrame:
        '''
        Regardless of the equities,  how is the portfolio doing based on money in,  money out
        :return:
        '''
        return PortfolioSummary(str(self.name), self.transactions,  self.e_pd, self.currency,  managed=self.managed).pd

    def switch(self, new_equity: Equity) -> DataFrame:
        return PortfolioEquitySummary(str(self.name),
                                      self.transactions,
                                      self.currency,
                                      managed=self.managed,
                                      fakequity=new_equity).pd

    @property
    def equities(self) -> QuerySet[Equity]:
        return Equity.objects.filter(symbol__in=Transaction.objects.filter(portfolio=self).values('equity__symbol')).order_by('symbol')

    @property
    def equity_keys(self):
        return sorted(self.e_pd['Equity'].unique())

    @property
    def transactions(self) -> QuerySet['Transaction']:
        """
        Cache and return a
        'equity1' : [xa1, xa2,...],
        'equity2' : [xa1,]
        :return:
        """
        return Transaction.objects.filter(portfolio=self)

    def trade_dates(self, equity_key) -> List[date]:
        return list(
            Transaction.objects.filter(portfolio=self,
                                       equity__symbol=equity_key,
                                       xa_action__in=[Transaction.BUY, Transaction.SELL]).values_list(
                'date', flat=True).order_by('date'))

    def trade_details(self, equity, trade_date) -> [float, float]:
        result = self.transactions.filter(equity=equity, date=trade_date,
                                 xa_action__in=[Transaction.BUY, Transaction.SELL]).aggregate(Sum('quantity'),
                                                                                              Avg('price'))
        quantity = round(result['quantity__sum'], 2) if result['quantity__sum'] else 0
        price = round(result['price__avg'], 2) if result['price__avg'] else 0
        return quantity, price

    @property
    def growth(self) -> int:
        if self.value and self.cost:
            return self.value - self.cost
        else:
            return 0

    @property
    def total(self) -> int:
        if self.growth and self.dividends:
            return self.growth + self.dividends
        else:
            return 0

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
        this_day = normalize_today()
        current = self.p_pd.loc[self.p_pd['Date'] == this_day]
        self.cost = current['EffectiveCost'].item()
        self.dividends = current['TotalDividends'].item()
        self.value = current['Value'].item() + current['Cash'].item()
        self.start = self.p_pd['Date'].min()
        end_series = self.p_pd.loc[(self.p_pd['Value'] <= 0) & (self.p_pd['Date'] > self.start)]
        '''if len(end_series) != 0:
            end_date = end_series.min()
            if end_date != this_day:
                self.end_date = end_date'''
        self.save()


class Transaction(models.Model):
    """
    Track changes made to an equity on a portfolio
    """
    FUND = 1
    BUY = 2
    DIV = 3
    SELL = 4
    REDEEM = 5
    INTEREST = 6

    @staticmethod
    def equity_choice_list():
        choices = list()

        for choice in Equity.objects.all():
            name = f'{choice.key} - {choice.equity_type}'
            if choice.region:
                name = f'{name} ({Equity.region_lookup()[choice.region]})'
            choices.append((choice.id, name))
        return sorted(choices)

    TRANSACTION_TYPE = ((FUND, 'Fund'),
                        (BUY, 'Buy'),
                        (DIV, 'Reinvested Dividend'),
                        (SELL, 'Sell'),
                        (INTEREST, 'Interest'),
                        (REDEEM, 'Redeem'),
                        )
    TRANSACTION_MAP = dict(TRANSACTION_TYPE)

    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    equity = models.ForeignKey(Equity, null=True, blank=True, on_delete=models.CASCADE)

    date: date = models.DateField()
    price: float = models.FloatField()
    quantity: float = models.FloatField()
    value: float = models.FloatField(null=True, blank=True)
    xa_action: int = models.IntegerField(choices=TRANSACTION_TYPE)

    @classmethod
    def transaction_value(cls, xa_string: str) -> int:
        for key, value in cls.TRANSACTION_TYPE:
            if value == xa_string:
                return key
        raise AssertionError(f'Invalid transaction string: {xa_string}')

    def __str__(self):
        return (f'{self.portfolio}:{self.equity}:{self.date}:{self.price} {self.quantity} {self.value} '
                f'{self.TRANSACTION_MAP[self.xa_action]}')

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        if not self.value:
            self.value = self.price * self.quantity
        super(Transaction, self).save(*args, **kwargs)
