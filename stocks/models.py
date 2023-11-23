import copy
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
from time import sleep

epoch = datetime(2018, 1, 1).date()  # Before this date.   I was too busy working
av_url = 'https://www.alphavantage.co/query?function='
av_regions = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
'''


def normalize_date(this_date: date | datetime) -> datetime.date:
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

    key: str = models.CharField(max_length=32, primary_key=True)  # Symbol + REGIONS.key()
    name = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    # todo: Do I really need symbol?
    symbol = models.CharField(max_length=32, verbose_name='Ticker name used when trading this equity')
    equity_type = models.CharField(max_length=10, blank=True, null=True, choices=EQUITY_TYPES)
    region = models.CharField(max_length=10, null=True, blank=True, choices=REGIONS, default='TRT',
                              verbose_name='Region where this is traded')
    currency = models.CharField(max_length=3, null=True, blank=True, choices=CURRENCIES, default='CAD')
    last_updated = models.DateField(blank=True, null=True)

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
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

    def update(self, force: bool = True) -> bool:
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month).
        """

        now = datetime.now().date()
        if now == self.last_updated and not force:
            print(f'{self} - Already updated {now}')
            return False  # Don't bother the external API

        url = f'{av_url}TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.key}&apikey={AV_API_KEY}'
        data_key = 'Monthly Adjusted Time Series'
        today = normalize_date(datetime.now())
        print(url)
        result = requests.get(url)
        if not result.status_code == 200:
            print(f'Result is {result.status_code} - {result.reason}')
            return True   # Still did an API call
        self.last_updated = now
        self.save(update=False)

        data = result.json()
        if data_key in data:
            for entry in data[data_key]:
                try:
                    date_value = normalize_date(datetime.strptime(entry, '%Y-%m-%d'))
                    if date_value >= epoch:
                        print(f'Processing {self} for {entry}')
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


class SummaryItem:
    """
    A linked list of processed data that is used by EquitySummary
    change will be negative if we are selling
    """
    def __init__(self, previous, price: float, key: str, dividend: float = 0, change: float = 0, xa_price: float = 0):

        self.price = price
        self.dividend = dividend
        self.previous = previous
        self.change = change
        self.xa_price = xa_price
        self.key = key

        if previous:
            if previous.shares + change < 0:
                raise ValueError("Trying to sell what you don't own")
            self.shares = change + previous.shares
            self.value = self.shares * price
            self.cost = previous.cost + (change * xa_price)
            self.dividends = previous.dividends + (dividend * self.shares)
        else:
            if change < 0:
                raise ValueError("Initial equity entry must be a purchase")
            self.shares = change  # which must be a positive
            self.value = change * price
            self.cost = change * xa_price
            self.dividends = dividend * change

    @property
    def gain(self) -> float:
        return (self.value + self.dividends - self.cost) / self.cost * 100

    @property
    def growth(self) -> float:
        return self.value - self.cost

    @property
    def returns(self) -> float:
        return self.value + self.dividends - self.cost


class EquitySummary:
    """
    Non django class to load equity values base on portfolio

    Need to decouple from a portfolio
        - We need a Transaction history cloass

    """

    def __init__(self, equity: Equity, transactions: List['TransactionSummary']):
        self.equity = Equity.objects.get(key=equity)
        self.transactions = transactions

    @cached_property
    def data(self) -> Dict[date, SummaryItem]:
        """
        """

        results = {}
        first = sorted(self.transactions.keys())[0]
        values = EquityValue.objects.filter(date__gte=first, equity=self.equity).order_by('date')
        dividends = dict(
            EquityEvent.objects.filter(date__gte=first, event_type='Dividend',
                                       equity=self.equity).values_list('date', 'value'))

        old_record = None
        for value in values:  # This is over every month you owned this equity.
            dividend = dividends[value.date] if value.date in dividends else 0
            if value.date in self.transactions:
                old_record = SummaryItem(old_record, value.price, self.equity, dividend=dividend,
                                         change=self.transactions[value.date].quantity,
                                         xa_price=self.transactions[value.date].price)
            else:
                old_record = SummaryItem(old_record, value.price, self.equity, dividend=dividend)
            results[value.date] = old_record
        return results

    @cached_property
    def current_data(self):
        if len(self.data) == 0:
            self.equity.update()
        return self.data[sorted(self.data.keys()).pop()]

    @property
    def shares(self):
        return self.current_data.shares

    @property
    def cost(self):
        return self.current_data.cost

    @property
    def value(self):
        return self.current_data.value

    @property
    def dividends(self):
        return self.current_data.dividends

    @property
    def returns(self) -> float:
        return self.value + self.dividends - self.cost

    @property
    def growth(self) -> float:
        return self.value - self.cost

    @property
    def key(self) -> str:
        return self.equity.key


class TransactionSummary:
    """
    Create on record per day for each instance of a transaction for that equity and that portfolio
    """
    def __init__(self, xa_date: date, portfolio: 'Portfolio', equity: 'Equity'):
        self.date = date
        self.price = 0
        self.quantity = 0

        total_shares = 0
        total_cost = 0
        xas = Transaction.objects.filter(date=xa_date, portfolio=portfolio, equity_fk=equity)
        for xa in xas:
            if xa.buy_action:
                total_shares += xa.quantity
                total_cost = total_cost + (xa.price * xa.quantity)
            else:
                total_shares -= xa.quantity
                total_cost = total_cost - (xa.price * xa.quantity)
        self.price = total_cost / total_shares
        self.quantity = total_shares


class PortfolioSummary:
    """
    None DB class that will calculate the historic information regarding a portfolio.    We purposefully do not
    reference raw portfolio or transaction data.   This is done so that we can compare / create speculative data
    """

    def __init__(self, name):
        self.name = name
        self.xa_history = {}
        self.data = {}

    def add_item(self, equity: Equity, xa_s: List[TransactionSummary]):
        if equity.key not in self.xa_history:
            self.xa_history[equity.key] = None
        self.xa_history[equity.key] = xa_s

    def duplicate(self, name: str) -> 'PortfolioSummary':
        new = PortfolioSummary(name)
        new.xa_history = copy.deepcopy(self.xa_history)

    def switch_equity(self, new_equity: Equity):
        for x in self.xa_history:
            if not x == new_equity.key:
                value = self.xa_history


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


    @property
    def equities(self) -> List[Equity]:
        return Equity.objects.filter(key__in=Transaction.objects.filter(portfolio=self).values('equity')).order_by('key')

    @property
    def equity_keys(self):
        result = []
        for equity in self.equities:
            result.append(equity.key)
        return result

    @cached_property
    def current_data(self) -> Dict:
        result = {}
        for key in self.data:
            result[key] = self.data[key].current_data
        return result


    @cached_property
    def transactions(self) -> Dict[str, Dict[date, TransactionSummary]]:
        """
        Cache and return a
        'equity1' : [xa1, xa2,...],
        'equity2' : [xa1,]
        :return:
        """
        result = {}
        for equity in self.equities:
            if equity.key not in result:
                result[equity.key] = {}
            for this_date in Transaction.objects.filter(
                    portfolio=self, equity_fk=equity).order_by('date').values_list('date', flat=True).distinct():
                result[equity.key][this_date] = TransactionSummary(this_date, self, equity)
        return result

    @cached_property
    def data(self) -> Dict[str, EquitySummary]:
        """
        Build up a dictionary of equity_keys,  dates and equitySummary

        :return:
        """
        results = dict()
        for equity_key in self.transactions.keys():
            results[equity_key] = EquitySummary(equity_key, self.transactions[equity_key])
        return results

    @property
    def cost(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity].cost
        return result

    @property
    def value(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity].value
        return result

    @property
    def dividends(self) -> float:
        result = 0
        for equity in self.current_data:
            result += self.current_data[equity].dividends
        return result

    @property
    def returns(self) -> float:
        return self.value + self.dividends - self.cost

    @property
    def gain(self) -> float:
        return (self.value + self.dividends - self.cost) / self.cost * 100


    @property
    def growth(self) -> float:
        return self.value - self.cost


    def update(self):
        """
        Ensure that each of my equities is updated
        :return:
        """
        for equity in self.equities:
            if equity.update():
                sleep(2)  # Any faster and my free API will fail


class Transaction(models.Model):
    """
    Track changes made to an equity on a portfolio
    """
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    equity_fk = models.ForeignKey(Equity, on_delete=models.CASCADE)  # Needed this so I can make a choice list
    equity = models.TextField(choices=Equity.choice_list())
    date: date = models.DateField()
    price: float = models.FloatField()
    quantity: float = models.FloatField()
    buy_action = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.equity} - {self.date}: {self.price} {self.quantity} Buy({self.buy_action})'

    @property
    def value(self):
        value = self.price * self.quantity
        return value

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        self.equity_fk = Equity.objects.get(key=self.equity)
        super(Transaction, self).save(*args, **kwargs)
