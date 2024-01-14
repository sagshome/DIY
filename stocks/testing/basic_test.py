import logging

from datetime import datetime, date
from unittest.mock import patch

from django.test import TestCase

from stocks.models import ExchangeRate, Inflation, Equity, EquityAlias, EquityEvent, EquityValue, Portfolio, Transaction
from stocks.utils import normalize_date, next_date, last_date, normalize_today

logger = logging.getLogger(__name__)

class BasicSetup(TestCase):

    def setUp(self):
        super().setUp()
        print(self.__class__.__name__, self._testMethodName)

        self.months = {
            datetime(2022,1,1).date: 0,
            datetime(2022, 2, 1).date: 0,
            datetime(2022, 3, 1).date: 0,
            datetime(2022, 4, 1).date: 0,
            datetime(2022, 5, 1).date: 0,
            datetime(2022, 6, 1).date: 0,
            datetime(2022, 7, 1).date: 0,
            datetime(2022, 8, 1).date: 0,
            datetime(2022, 9, 1).date: 0,
            datetime(2022, 10, 1).date: 0,
            datetime(2022, 11, 1).date: 0,
            datetime(2022, 12, 1).date: 0,
            datetime(2023, 1, 1).date: 0,
            datetime(2023, 2, 1).date: 0,
            datetime(2023, 3, 1).date: 0

        }
        self.start = normalize_date(datetime(2022, 1, 1))
        self.today = normalize_date(datetime(2023, 3, 1))
        self.my_dates = []
        self.months = 15
        process = self.start

        # 1.  ExchangeRates
        #            jan  feb  mar  apr  may  jun  jul  aug  sep  oct  nov  dec  jan  feb  mar
        us_to_can = [1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        process = self.start
        for r in range(self.months):
            ExchangeRate.objects.create(date=process, us_to_can=us_to_can[r], can_to_us=1 / us_to_can[r])
            process = next_date(process)

        # 2.  Inflation
        #            jan  feb  mar  apr  may  jun  jul  aug  sep  oct  nov  dec  jan  feb  mar
        inflation = [0.1, 0.2, 0.3, 0.4, 0.3, 0.2, 0.1, 0.2, 0.3, 0.4, 0.3, 0.2, 0.1, 0.0, 0.0]
        process = self.start
        for r in range(self.months):
            Inflation.objects.create(date=process, cost=0, inflation=inflation[r], estimated=False)
            process = next_date(process)
        self.inflation: dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))

        # 3. Some Equities
        self.equities = []
        self.equities.append(Equity.objects.create(symbol='CETF.TRT', name='Eq CAN_ETF', equity_type='ETF',
                                                   region='TRT', currency='CAD', searchable=False, validated=True))
        self.equities.append(Equity.objects.create(symbol='CEQ.TRT', name='Eq CAN_EQUITY', equity_type='Equity',
                                                   region='TRT', currency='CAD', searchable=False, validated=True))
        self.equities.append(Equity.objects.create(symbol='USEQ', name='Eq US_EQUITY', equity_type='Equity',
                                                   region='', currency='USD', searchable=False, validated=True))

        eq_values = ((1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3),
                     (2.1, 2.2, 2.3, 2.2, 2.1, 2.0, 1.9, 1.8, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3),
                     (3.1, 3.2, 3.3, 3.2, 3.1, 3.0, 2.9, 2.8, 2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 3.3))
        dv_values = (.25, 0, 0, 0, .25, 0, 0, 0, .25, 0, 0, 0, .25, 0, 0)
        process = self.start
        for r in range(self.months):
            for e in range(3):
                EquityValue.objects.create(equity=self.equities[e], date=process, price=eq_values[e][r],
                                           estimated=False)
                if e == 0:
                    EquityEvent.objects.create(equity=self.equities[e], date=process, value=dv_values[r],
                                               event_type='Dividend', event_source='api')
                elif e == 2:
                    EquityEvent.objects.create(equity=self.equities[e], date=process, value=.1, event_type='Dividend',
                                               event_source='api')

        self.portfolio = Portfolio.objects.create(name='Test', explicit_name='001', managed=False, currency='CAD')


class TestTest(BasicSetup):

    def test_setup(self):
        self.assertTrue(Equity.objects.all().count() == 3)

    @patch('stocks.utils.normalize_today')
    def test_gen_static(self, this_day):
        this_day.return_value = self.today
        Transaction.objects.create(portfolio=self.portfolio, date=last_date(self.start), value=1000,
                                   price=0, quantity=0, xa_action=Transaction.FUND)

        self.portfolio.update_static_values()
        self.assertEqual(self.portfolio.cost, 1000)
        self.assertEqual(self.portfolio.value, 1000)
        self.assertEqual(self.portfolio.start, last_date(self.start))
        self.assertEqual(self.portfolio.dividends, 0)

    @patch('stocks.utils.normalize_today')
    def test_start_dfs(self, this_day):
        """
        This is just by initial funding,  no equities

        EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value','TotalDividends', 'EffectiveCost', 'InflatedCost']
        PortfolioColumns = ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost', 'Cash']
        inflation = [0.1, 0.2, 0.3, 0.4, 0.3, 0.2, 0.1, 0.2, 0.3, 0.4, 0.3, 0.2, 0.1, 0.0, 0.0]

        """
        this_day.return_value = self.today

        cost = inflated_cost = 1000
        Transaction.objects.create(portfolio=self.portfolio, date=self.start, value=cost,
                                   price=0, quantity=0, xa_action=Transaction.FUND)

        this_date = self.start
        while this_date <= self.today:
            row = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == this_date]
            self.assertEqual(row['EffectiveCost'].item(), cost, f'{this_date} EffectiveCost {cost}')
            self.assertEqual(row['Value'].item(), 0, f'{this_date} Value 0')
            self.assertEqual(row['TotalDividends'].item(), 0, f'{this_date} TotalDividends 0')
            self.assertEqual(row['InflatedCost'].item(), inflated_cost, f'{this_date} InflatedCost {inflated_cost}')
            self.assertEqual(row['Cash'].item(), cost, f'{this_date} Cash {cost}')
            inflated_cost += self.inflation[this_date] / 100 * inflated_cost
            this_date = next_date(this_date)

    def test_xa_buy_save(self):
        Transaction.objects.create(portfolio=self.portfolio, date=self.start, value=cost,
                                   price=0, quantity=0, xa_action=Transaction.FUND)

        t = Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.start,
                                       xa_action=Transaction.BUY, price=1.1, quantity=10)
        self.assertEqual(t.value, 11, 'Unexpected value got %s expected 11' % t.value)  # 10 * 1.1


    @patch('stocks.utils.normalize_today')
    def test_with_can_dividends(self, this_day):
        this_day.return_value = self.today
        Transaction.objects.create(portfolio=self.portfolio, date=self.start, value=cost,
                                   price=0, quantity=0, xa_action=Transaction.FUND)

        t = Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.start,
                                       xa_action=Transaction.BUY, price=1.1, quantity=10)
        this_date = self.start
        cost = inflated_cost = 1000
        while this_date <= self.today:
            row = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == this_date]
            self.assertEqual(row['EffectiveCost'].item(), cost, f'{this_date} EffectiveCost {cost}')
            self.assertEqual(row['Value'].item(), 0, f'{this_date} Value 0')
            self.assertEqual(row['TotalDividends'].item(), 0, f'{this_date} TotalDividends 0')
            self.assertEqual(row['InflatedCost'].item(), inflated_cost, f'{this_date} InflatedCost {inflated_cost}')
            self.assertEqual(row['Cash'].item(), cost, f'{this_date} Cash {cost}')
            inflated_cost += self.inflation[this_date] / 100 * inflated_cost
            this_date = next_date(this_date)






