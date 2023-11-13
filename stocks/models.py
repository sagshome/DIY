import platform
import requests
import tempfile
from django.urls import reverse

from django.db import models
from django.utils.functional import cached_property

from diy.settings import ALPHAVANTAGEAPI_KEY as AV_API_KEY
from typing import List, Dict
from pathlib import Path


from datetime import datetime, date
from functools import cache
from time import sleep

epoch = datetime(2018, 1, 1).date()  # I don't care about anything before this date.   I was too busy working
av_url = 'https://www.alphavantage.co/query?function='
av_regions = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
'''


def normalize_date(this_date) -> datetime.date:
    """
    Make every date the start of the next month.    The alpahvantage website is based on the last trading day each month
    :param this_date:  The date to normalize
    :return:  The 1st of the next month (and year if December)
    """
    if not isinstance(this_date, date):
        this_date = this_date.date()

    if this_date.day == 1:
        return this_date

    if this_date.month == 12:
        year = this_date.year + 1
        month = 1
    else:
        year = this_date.year
        month = this_date.month + 1

    return datetime(year, month, 1).date()


def previous_date(this_date: datetime.date) -> datetime.date:
    if this_date.day == 1:
        return this_date

    if this_date.month == 1:
        year = this_date.year - 1
        month = 12
    else:
        year = this_date.year
        month = this_date.month - 1
    return datetime(year, month, 1).date()


def tempdir() -> Path:
    return Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())


class Equity(models.Model):

    EQUITY_TYPES = (('Equity', 'Equity/Stock'), ('ETF', 'Exchange Traded Fund'), ('MF', 'Mutual Fund'))
    REGIONS = (('TRT', 'Toronto'), ('', 'United States'))
    CURRENCIES = (('CAD', 'Canadian Dollar'), ('USD', 'US Dollar'))

    @classmethod
    def region_lookup(cls):
        result = {}
        for region in cls.REGIONS:
            result[region[0]] = region[1]
        return result

    key = models.CharField(max_length=32, primary_key=True)  # Symbol + REGIONS.key()
    name = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    symbol = models.CharField(max_length=32, verbose_name='Ticker name used when trading this equity')
    equity_type = models.CharField(max_length=10, blank=True, choices=EQUITY_TYPES)
    region = models.CharField(max_length=10, choices=REGIONS, default='TRT', verbose_name='Region where this is traded')
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='CAD')
    last_updated = models.DateField()

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
        print(f'args:{args}, kwargs:{kwargs}, new: {self._state.adding}')
        if 'update' in kwargs:
            update = kwargs.pop('update')
        else:
            update = True

        self.key = self.key.upper()
        if self._state.adding:
            validated = self.get_equity_data(self.key)
            if validated:
                self.symbol = self.key.split('.')[0]
                self.name = validated['2. name']
                self.equity_type = validated['3. type']
                for region in self.REGIONS:
                    if validated['4. region'] == region[1]:
                        self.region = region[0]
                        break
                self.currency = validated['8. currency']
            else:
                return  # This should cause an error

        if update:
            self.update()

        super(Equity, self).save(*args, **kwargs)

    @staticmethod
    def choice_list():
        choices = list()
        for choice in Equity.objects.all():
            name = f'{choice.symbol} - {choice.equity_type}'
            if choice.region:
                name = f'{name} ({Equity.region_lookup()[choice.region]})'
            choices.append((choice.key, name))
        return sorted(choices)

    def cleanup(self):
        if not Portfolio.objects.filter(equity=self).exists():
            EquityEvent.objects.filter(equity=self).delete()
            EquityValue.objects.filter(equity=self).delete()
            Equity.objects.filter(equity=self).delete()

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
        print(search)
        if 'bestMatches' in data:
            return data['bestMatches']
        return None

    @staticmethod
    def get_equity_data(ticker: str) -> Dict:
        ticker_set = Equity.lookup(ticker)
        if ticker_set:
            if not len(ticker_set) == 1:
                if not ticker_set[0]['9. matchScore'] == '1.0000':
                    return {}
            return ticker_set[0]
        return {}

    def update(self) -> bool:
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month).
        """

        now = datetime.now().date()
        if now == self.last_updated:
            print(f'{self} - Already updated {now}')
            return  False# Don't bother the external API

        url = f'{av_url}TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.key}&apikey={AV_API_KEY}'
        data_key = 'Monthly Adjusted Time Series'
        today = normalize_date(datetime.now())
        print(url)
        result = requests.get(url)
        if not result.status_code == 200:
            print(f'Result is {result.status_code} - {result.reason}')
            return True   # Still did an API call
        self.last_updated = now
        self.save()
        data = result.json()
        if data_key in data:
            for entry in data[data_key]:
                try:
                    print(f'Processing {self} for {entry}')

                    date_value = normalize_date(datetime.strptime(entry, '%Y-%m-%d'))
                    if date_value >= epoch:
                        if date_value == today or not EquityValue.objects.filter(equity=self, date=date_value).exists():
                            print(f'Updating {self} for {date_value}')
                            EquityValue.objects.update_or_create(equity=self,
                                                                 date=date_value,
                                                                 defaults={'price': data[data_key][entry]['4. close']})
                            dividend = float(data[data_key][entry]['7. dividend amount'])
                            print(dividend)
                            if dividend != 0:
                                EquityEvent.objects.update_or_create(equity=self,
                                                                     event_type='Dividend',
                                                                     date=date_value,
                                                                     defaults={'value': data[data_key][entry]['7. dividend amount']})
                except ValueError:
                    print(f'Bad date in {entry}')
        return True


class EquityValue(models.Model):
    """
    Track an equities value
    """
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date = models.DateField()
    price = models.FloatField()


class EquityEvent(models.Model):
    """
    Track an equities dividends
    """
    EVENT_TYPES = (('Dividend', 'Dividend'),  # Automatically created as part of 'Update' action
                   ('SplitAD', 'Stock Split with Adjusted Dividends'),  # Historic dividends adjusted
                   ('Split', 'Stock Split'))

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date = models.DateField()
    value = models.FloatField()
    event_type = models.TextField(max_length=10, choices=EVENT_TYPES)

    def save(self, *args, **kwargs):
        super(EquityEvent, self).save(*args, **kwargs)
        if self.event_type == 'SplitAD':
            print(f'Adjusting Dividends for {self.equity}')
            for event in EquityEvent.objects.filter(equity=self.equity, event_type='Dividend', date__lt=self.date):
                event.value = event.value * self.value
                event.save()
        if self.event_type.startswith('Split'):
            print(f'Adjusting Shares for {self.equity}')
            for transaction in Transaction.objects.filter(equity_fk=self.equity, date__lt=self.date):
                print(f'Portfolio {transaction.portfolio} - Adding {transaction.quantity} from date {transaction.date}')
                Transaction.objects.create(portfolio=transaction.portfolio,
                                           equity_fk=self.equity, equity=self.equity, price=0,
                                           quantity=transaction.quantity, buy_action=True, date=self.date)


class EquitySummary:
    """
    Non django class to load equity values
    """
    def __init__(self, portfolio, equity):
        self.portfolio = portfolio
        self.equity = equity

    @cached_property
    def current_data(self):
        if len(self.history) == 0:
            self.equity.update()
        return self.history[sorted(self.history.keys()).pop()]

    @property
    def shares(self):
        return self.current_data[0]

    @property
    def cost(self):
        return self.current_data[3] * -1

    @property
    def value(self):
        return self.current_data[1]

    @property
    def dividends(self):
        return self.current_data[2]

    @property
    def returns(self) -> float:
        return self.value + self.dividends - self.cost

    @property
    def growth(self) -> float:
        return self.value - self.cost

    @cached_property
    def history(self):
        """
        Prepare a dictionary keyed on date values each entry the value as of that date
        :param start_date:  When to start the search on (none is first entry found
        :param end_date: When to end the search (none is datetime.now()
        :param equity: Which equity to get_values on (default is the whole portfolio)
        :return:

        """

        first_date = list(self.xas)[0]

        result = dict()
        investment_value = 0
        total_dividend = 0

        values = EquityValue.objects.filter(date__gte=first_date, equity=self.equity).order_by('date')
        dividends = dict(
            EquityEvent.objects.filter(date__gte=first_date, event_type='Dividend',
                                       equity=self.equity).values_list('date', 'value'))

        for value in values:  # This is over every month you owned this equity.
            # print(f'get_values: Processing {value.date}')

            # Share value
            shares = self.shares_on_date(value.date)
            result[value.date] = [shares, shares * value.price]

            # Dividend value
            this_dividend = 0
            if value.date in dividends:
                total_dividend += shares * dividends[value.date]
                this_dividend = dividends[value.date]
            result[value.date].append(total_dividend)

            # Investment value
            if value.date in self.xas:
                investment_value = investment_value + self.xas[value.date][1]
            result[value.date].append(investment_value)

            # Aggregated value
            result[value.date].append(shares * value.price + investment_value + total_dividend)
            result[value.date].append(value.price)
            result[value.date].append(this_dividend)
        return result


    @cache
    def shares_on_date(self, date: datetime.date) -> float:
        """
        On any date,  how many shares did I own
         - Use case 1:
              My date is None so take them all
        - Use case 2:
              My date is not none (fails,  None is not an option)

        Testing
        from stocks.models import *
        from datetime import datetime
        p = Portfolio.objects.all()[0]
        e = Equity.objects.get(key='bmo.trt')
        print(p.shares_on_date(e, datetime.now()))  # 292
        print(p.shares_on_date(e, datetime(2021,9,9)))  # 250


        :param ticker:
        :param date:
        :return:
        """
        total = 0

        for xa in self.xas:
            if xa > date:
                return total
            total += self.xas[xa][0]
        return total

    @cached_property
    def xas(self) -> Dict:
        """
        Cache a ordered dictionary normalized representation
                                               shares  Investment  PPS   Value  profit
        first  = buy  (price 5 quantity 10) -> 10,     -50          5,     50     0
        second = buy  (price 6 quantity 15) -> 25, (-50+(-90))      5.6   150     10
        third  = sell (price 4 quantity -5) -> 20, (-140+20)        6     80     -40

        :param ticker:
        :return: Dict(key=date, data = list(shares change (- if sold), value (- if bought)
        """
        result = {}
        for xa in Transaction.objects.filter(equity_fk=self.equity, portfolio=self.portfolio).order_by('date'):
            this_date = normalize_date(xa.date)
            if this_date not in result:
                result[this_date] = [xa.quantity,  xa.value, xa.price]
            else:
                result[this_date] = [result[this_date][0] + xa.quantity, result[this_date][1] + xa.value]
            print(f'Found {xa} on {this_date} --> {result}')
        return dict(sorted(result.items()))


class Portfolio(models.Model):
    """
    Will need to be unique based on future user attribute
    """
    name = models.CharField(max_length=128, unique=True, primary_key=False,
                            help_text='Enter a unique name for this portfolio')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.pk})

    @cached_property
    def current_data(self) -> Dict:
        result = {}
        for equity in self.equities:
            es = EquitySummary(self, equity)
            result[equity.key] = es.current_data
        return result

    @property
    def cost(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity][3] * -1
        return result

    @property
    def value(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity][1]
        return result

    @property
    def dividends(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity][2]
        return result

    @property
    def returns(self) -> float:
        return self.value + self.dividends - self.cost

    @property
    def growth(self) -> float:
        return self.value - self.cost

    @property
    def equities(self) -> List[Equity]:
        return Equity.objects.filter(key__in=Transaction.objects.filter(portfolio=self).values('equity'))

    def update(self):
        """
        Ensure that each of my equities is updated
        :return:
        """
        for equity in self.equities:
            if equity.update():
                sleep(2)  # Any faster and my free API will fail

    def csv_values(self, equity: Equity) -> dict:
        """
        from stocks.models import *
        from datetime import datetime
        p = Portfolio.objects.all()[0]
        e = Equity.objects.get(key='bmo.trt')
        p.csv_values(e)
        """
        results = dict()
        values = self.history(equity)
        print(f'CVS report on portfolio {self} Equity: {equity}')
        print('Date,Cost,Value,Dividends,Net Cost,Gain,% Value Gain,Net Gain,% Net Gain')
        for value in values:
            cost = values[value][3] * -1  # (since cost is negative)
            current = values[value][1]
            dividends = values[value][2]
            net_cost = cost - dividends
            gain = current - cost
            gain_p = gain * 100 / cost
            net_gain = current - net_cost
            net_gain_p = net_gain * 100 / cost
            results[value] = {'cost': cost, 'current': current, 'dividends': dividends}

            print(f'{value},{cost:.0f},{current:.0f},{dividends:.0f},{net_cost:.0f},{gain:.0f}', end='')
            print(f',{gain_p:.1f},{net_gain:.0f},{net_gain_p:.1f}')
        return results


class Transaction(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    equity_fk = models.ForeignKey(Equity, on_delete=models.CASCADE)
    equity = models.TextField(choices=Equity.choice_list())
    date = models.DateField()
    price = models.FloatField()
    quantity = models.FloatField()
    buy_action = models.BooleanField(default=True)

    @property
    def value(self):
        value = self.price * self.quantity
        if (self.buy_action and value > 0) or (not self.buy_action and value < 0):
            value = value * -1
        return value

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        if self.buy_action:  # Since I bought something I spend money so make the price negative
            if self.price > 0:
                self.price = self.price * -1
        else:  # I sold something
            if self.quantity > 0:
                self.quantity = self.quantity * -1
        super(Transaction, self).save(*args, **kwargs)
