import platform
import requests
import tempfile

from django.db import models
from diy.settings import ALPHAVANTAGEAPI_KEY as AV_API_KEY
from typing import List, Dict
from pathlib import Path


from datetime import datetime
from functools import cache

av_url = 'https://www.alphavantage.co/query?function='

'''
Notes:
Inflation WebSite: https://www150.statcan.gc.ca/t1/tbl1/en/cv.action?pid=1810000401 (download Ontario all)
    Use this to calculate current equivalent dollar value (should be higher) or idle dollar value (the inverse)
'''


def normalize_date(this_date: datetime.date) -> datetime.date:
    """
    Make every date the start of the next month.    The alpahvantage website is based on the last trading day each month
    :param this_date:  The date to normalize
    :return:  The 1st of the next month (and year if December)
    """

    if this_date.day == 1:
        return this_date

    if this_date.month == 12:
        year = this_date.year + 1
        month = 1
    else:
        year = this_date.year
        month = this_date.month + 1
    return datetime(year, month, 1).date()


def tempdir() -> Path:
    return Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())


class Equity(models.Model):
    key = models.CharField(max_length=128, primary_key=True)
    name = models.CharField(max_length=128, blank=True)

    def __str__(self):
        return self.key

    def save(self, *args, **kwargs):
        super(Equity, self).save(*args, **kwargs)
        self.update()

    @staticmethod
    def lookup(key: str) -> List[Dict]:
        """
        Given a key,   use the API to find the best stock matches.   Not used but should be
        :param key:  The search key string
        :return:  A list of dictionary values (top 10) that match - The API is lacking it would be great if it
                  supported wild cards (request was sent)
        """
        data = requests.get(av_url + 'SYMBOL_SEARCH&keywords=' + key + '&apikey=' + AV_API_KEY).json()
        return data['bestMatches']

    def update(self):
        """
        For simplification,  I will change the closing date (each month) to the first of the next month.  This
        provides consistency later on when processing transactions (which will also be processed on the first of the
        next month.
        :return:
        """
        url = f'{av_url}TIME_SERIES_MONTHLY_ADJUSTED&symbol={self.key}&outputsize=full&apikey={AV_API_KEY}'
        data_key = 'Monthly Adjusted Time Series'
        print(url)
        result = requests.get(url)
        if result.status_code == 200:
            data = result.json()
            if data_key in data:
                for entry in data[data_key]:
                    try:
                        date_value = normalize_date(datetime.strptime(entry, '%Y-%m-%d'))

                        existing = EquityValue.objects.filter(equity=self, date=date_value)
                        if not existing:
                            EquityValue.objects.create(equity=self,
                                                       date=date_value,
                                                       price=data[data_key][entry]['4. close'])
                            if float(data[data_key][entry]['7. dividend amount']) != 0:
                                EquityDividend.objects.create(equity=self,
                                                              date=date_value,
                                                              value=data[data_key][entry]['7. dividend amount'])
                    except ValueError:
                        print(f'Bad date in {entry}')
        else:
            print(f'Result is {result.status_code} - {result.reason}')


class EquityValue(models.Model):
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date = models.DateField()
    price = models.FloatField()


class EquityDividend(models.Model):
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
    date = models.DateField()
    value = models.FloatField()


class Portfolio(models.Model):
    name = models.CharField(max_length=128, unique=True, primary_key=True)
    members = models.ManyToManyField(Equity, through='Transaction')

    def __str__(self):
        return self.name

    @cache
    def xas(self, ticker: Equity) -> Dict:
        """
        Cache a dictionary normalized representation
                                               shares  Investment  PPS   Value  profit
        first  = buy  (price 5 quantity 10) -> 10,     -50          5,     50     0
        second = buy  (price 6 quantity 15) -> 25, (-50+(-90))      5.6   150     10
        third  = sell (price 4 quantity -5) -> 20, (-140+20)        6     80     -40

        :param ticker:
        :return: Dict(key=date, data = list(shares change (- if sold), value (- if bought)
        """
        result = {}
        print(f'Searching portfolio {self.name} for XA on ticker {ticker.key}')
        for xa in Transaction.objects.filter(equity=ticker, portfolio=self):
            this_date = normalize_date(xa.date)
            if this_date not in result:
                result[this_date] = [xa.quantity,  xa.value]
            else:
                result[this_date] = [result[this_date][0] + xa.quantity, result[this_date][1] + xa.value]
        return dict(sorted(result.items()))

    @cache
    def shares_on_date(self, ticker: Equity, date: datetime.date) -> float:
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
        xas = self.xas(ticker)
        for xa in xas:
            if xa > date:
                return total
            total += xas[xa][0]
        return total

    def csv_values(self, equity: Equity) -> dict:
        """
        from stocks.models import *
        from datetime import datetime
        p = Portfolio.objects.all()[0]
        e = Equity.objects.get(key='bmo.trt')
        p.csv_values(e)
        """
        results = dict()
        values = self.get_values(equity)
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


    def get_values(self, equity: Equity, start_date: datetime = None, end_date: datetime = None):
        """
        Prepare a dictionary keyed on date values each entry the value as of that date
        :param start_date:  When to start the search on (none is first entry found
        :param end_date: When to end the search (none is datetime.now()
        :param equity: Which equity to get_values on (default is the whole portfolio)
        :return:

        def dump_res(res, e):
            print(f'Equity is {e}')
            for x in res:
                print(f'{x} Shares:{res[x][0]} Value:${res[x][1]:.0f} Invested:${res[x][3]:.0f} Accumulated Dividends:${res[x][2]:.0f} Profit: {(res[x][1] + res[x][2] + res[x][3]):0f}')


        from stocks.models import *
        from datetime import datetime
        p = Portfolio.objects.all()[0]
        e = Equity.objects.get(key='bmo.trt')
        e2 = Equity.objects.get(key='bce.trt')
        e3 = Equity.objects.get(key='cu.trt'
        res = p.get_values(e)
        res2 = p.get_values(e2)
        res3 = p.get_values(e3)


        """

        xas = self.xas(equity)
        first_date = list(xas)[0]

        result = dict()
        investment_value = 0
        total_dividend = 0

        values = EquityValue.objects.filter(date__gte=first_date, equity=equity).order_by('date')
        dividends = dict(
            EquityDividend.objects.filter(date__gte=first_date, equity=equity).values_list('date', 'value'))

        for value in values:  # This is over every month you owned this equity.
            # print(f'get_values: Processing {value.date}')

            # Share value
            shares = self.shares_on_date(equity, value.date)
            result[value.date] = [shares, shares * value.price]

            # Dividend value
            if value.date in dividends:
                total_dividend += shares * dividends[value.date]
            result[value.date].append(total_dividend)

            # Investment value
            if value.date in xas:
                investment_value = investment_value + xas[value.date][1]
            result[value.date].append(investment_value)

            # Aggregated value
            result[value.date].append(shares * value.price + investment_value + total_dividend)

        return result


class Transaction(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE)
    equity = models.ForeignKey(Equity, on_delete=models.CASCADE)
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
        if self.buy_action:  # Since I bought something I spend money so make the price negative
            if self.price > 0:
                self.price = self.price * -1
        else:  # I sold something
            if self.quantity > 0:
                self.quantity = self.quantity * -1
        super(Transaction, self).save(*args, **kwargs)
