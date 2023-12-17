import copy
import pandas as pd
import requests
from django.urls import reverse

from django.db import models
from django.utils.functional import cached_property

from diy.settings import ALPHAVANTAGEAPI_KEY as AV_API_KEY
from typing import List, Dict


from datetime import datetime, date
from time import sleep

from stocks.utils import normalize_date, normalize_today, next_date

epoch = datetime(2014, 1, 1).date()  # Before this date.   I was too busy working
av_url = 'https://www.alphavantage.co/query?function='
av_regions = {'Toronto': {'suffix': 'TRT'},
              'United States': {'suffix': None},
              }
'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
    
Bank of Canada
https://www.bankofcanada.ca/valet/docs
https://www.bankofcanada.ca/valet/observations/STATIC_INFLATIONCALC/json?recent_months=96&order_dir=asc
   - above to calculate inflatin
'''


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
        url = f'https://www.bankofcanada.ca/valet/observations/STATIC_INFLATIONCALC/json?start_date={first_str}'
        result = requests.get(url)
        if not result.status_code == 200:
            print(f'BOC API failure: {result.status_code} - {result.reason}')
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
                        print(f'{record.date}: Inflation set to {last_inflation}')
                        record.inflation = last_inflation
                        record.save()
                last_date = record.date
                last_cost = record.cost
                print(f'{last_date} {last_cost}')
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
    CURRENCIES = (('CAD', 'Canadian Dollar'), ('USD', 'US Dollar'))

    @classmethod
    def region_lookup(cls):
        result = {}
        for region in cls.REGIONS:
            result[region[0]] = region[1]
        return result

    symbol: str = models.CharField(max_length=32, verbose_name='Trading symbol')  # Symbol
    name: str = models.CharField(max_length=128, blank=True, null=True, verbose_name='Equities Full Name')
    equity_type: str = models.CharField(max_length=10, blank=True, null=True, choices=EQUITY_TYPES)
    region: str = models.CharField(max_length=10, null=False, blank=False, choices=REGIONS, default='TRT',
                              verbose_name='Region where this is traded')
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
                print(last_date, value, months, change_increment)
                for _ in range(months):
                    next_month = next_date(last_date)
                    last_price = last_price + change_increment
                    if not EquityValue.objects.filter(equity=self, date=next_month).exists():
                        EquityValue.objects.get_or_create(equity=self, date=next_month,
                                                          price=last_price, estimated=True)
                    last_date = next_month

            last_date = value
            last_price = date_values[value]

        last_entry = EquityValue.objects.filter(equity=self).order_by('-date')[0]
        current_date = normalize_today()
        date_value = next_date(last_entry.date)
        if not date_value > current_date:
            price_value = last_entry.price
            while date_value <= current_date:
                EquityValue.objects.create(equity=self, date=date_value, price=price_value, estimated=True)
                date_value = next_date(date_value)

    def update(self, force: bool = False) -> bool:
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month).
        """
        if not self.validated:
            self.searchable = self.set_equity_data(self.symbol)
            self.validated = True

        if self.searchable:
            # Get rid of any uploaded dividend data,  it may be duplicated based on off month processing
            EquityEvent.objects.filter(event_source='upload', event_type='Dividend').delete()

            now = datetime.now().date()
            if now == self.last_updated and not force:
                print(f'{self} - Already updated {now}')
                return False  # Don't bother the external API

            url = f'{av_url}TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.symbol}&apikey={AV_API_KEY}'
            data_key = 'Monthly Adjusted Time Series'
            this_day = normalize_date(datetime.now())
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
                            if date_value == this_day or not EquityValue.objects.filter(
                                    equity=self, estimated=False, date=date_value).exists():
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
                    except ValueError:
                        print(f'Bad date in {entry}')
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
        match: Equity
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
    date = models.DateField()
    price = models.FloatField()
    estimated = models.BooleanField(default=False)

    def __str__(self):
        output = f'{self.equity} - {self.date}: {self.price}'
        if self.estimated:
            output = f'{output} ?'
        return output


class EquityEvent(models.Model):
    """
    Track an equities dividends
    """
    EVENT_TYPES = (('Dividend', 'Dividend'),  # Automatically created as part of 'Update' action
                   ('SplitAD', 'Stock Split with Adjusted Dividends'),  # Historic dividends adjusted
                   ('Split', 'Stock Split'))
    EVENT_SOURCE = (('manual', 'Manual'), ('api', 'API'), ('upload', 'Upload'))

    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date = models.DateField()
    value = models.FloatField()
    event_type = models.TextField(max_length=10, choices=EVENT_TYPES)
    event_source = models.TextField(max_length=6, choices=EVENT_SOURCE)

    def save(self, *args, **kwargs):
        if not self.event_source:
            self.event_source = 'manual'
        super(EquityEvent, self).save(*args, **kwargs)
        if self.event_type == 'SplitAD':
            print(f'Adjusting Dividends for {self.equity}')
            for event in EquityEvent.objects.filter(equity=self.equity, event_type='Dividend', date__lt=self.date):
                event.value = event.value * self.value
                event.save()
        if self.event_type.startswith('Split'):
            print(f'Adjusting Shares for {self.equity}')
            for transaction in Transaction.objects.filter(equity=self.equity, date__lt=self.date):
                # print(f'Portfolio {transaction.portfolio} - Adding {transaction.quantity} from date {transaction.date}')
                Transaction.objects.create(portfolio=transaction.portfolio,
                                           equity=self.equity, price=0,
                                           quantity=transaction.quantity, xa_action='buy', date=self.date)


class TransactionSummary:
    """
    Create on record per day for each instance of a transaction for that equity and that portfolio
    """
    def __init__(self, xa_date: date, equity: 'Equity'):
        self.xa_date = xa_date
        self.equity = equity
        self.price = 0
        self.quantity = 0
        self.dividend = 0

    def process(self, portfolio: 'Portfolio'):

        total_shares = 0
        total_cost = 0
        total_dividends = 0
        xas = Transaction.objects.filter(date=self.xa_date, portfolio=portfolio, equity=self.equity)
        price = 0
        for xa in xas:
            price = xa.price
            if xa.xa_action == 'buy':
                total_shares += xa.quantity
                total_cost = total_cost + (xa.price * xa.quantity)
            elif xa.xa_action == 'sell':
                total_shares -= xa.quantity
                total_cost = total_cost - (xa.price * xa.quantity)
            elif xa.xa_action == 'int':
                total_dividends += xa.quantity
            elif xa.xa_action == 'div':
                total_shares += xa.quantity

        self.price = total_cost / total_shares if total_shares else price
        self.quantity = total_shares
        self.dividend = total_dividends

    def set(self, price,  quantity, dividends):
        self.price = price
        self.quantity = quantity
        self.dividend = dividends

    def adjust_shares(self, funds):
        self.quantity += funds / self.price


class PortfolioSummary:
    """
    None DB class that will calculate the historic information regarding a portfolio.    We purposefully do not
    reference raw portfolio or transaction data.   This is done so that we can compare / create speculative data
    """
    DataColumns = ['Date',   # The date of this record
                   'Funding',  # The amount the Portfolio has received and redeemed
                   'FundingCost',  # The inflated cost of the funding
                   'Equity',   # The equity (key) for this entry
                   'Shares',   # The number of shares (on this date)
                   'Spent',  # Accumulated Cost
                   'Redeemed',  # Accumulated Sales
                   'EffectiveCost',  # Spend - Redeemed (or 0)
                   'Value',  # Present Value
                   'Dividend',  # The dividend value on this date/equity/portfolio
                   'TotalDividends',   # The accumulated dividends as of this date
                   'InflatedCost',  # The cost (as of this date) - with inflation factored in / Less redeemed
                   ]

    def __init__(self, name: str, xas: Dict, funding: Dict, drip: bool = False):
        self.name = name
        self.xas = xas
        self.funding = funding
        self.drip = drip  # if this a drip portfolio then do not realize dividends - they will appear as purchases

    @cached_property
    def pd(self) -> pd:
        '''
        This structure
        :return:
        '''
        now = datetime.now()
        new = pd.DataFrame(columns=self.DataColumns)
        monthly_inflation: Dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))
        e: Equity

        for e in self.xas.keys():
            equity = Equity.objects.get(symbol=e)
            first = sorted(self.xas[e])[0]  # todo: How many times am I sorting this
            values = EquityValue.objects.filter(date__gte=first, equity=equity).order_by('date')
            dividends: Dict[date, float] = dict(EquityEvent.objects.filter(date__gte=first, event_type='Dividend',
                                                                           equity=equity).values_list('date', 'value'))

            shares = spent = redeemed = effective_cost = total_dividends = inflation = 0
            for value in values:  # This is over every month you owned this equity.
                if self.drip:
                    dividend = 0
                else:
                    dividend = dividends[value.date] if value.date in dividends else 0

                new_cash = 0
                if value.date in self.xas[e]:
                    xa = self.xas[e][value.date]
                    shares += xa.quantity
                    if xa.quantity > 0:
                        spent += xa.quantity * xa.price
                    else:
                        redeemed += xa.quantity * xa.price
                    effective_cost += xa.quantity * xa.price
                    inflation += (inflation * monthly_inflation[value.date] / 100) + (xa.quantity * xa.price)
                    if equity.equity_type == 'MM':
                        new_cash += xa.dividend  # todo:  Test this out with a MM equity
                else:
                    inflation += inflation * monthly_inflation[value.date] / 100
                    if effective_cost < 0:
                        print(f'Equity:{e} Date:{value.date} - LESS THEN 0 -> {effective_cost} Shares {shares}')
                        shares = 0
                        inflation = 0
                        effective_cost = 0
                this_dividend = shares * dividend if not self.drip else 0
                total_dividends += this_dividend + new_cash

                new.loc[len(new.index)] = [value.date, e, shares, spent, redeemed, effective_cost,
                                           value.price * shares, this_dividend, total_dividends, inflation]
        print(f'Created DataFrame for {self.name} in {(datetime.now()-now).seconds}')
        return new

    def switch(self, new_name: str, new_equity: Equity, original_portfolio: 'Portfolio') -> 'PortfolioSummary':
        '''
        Using the data from this portfolio summary,  create a new portfolio based on new_equity.   If this portfolio
        is managed,  assume any dividends are just dripped back in.

        :param new_name:
        :param new_equity:
        :param original_portfolio:
        :return:
        '''

        new = PortfolioSummary(new_name, {}, original_portfolio.managed)
        new.xas = dict()  # This is what we are switching out.
        new.xas[new_equity.key] = {}

        new_v = dict(EquityValue.objects.filter(equity=new_equity).values_list('date', 'price'))
        new_d = dict(EquityEvent.objects.filter(equity=new_equity, event_type='Dividend').values_list('date', 'value'))

        # Pass 1,  figure out shares owned
        for equity in self.xas:
            for this_date in self.xas[equity]:
                xa = self.xas[equity][this_date]
                if this_date not in new.xas[new_equity.key]:
                    new.xas[new_equity.key][this_date] = TransactionSummary(this_date, new_equity)
                    new.xas[new_equity.key][this_date].set(new_v[this_date], 0, 0)

                if not xa.quantity == 0:  # We bought or sold something  vs split or drip
                    new.xas[new_equity.key][this_date].adjust_shares(xa.quantity * xa.price)
                else:
                    pass  # This must be a split. It does not apply. Not sure how to deal with splits in new equity.
        return new


class Portfolio(models.Model):
    """
    Will need to be unique based on future user attribute
    """

    name: str = models.CharField(max_length=128, unique=True, primary_key=False,
                                 help_text='Enter a unique name for this portfolio')
    managed: bool = models.BooleanField(default=True)
    # These Values are updated to allow for a quick loading of portfolio_list
    cost: int = models.IntegerField(null=True, blank=True)  # Effective cost of all shares ever purchased
    value: int = models.IntegerField(null=True, blank=True)  # of shares owned as of today
    dividends: int = models.IntegerField(null=True, blank=True)  # Total dividends ever received
    start: date = models.DateField(null=True, blank=True)
    end: date = models.DateField(null=True, blank=True)

    @cached_property
    def summary(self):
        return PortfolioSummary(str(self.name), self.transactions, self.funding, drip=self.managed)

    def funding(self):
        return dict(Funding.objects.filter(portfolio=self).values_list('date', 'amount').order_by_date())

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.pk})

    @cached_property
    def pd(self) -> pd:
        return self.summary.pd

    @property
    def equities(self) -> List[Equity]:
        return Equity.objects.filter(symbol__in=Transaction.objects.filter(portfolio=self).values('equity__symbol')).order_by('symbol')

    @property
    def equity_keys(self):
        return sorted(self.pd['Equity'].unique())

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
                    portfolio=self, equity=equity).order_by('date').values_list('date', flat=True).distinct():
                result[equity.key][this_date] = TransactionSummary(this_date, equity)
                result[equity.key][this_date].process(self)
        return result


    @property
    def growth(self) -> int:
        return self.value - self.cost

    @property
    def total(self) -> int:
        return self.growth + self.dividends

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
        current = self.pd.loc[self.pd['Date'] == this_day]
        self.cost = current['EffectiveCost'].sum()
        self.dividends = current['TotalDividends'].sum()
        self.value = current['Value'].sum()
        self.start = self.pd['Date'].min()
        end_date = self.pd.loc[self.pd['Value'] > 0]['Date'].max()
        self.save()


class Funding(models.Model):
    """
    Track money in/out of a portfolio
    """
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    date: date = models.DateField()
    amount: float = models.FloatField()

    def __str__(self):
        return f'{self.date} - {self.portfolio} - {self.amount}'

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super(Transaction, self).save(*args, **kwargs)
        raise Exception(f'Portfolio {portfolio} - has negative funding.')


class Transaction(models.Model):
    """
    Track changes made to an equity on a portfolio
    """

    @staticmethod
    def equity_choice_list():
        choices = list()

        for choice in Equity.objects.all():
            name = f'{choice.key} - {choice.equity_type}'
            if choice.region:
                name = f'{name} ({Equity.region_lookup()[choice.region]})'
            choices.append((choice.id, name))
        return sorted(choices)


    TRANSACTION_TYPE = (('buy', 'Buy'), ('sell', 'Sell'), ('int', 'Interest'), ('div', 'Dividend'))
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    #
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)  # Needed this so I can make a choice list
    date: date = models.DateField()
    price: float = models.FloatField()
    quantity: float = models.FloatField()
    xa_action = models.TextField(choices=TRANSACTION_TYPE, default='buy')
    drip = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.portfolio}: {self.equity} - {self.date}: {self.price} {self.quantity} Buy({self.xa_action})'

    @property
    def value(self):
        value = self.price * self.quantity
        return value

    def save(self, *args, **kwargs):
        self.date = normalize_date(self.date)
        super(Transaction, self).save(*args, **kwargs)
