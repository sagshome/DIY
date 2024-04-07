import logging

from datetime import datetime, date
from freezegun import freeze_time
from unittest.mock import patch

from django.test import TestCase

from stocks.models import ExchangeRate, Inflation, Equity, EquityEvent, EquityValue, Portfolio, Transaction, DataSource
from base.utils import normalize_date, next_date, last_date, normalize_today

logger = logging.getLogger(__name__)

class BasicSetup(TestCase):

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)


        # Some Equities
        self.equities = []
        self.equities.append(Equity.objects.create(symbol='CETF.TRT', name='Eq CAN_ETF', equity_type='ETF',
                                                   region='TRT', currency='CAD', searchable=False, validated=True))
        self.equities.append(Equity.objects.create(symbol='USEQ', name='Eq US_EQUITY', equity_type='Equity',
                                                   region='', currency='USD', searchable=False, validated=True))
        self.portfolio = Portfolio.objects.create(name='Test', explicit_name='001', managed=False, currency='CAD')


class DataFrameTest(BasicSetup):
    def setUp(self):
        super().setUp()
        self.months = [datetime(2022, 1, 1).date(),
                       datetime(2022, 2, 1).date(),
                       datetime(2022, 3, 1).date(),
                       datetime(2022, 4, 1).date(),
                       datetime(2022, 5, 1).date(),
                       datetime(2022, 6, 1).date(),
                       ]

        EquityValue.objects.create(equity=self.equities[0], date=self.months[0], price=10)
        EquityValue.objects.create(equity=self.equities[0], date=self.months[1], price=10)
        EquityValue.objects.create(equity=self.equities[0], date=self.months[2], price=10)
        EquityValue.objects.create(equity=self.equities[0], date=self.months[3], price=10)
        EquityValue.objects.create(equity=self.equities[0], date=self.months[4], price=10)
        EquityValue.objects.create(equity=self.equities[0], date=self.months[5], price=10)

        Transaction.objects.create(portfolio=self.portfolio, date=self.months[0], value=1000, xa_action=Transaction.FUND)
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[1],
                                   price=10, quantity=50, xa_action=Transaction.BUY)

    @freeze_time("2022-02-02")
    def test_nochange(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000, 'PD EffectiveCost')
        self.assertEqual(today_pd_series['Value'].item(), 500, 'PD Value')
        self.assertEqual(today_pd_series['TotalDividends'].item(), 0, 'PD Total Dividends')
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000, 'PD Inflated Cost')
        self.assertEqual(today_pd_series['Cash'].item(), 500, 'PD Cash')
        # EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value', 'TotalDividends', 'EffectiveCost', 'InflatedCost']

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Equity'].item(), self.equities[0].symbol, 'EPD Symbol')
        self.assertEqual(today_ed_series['Shares'].item(), 50, 'EPD Shares')
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 10, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 500, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 0, 'EPD Total Dividends')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 500, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 500, 'EPD Inflated Cost')

    @freeze_time("2022-02-02")
    def test_day_change(self):
        """
        On the trade day we bought 50@10,  then sold 10@11
        :return:
        """
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[1],
                                   price=11, quantity=10, xa_action=Transaction.SELL)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000, 'PD EffectiveCost')
        self.assertEqual(today_pd_series['Value'].item(), 400, 'PD Value')
        self.assertEqual(today_pd_series['TotalDividends'].item(), 0, 'PD Total Dividends')
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000, 'PD Inflated Cost')
        self.assertEqual(today_pd_series['Cash'].item(), 610, 'PD Cash')
        # EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value', 'TotalDividends', 'EffectiveCost', 'InflatedCost']

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Equity'].item(), self.equities[0].symbol, 'EPD Symbol')
        self.assertEqual(today_ed_series['Shares'].item(), 40, 'EPD Shares')
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 10, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 400, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 0, 'EPD Total Dividends')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 390, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 390, 'EPD Inflated Cost')

    @freeze_time("2022-02-02")
    def test_daytrader(self):
        """
        On the trade day we bought 50@10,  then sold 10@11
        :return:
        """
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[1],
                                   price=11, quantity=50, xa_action=Transaction.SELL)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000, 'PD EffectiveCost')
        self.assertEqual(today_pd_series['Value'].item(), 0, 'PD Value')
        self.assertEqual(today_pd_series['TotalDividends'].item(), 0, 'PD Total Dividends')
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000, 'PD Inflated Cost')
        self.assertEqual(today_pd_series['Cash'].item(), 1050, 'PD Cash')
        # EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value', 'TotalDividends', 'EffectiveCost', 'InflatedCost']

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Shares'].item(), 0, 'EPD Shares')
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 10, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 0, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 0, 'EPD Total Dividends')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 0, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 0, 'EPD Inflated Cost')

    @freeze_time("2022-02-02")
    def test_inflation(self):
        """
        This inflation should not count since it was in the month we funded (inflation counted after the fact)
        default inflation = 0,  exchange rate = 1
        :return:
        """
        Inflation.objects.create(date=self.months[0], cost=0, inflation=0.1, source=DataSource.API.value)
        p = Portfolio.objects.get(id=self.portfolio.id)
        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[0]]['InflatedCost'].item(), 1000)
        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[1]]['InflatedCost'].item(), 1001)
        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[2]]['InflatedCost'].item(), 1001)

        # Bought with inflated money!
        self.assertEqual(p.e_pd.loc[p.e_pd['Date'] == self.months[1]]['InflatedCost'].item(), 500)
        self.assertEqual(p.e_pd.loc[p.e_pd['Date'] == self.months[2]]['InflatedCost'].item(), 500)

        Inflation.objects.create(date=self.months[1], cost=0, inflation=0.2, source=DataSource.API.value)
        p = Portfolio.objects.get(id=self.portfolio.id)

        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[0]]['InflatedCost'].item(), 1000)
        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[1]]['InflatedCost'].item(), 1001)
        self.assertEqual(p.p_pd.loc[p.p_pd['Date'] == self.months[2]]['InflatedCost'].item(), 1003.002)

        # Bought with inflated money!
        self.assertEqual(p.e_pd.loc[p.e_pd['Date'] == self.months[1]]['InflatedCost'].item(), 500)
        self.assertEqual(p.e_pd.loc[p.e_pd['Date'] == self.months[2]]['InflatedCost'].item(), 501)

    @freeze_time("2022-02-02")
    def test_with_dividend(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        EquityEvent.objects.create(equity=self.equities[0], date=self.months[1], value=0.10, event_type='Dividend')
        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000, 'PD EffectiveCost')
        self.assertEqual(today_pd_series['Value'].item(), 500, 'PD Value')
        self.assertEqual(today_pd_series['TotalDividends'].item(), 5.0, 'PD Total Dividends')
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000, 'PD Inflated Cost')
        self.assertEqual(today_pd_series['Cash'].item(), 505, 'PD Cash')
        # EquityColumns = ['Date', 'Equity', 'Shares', 'Dividend', 'Price', 'Value', 'TotalDividends', 'EffectiveCost', 'InflatedCost']

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Equity'].item(), self.equities[0].symbol, 'EPD Symbol')
        self.assertEqual(today_ed_series['Shares'].item(), 50, 'EPD Shares')
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 10, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 500, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 5.0, 'EPD Total Dividends')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 500, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 500, 'EPD Inflated Cost')

    @freeze_time("2022-02-02")
    def test_equity_gain(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[2]).update(price=11)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000)
        self.assertEqual(today_pd_series['Value'].item(), 550)
        self.assertEqual(today_pd_series['TotalDividends'].item(), 0)
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000)
        self.assertEqual(today_pd_series['Cash'].item(), 500)

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Equity'].item(), self.equities[0].symbol)
        self.assertEqual(today_ed_series['Shares'].item(), 50)
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 11, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 550, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 0)
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 500)
        self.assertEqual(today_ed_series['InflatedCost'].item(), 500)

    @freeze_time("2022-03-02")
    def test_equity_sale(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[2]).update(price=11)
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[3]).update(price=11)
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[3],
                                   price=11, quantity=10, xa_action=Transaction.SELL)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['EffectiveCost'].item(), 1000)
        self.assertEqual(today_pd_series['Value'].item(), 440)
        self.assertEqual(today_pd_series['TotalDividends'].item(), 0)
        self.assertEqual(today_pd_series['InflatedCost'].item(), 1000)
        self.assertEqual(today_pd_series['Cash'].item(), 610)

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Equity'].item(), self.equities[0].symbol)
        self.assertEqual(today_ed_series['Shares'].item(), 40)
        self.assertEqual(today_ed_series['Dividend'].item(), 0, 'EPD Dividend')
        self.assertEqual(today_ed_series['Price'].item(), 11, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 440, 'EPD Value')
        self.assertEqual(today_ed_series['TotalDividends'].item(), 0)
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 390)
        self.assertEqual(today_ed_series['InflatedCost'].item(), 390)

    @freeze_time("2022-03-02")
    def test_equity_sale_loss(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[2]).update(price=11)
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[3]).update(price=11)
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[3],
                                   price=9, quantity=10, xa_action=Transaction.SELL)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['Value'].item(), 440)
        self.assertEqual(today_pd_series['Cash'].item(), 590)

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Price'].item(), 11, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 440, 'EPD Value')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 410, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 410, 'EPD Inflated Cost')

    @freeze_time("2022-03-02")
    def test_equity_sale_loss2(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[2]).update(price=10)
        EquityValue.objects.filter(equity=self.equities[0], date=self.months[3]).update(price=10)
        Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.months[3],
                                   price=9, quantity=10, xa_action=Transaction.SELL)

        today_pd_series = self.portfolio.p_pd.loc[self.portfolio.p_pd['Date'] == normalize_today()]
        self.assertEqual(today_pd_series['Value'].item(), 400)
        self.assertEqual(today_pd_series['Cash'].item(), 590)

        today_ed_series = self.portfolio.e_pd.loc[self.portfolio.e_pd['Date'] == normalize_today()]
        self.assertEqual(today_ed_series['Price'].item(), 10, 'EPD Price')
        self.assertEqual(today_ed_series['Value'].item(), 400, 'EPD Value')
        self.assertEqual(today_ed_series['EffectiveCost'].item(), 410, 'EPD Effective Cost')
        self.assertEqual(today_ed_series['InflatedCost'].item(), 410, 'EPD Inflated Cost')


class StaticValueTest(BasicSetup):
    def setUp(self):
        super().setUp()
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
            Inflation.objects.create(date=process, cost=0, inflation=inflation[r], source=DataSource.API.value)
            process = next_date(process)
        self.inflation: dict[date, float] = dict(Inflation.objects.all().values_list('date', 'inflation'))
        eq_values = ((1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3),
                     (2.1, 2.2, 2.3, 2.2, 2.1, 2.0, 1.9, 1.8, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3),
                     (3.1, 3.2, 3.3, 3.2, 3.1, 3.0, 2.9, 2.8, 2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 3.3))
        dv_values = (.25, 0, 0, 0, .25, 0, 0, 0, .25, 0, 0, 0, .25, 0, 0)
        process = self.start
        for r in range(self.months):
            for e in range(2):
                EquityValue.objects.create(equity=self.equities[e], date=process, price=eq_values[e][r])
                if e == 0:
                    EquityEvent.objects.create(equity=self.equities[e], date=process, value=dv_values[r],
                                               event_type='Dividend', source=DataSource.API.value)
                elif e == 2:
                    EquityEvent.objects.create(equity=self.equities[e], date=process, value=.1, event_type='Dividend',
                                               source=DataSource.API.value)

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
        Transaction.objects.create(portfolio=self.portfolio, date=self.start, value=100,
                                   price=0, quantity=0, xa_action=Transaction.FUND)

        t = Transaction.objects.create(portfolio=self.portfolio, equity=self.equities[0], date=self.start,
                                       xa_action=Transaction.BUY, price=1.1, quantity=10)
        self.assertEqual(t.value, 11, 'Unexpected value got %s expected 11' % t.value)  # 10 * 1.1


