import csv
import logging
import os
import sys

from copy import deepcopy
from datetime import datetime, date
from freezegun import freeze_time
from unittest.mock import patch, mock_open, Mock

from django.test import TestCase, override_settings
from stocks.importers import QuestTrade, FUND, BUY, SELL, DIV, REDEEM, JUNK, SPLIT
from stocks.models import ExchangeRate, Inflation, Equity, EquityAlias, EquityEvent, EquityValue, Portfolio, Transaction, DataSource
from stocks.utils import normalize_date, next_date, last_date, normalize_today
from stocks.testing.setup import DEFAULT_QUERY, DEFAULT_LOOKUP

logger = logging.getLogger(__name__)

class BasicSetup(TestCase):

    current = datetime(2020,9,1).date()

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.current = datetime(2020, 9, 1).date()
        self.csv_header = 'Settlement Date,Action,Symbol,FOO,Description,Quantity,Price,Commission,Net Amount,Currency,Account #,Activity Type,Account Type'
        #                 '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,5.0,-505.0,CAD,123,Trades,Type'
        self.mock_lookup = Mock()
        self.mock_lookup.status_code = 200
        self.mock_lookup.json.return_value = DEFAULT_LOOKUP
        self.mock_query = Mock()
        self.mock_query.status_code = 200
        self.mock_query.json.return_value = DEFAULT_QUERY
        self.mock_empty = Mock()
        self.mock_empty.status_code = 200
        self.mock_empty.json.return_value = {}
        self.mock_error = Mock()
        self.mock_error.status_code = 500

    @freeze_time('2020-09-01')
    def test_funding(self):
        data_text = [self.csv_header]
        data_text.append('2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type')

        #with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
        my_obj = QuestTrade(csv.reader(data_text), 'test')
        self.assertNotIn('FOO', my_obj.headers, 'Skip unneeded column')
        self.assertIn('Action', my_obj.headers, 'Ensure extra column is added')
        self.assertFalse(my_obj.managed, 'Default managed setting')
        self.assertEqual(len(my_obj.pd), 1, 'PD created with initial funding')
        self.assertEqual(my_obj.pd.iloc[0]['XAType'], Transaction.FUND, 'Funding record parsed')
        self.assertEqual(my_obj.pd.iloc[0]['Amount'], 1000.0, 'Funding amount parsed')
        my_obj.process()

        p = Portfolio.objects.get(name='test_Type')
        self.assertEqual(len(p.p_pd), 6)

        this = p.p_pd.loc[p.p_pd['Date'] == datetime(2020,9,1).date()]
        self.assertEqual(this['EffectiveCost'].item(), 1000)
        self.assertEqual(p.last_import, datetime(2020,3,3).date(), 'Import Date test')
        self.assertEqual(Transaction.objects.all().count(), 1)
        this_xa: Transaction = Transaction.objects.all()[0]
        this_xa.portfolio = p
        self.assertEqual(this_xa.xa_action, Transaction.FUND)
        self.assertEqual(this_xa.value, 1000)

        my_obj = QuestTrade(csv.reader(data_text), 'other_stub')

        self.assertEqual(Portfolio.objects.all().count(), 1, 'New Stub is ignored')
        self.assertEqual(this['EffectiveCost'].item(), 1000, 'ReImport does not process old records')
        self.assertEqual(p.last_import, datetime(2020,3,3).date(), 'ImportDate Not updated')

        data_text = [self.csv_header]
        data_text.append('2020-03-04 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type')

        my_obj = QuestTrade(csv.reader(data_text), 'other_stub').process()

        self.assertEqual(Portfolio.objects.all().count(), 1, 'New Stub is ignored')

        p = Portfolio.objects.get(name='test_Type')
        this = p.p_pd.loc[p.p_pd['Date'] == datetime(2020,9,1).date()]

        self.assertEqual(this['EffectiveCost'].item(), 2000, 'ReImport finds new records')
        self.assertEqual(p.last_import, datetime(2020,3,4).date(), 'ImportDate updated')

    @freeze_time('2020-09-01')
    def test_deposit2(self):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type'
        ]

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        self.assertEqual(len(my_obj.pd), 2, 'PD double fimded with initial funding')
        self.assertEqual(my_obj.pd.iloc[0]['XAType'], Transaction.FUND, 'Funding record parsed')
        self.assertEqual(my_obj.pd.iloc[0]['Amount'], 1000.0, 'Funding amount parsed')
        self.assertEqual(my_obj.pd.iloc[1]['XAType'], Transaction.FUND, 'Funding record parsed')
        self.assertEqual(my_obj.pd.iloc[1]['Amount'], 1000.0, 'Funding amount parsed')
        my_obj.process()

        p = Portfolio.objects.get(name='test_Type')
        this = p.p_pd.loc[p.p_pd['Date'] == datetime(2020,9,1).date()]
        self.assertEqual(this['EffectiveCost'].item(), 2000)
        self.assertEqual(Transaction.objects.all().count(), 2)

    @freeze_time('2020-09-01')
    def test_blank_line(self):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '',
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type'
        ]

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        self.assertEqual(len(my_obj.pd), 2, 'PD double fimded with initial funding')
        self.assertEqual(my_obj.pd.iloc[0]['XAType'], Transaction.FUND, 'Funding record parsed')
        self.assertEqual(my_obj.pd.iloc[0]['Amount'], 1000.0, 'Funding amount parsed')
        self.assertEqual(my_obj.pd.iloc[1]['XAType'], Transaction.FUND, 'Funding record parsed')
        self.assertEqual(my_obj.pd.iloc[1]['Amount'], 1000.0, 'Funding amount parsed')

    @patch('requests.get')
    def test_lookups_1(self, get):
        """
        When I use the API,  it will return a different discription.    I should make an alias with both the
        csv description and the real description.
        :param get:
        :return:
        """
        data = [self.csv_header,
                '2020-03-03 12:00:00 AM,Buy,BCE.TO,x,The BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x',
                '2020-03-06 12:00:00 AM,DIV,XXX.TO,,The BCE Dividend,0,0,0,5,CAD,123,Dividends,Type',
                '2020-04-06 12:00:00 AM,DIV,XXX.TO,,The BCE Dividend,0,0,0,5,CAD,123,Dividends,Type']

        get.side_effect = [self.mock_lookup, self.mock_empty, self.mock_empty]
        my_obj = QuestTrade(csv.reader(data), 'test')
        my_obj.process()
        self.assertEqual(len(my_obj.equities), 2, 'Added one')


    @patch('requests.get')
    def test_equities_1(self, get):
        data = [self.csv_header, '2020-03-03 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x']
        get.side_effect = [self.mock_lookup, self.mock_empty, self.mock_empty]
        my_obj = QuestTrade(csv.reader(data), 'test')
        self.assertEqual(len(my_obj.equities), 0, 'Empty')
        my_obj.process()
        self.assertEqual(len(my_obj.equities), 1, 'Added one')

    @patch('requests.get')
    def test_equities_2(self, get):
        data = [self.csv_header,
                '2020-03-22 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x',
                '2020-03-23 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x']
        get.side_effect = [self.mock_lookup, self.mock_empty, self.mock_empty]

        my_obj = QuestTrade(csv.reader(data), 'test')
        self.assertEqual(len(my_obj.equities), 0, 'Empty')
        my_obj.process()
        self.assertEqual(len(my_obj.equities), 1, 'Added just one')

    @patch('requests.get')
    def test_XAs(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type'
            '2020-03-04 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type'
        ]
        get.side_effect = [self.mock_lookup, self.mock_query]
        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(Equity.objects.count(), 1)
        e = Equity.objects.all()[0]
        p = Portfolio.objects.get(name='test_Type')
        t = Transaction.objects.get(portfolio=p, xa_action=Transaction.BUY)
        self.assertEqual(t.value, 505.0, 'Total value inluceds commission')
        self.assertEqual(t.price, 10.1, "Include commission in price")

        self.assertEqual(e.symbol, 'MYE', 'Set symbol')
        self.assertEqual(e.key, 'MYE.TRT', 'Key includes code for canada')
        self.assertEqual(e.currency, 'CAD')
        self.assertEqual(e.region, 'Canada')
        self.assertEqual(e.name, 'MYE this is better Inc', 'Name from API')
        self.assertTrue(e.validated)
        self.assertTrue(e.searchable)

    @patch('requests.get')
    def test_rebuy1(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type'
        ]
        get.side_effect = [self.mock_lookup, self.mock_query]
        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()
        self.assertEqual(Transaction.objects.count(), 2, 'Initial Transactions')

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()
        self.assertEqual(Transaction.objects.count(), 2, 'Initial extra BUYS')

    @freeze_time('2022-12-01')
    @patch('requests.get')
    def test_import_split_fail(self, get):
        data = [
            'Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,Commission,Net Amount,Currency,Account #,Activity Type,Account Type',
            '2019-04-29 12:00:00 AM,2019-04-29 12:00:00 AM,DIV,.CM,CANADIAN IMPERIAL BANK OF COMMERCE CASH ,0.00000,0.00000000,0.00,0.00,109.20,CAD,8,Dividends,k',
            '2022-05-18 12:00:00 AM,2022-05-18 12:00:00 AM,DIS,CM,CANADIAN IMPERIAL BANK OF COMMERCE STK SPLIT,203.00000,0.00000000,0.00,0.00,0.00,CAD,8,Dividends,k',
            '2022-01-05 12:00:00 AM,2022-01-07 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,53.00000,150.84000000,-7994.52,-5.14,-7999.66,CAD,8,Trades,k',
            '2020-09-18 12:00:00 AM,2020-09-22 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,72.00000,102.47000000,-7377.84,-5.20,-7383.04,CAD,8,Trades,k',
            '2019-01-07 12:00:00 AM,2019-01-09 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,78.00000,103.60000000,-8080.80,-5.22,-8086.02,CAD,8,Trades,k',
        ]

        get.side_effect = [self.mock_empty]
        my_obj = QuestTrade(csv.reader(data), 'test')
        my_obj.process()
        self.assertEqual(Equity.objects.count(), 1,
                         'Different symbol on Dividends, DIS should be ignored')
        self.assertEqual(len(my_obj.warnings), 1, 'Split ignored')

    @freeze_time('2022-12-01')
    @patch('requests.get')
    def test_import_nostub_fail(self, get):
        data = [
            'Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,Commission,Net Amount,Currency,Account #,Activity Type,Account Type',
            '2019-04-29 12:00:00 AM,2019-04-29 12:00:00 AM,DIV,.CM,CANADIAN IMPERIAL BANK OF COMMERCE CASH ,0.00000,0.00000000,0.00,0.00,109.20,CAD,8,Dividends,k',
            '2022-05-18 12:00:00 AM,2022-05-18 12:00:00 AM,DIS,CM,CANADIAN IMPERIAL BANK OF COMMERCE STK SPLIT,203.00000,0.00000000,0.00,0.00,0.00,CAD,8,Dividends,k',
            '2022-01-05 12:00:00 AM,2022-01-07 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,53.00000,150.84000000,-7994.52,-5.14,-7999.66,CAD,8,Trades,k',
            '2020-09-18 12:00:00 AM,2020-09-22 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,72.00000,102.47000000,-7377.84,-5.20,-7383.04,CAD,8,Trades,k',
            '2019-01-07 12:00:00 AM,2019-01-09 12:00:00 AM,Buy,CM.TO,CANADIAN IMPERIAL BANK OF COMMERCE WE ,78.00000,103.60000000,-8080.80,-5.22,-8086.02,CAD,8,Trades,k',
        ]

        get.side_effect = [self.mock_empty]
        my_obj = QuestTrade(csv.reader(data), None)
        my_obj.process()
        self.assertEqual(Portfolio.objects.count(), 1,
                         'Only one portfolio created')
        p = Portfolio.objects.all()[0]
        self.assertEqual(p.name, 'k', 'No STUB value expected')

    @freeze_time('2020-12-01')
    @patch('requests.get')
    def test_import_search_fail(self, get):
        data = [
            'Transaction Date,Settlement Date,Action,Symbol,Description,Quantity,Price,Gross Amount,Commission,Net Amount,Currency,Account #,Activity Type,Account Type',
            '2020-09-15 12:00:00 AM,2020-09-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,23.44,CAD,7,Dividends,m',
            '2020-08-14 12:00:00 AM,2020-08-14 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,23.44,CAD,7,Dividends,m',
            '2020-07-15 12:00:00 AM,2020-07-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,23.44,CAD,7,Dividends,m',
            '2020-06-15 12:00:00 AM,2020-06-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,23.44,CAD,7,Dividends,m',
            '2020-05-15 12:00:00 AM,2020-05-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,23.44,CAD,7,Dividends,m',
            '2020-04-15 12:00:00 AM,2020-04-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2020-03-16 12:00:00 AM,2020-03-16 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2020-02-14 12:00:00 AM,2020-02-14 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2020-01-15 12:00:00 AM,2020-01-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2019-12-16 12:00:00 AM,2019-12-16 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2019-11-15 12:00:00 AM,2019-11-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2019-10-15 12:00:00 AM,2019-10-15 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2019-09-16 12:00:00 AM,2019-09-16 12:00:00 AM,DIV,H034682,INTER PIPELINE LTD,0,0,0,0,83.51,CAD,7,Dividends,m',
            '2020-09-16 12:00:00 AM,2020-09-18 12:00:00 AM,Sell,IPL.TO,INTER PIPELINE LTD,-286,13.9634965,3993.56,-5.95,3987.61,CAD,7,Trades,m',
            '2020-09-16 12:00:00 AM,2020-09-18 12:00:00 AM,Sell,IPL.TO,INTER PIPELINE LTD,-300,13.96,4188,-1.96,4186.04,CAD,7,Trades,m',
            '2019-07-29 12:00:00 AM,2019-07-31 12:00:00 AM,Buy,IPL.TO,INTER PIPELINE LTD,300,22.16,-6648,-1.05,-6649.05,CAD,7,Trades,m',
            '2019-07-29 12:00:00 AM,2019-07-31 12:00:00 AM,Buy,IPL.TO,INTER PIPELINE LTD,186,22.15731183,-4121.26,-5.6,-4126.86,CAD,7,Trades,m',
            '2019-07-29 12:00:00 AM,2019-07-31 12:00:00 AM,Buy,IPL.TO,INTER PIPELINE LTD,100,22.16,-2216,-1.26,-2217.26,CAD,7,Trades,m',
        ]

        get.side_effect = [self.mock_empty]
        my_obj = QuestTrade(csv.reader(data), 'test')
        my_obj.process()
        self.assertEqual(EquityValue.objects.filter(source=DataSource.UPLOAD.value).count(), 2,
                         '0 Div value ignored')
        self.assertEqual(EquityValue.objects.filter(source=DataSource.ESTIMATE.value).count(), 15,
                         'Estimate the rest')

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_equity_alias(self, get):
        'MYE this is better Inc'
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,POWER CORP OF CANADA SUB-VTG WE ACTED AS AGENT,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-03-03 12:00:00 AM,Buy,MYF,BAR,BCE INC COM WE ACTED AS AGENT AVG ,10.0,10.0,-5.0,-105.0,USD,123,Trades,Type',
            '2020-03-03 12:00:00 AM,Buy,MYF.TO,BAR,BCE INC COM WE ACTED AS AGENT AVG ,10.0,10.0,-5.0,-105.0,CAD,123,Trades,Type',
            '2020-03-06 12:00:00 AM,DIV,XXX.TO,,POWER CORP OF CANADA SUB-VTG NEW CASH DIV ON 368  Div,0,0,0,5,CAD,123,Dividends,Type',
            '2020-04-06 12:00:00 AM,DIV,.BCE.TO,,BCE INC COM NEW CASH DIV ON 368 ,0,0,0,5,CAD,123,Dividends,Type',
            ]

        second_lookup = deepcopy(DEFAULT_LOOKUP)
        second_lookup["bestMatches"][0]["2. name"] = "BCE Inc Com"
        second_lookup["bestMatches"][0]["8. currency"] = "USD"
        mock2 = Mock()
        mock2.status_code = 200
        mock2.json.return_value = second_lookup

        third_lookup = deepcopy(DEFAULT_LOOKUP)
        third_lookup["bestMatches"][0]["2. name"] = "BCE Com"
        third_lookup["bestMatches"][0]["8. currency"] = "CAD"
        mock3 = Mock()
        mock3.status_code = 200
        mock3.json.return_value = third_lookup

        get.side_effect = [self.mock_lookup, self.mock_query, mock2, self.mock_query, mock3, self.mock_query]

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        self.assertEqual(EquityAlias.objects.count(), 3, '3 alias records')
        self.assertEqual(EquityAlias.objects.filter(symbol__startswith='MYF.').count(), 2, '2 for MYF')
        self.assertEqual(Equity.objects.count(), 3, 'Only three records')
        self.assertEqual(Equity.objects.filter(symbol='MYF').count(), 2, '2 MYFs')

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_buy_and_sell(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-05-20 12:00:00 AM,Sell,MYE.TO,,MY Equity,-10.0,20.0,-5.0,195.0,CAD,123,Trades,Type'

        ]
        get.side_effect = [self.mock_lookup, self.mock_empty, self.mock_empty]

        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        self.assertEqual(Transaction.objects.count(), 3)
        p = Portfolio.objects.get(name='test_Type')
        t = Transaction.objects.get(portfolio=p, xa_action=Transaction.SELL)
        self.assertEqual(t.value, -195, 'Total value inluceds commission')
        self.assertEqual(t.price, 19.5, "Include commission in price")
        e = EquityValue.objects.get(date=datetime(2020,4,1).date())
        self.assertEqual(e.price, 10.1)
        self.assertEqual(e.source, DataSource.UPLOAD.value)
        e = EquityValue.objects.get(date=datetime(2020,6,1).date())
        self.assertEqual(e.price, 19.5)
        self.assertEqual(e.source, DataSource.UPLOAD.value)
        e = EquityValue.objects.get(date=datetime(2020,5,1).date())
        self.assertEqual(e.price, 14.8)
        self.assertEqual(e.source, DataSource.ESTIMATE.value)
        e = EquityValue.objects.get(date=datetime(2020,7,1).date())
        self.assertEqual(e.price, 19.5)
        self.assertEqual(e.source, DataSource.ESTIMATE.value)

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_div_api(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-03-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
            '2020-04-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
            '2020-05-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
        ]
        get.side_effect = [self.mock_lookup, self.mock_query]
        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(EquityEvent.objects.count(), 4, 'API is used,  not the upload')
        e = Equity.objects.all()[0]
        self.assertTrue(e.validated)
        self.assertTrue(e.searchable)
        p = Portfolio.objects.get(name='test_Type')
        self.assertFalse(EquityEvent.objects.filter(date=datetime(2020,6,1).date()).exists())
        self.assertTrue(EquityEvent.objects.filter(date=datetime(2020,7,1).date()).exists())
        ev = EquityEvent.objects.get(date=datetime(2020,7,1).date())
        self.assertEqual(ev.equity, e)
        self.assertEqual(ev.value, 0.8325)
        self.assertEqual(ev.event_type, 'Dividend')
        self.assertEqual(ev.source, DataSource.API.value)

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_div_bad(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-03-06 12:00:00 AM,DIV,OTHER,,Other Equity,0,0,0,5,CAD,123,Dividends,Type',
        ]
        get.side_effect = [self.mock_lookup, self.mock_query]
        with self.assertRaises(Exception) as context:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            my_obj.process()
            self.assertEqual(str(context.exception), "Failed to lookup OTHER - Other Equity")

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_div_upload(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-03-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
            '2020-04-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
            '2020-05-06 12:00:00 AM,DIV,MYE.TO,,MY Equity,0,0,0,5,CAD,123,Dividends,Type',
        ]
        get.side_effect = [self.mock_empty, self.mock_empty]
        my_obj = QuestTrade(csv.reader(data_text), 'test')
        my_obj.process()

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(EquityEvent.objects.count(), 3, 'API is used,  not the upload')
        self.assertTrue(EquityEvent.objects.filter(date=datetime(2020,6,1).date()).exists())
        self.assertFalse(EquityEvent.objects.filter(date=datetime(2020,7,1).date()).exists())
        ev = EquityEvent.objects.get(date=datetime(2020,6,1).date())
        e = Equity.objects.all()[0]
        self.assertTrue(e.validated)
        self.assertFalse(e.searchable)
        p = Portfolio.objects.get(name='test_Type')
        self.assertEqual(ev.equity, e)
        self.assertEqual(ev.value, 0.1)
        self.assertEqual(ev.event_type, 'Dividend')
        self.assertEqual(ev.source, DataSource.UPLOAD.value)


class ParsingQT(TestCase):

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.csv_header = 'Settlement Date,Action,Symbol,FOO,Description,Quantity,Price,Commission,Net Amount,Currency,Account #,Activity Type,Account Type'
        #                 '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,5.0,-505.0,CAD,123,Trades,Type'

    def test_parsing_date(self):
        data_text = [self.csv_header,
                     '2020-fish-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type']
        with self.assertLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')
            self.assertEqual(len(captured.records), 1, 'Quiet with no date')
            self.assertEqual(captured.records[0].levelname, 'DEBUG', 'Error only with DEBUG')
            self.assertTrue(captured.records[0].msg.startswith('Invalid date 2020-fish-03'), 'Error in log')

        with self.assertNoLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')

        data_text = [self.csv_header,
                    ',CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type']
        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')

        data_text = [self.csv_header,
                     '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type']
        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')

    def test_parsing_price(self):
        """
        Three columns used in price,  Price (10) Quantity (50) and Fees (-5)
        if quantity or fees do not convert just use price
        :return:
        """
        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type']

        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 10.1, 'Price incluces commission')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10,-5.0,-505.0,CAD,123,Trades,Type']
        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 10.1, 'Integers are ok')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,foo,-5.0,-505.0,CAD,123,Trades,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 0, 'Try that')
            self.assertEqual(len(captured.records), 1, 'Log an error')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Could not convert price'), 'Error in log')


        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,bar,foo,-5.0,-505.0,CAD,123,Trades,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 0, 'Try that')
            self.assertEqual(len(captured.records), 2, 'Log an error')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,bar,10,-5.0,-505.0,CAD,123,Trades,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 10, 'Try that')
            self.assertEqual(len(captured.records), 2, 'Log an error (twice!)')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Failed to convert Quantity'), 'Error in log')
            self.assertEqual(captured.records[0].msg, captured.records[1].msg, 'Hit twice with QT')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,,10,-5.0,-505.0,CAD,123,Trades,Type']
        with self.assertNoLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 10, 'Try that')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50,10,-bar,-505.0,CAD,123,Trades,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Price'], 10, 'Try that')
            self.assertEqual(len(captured.records), 1, 'Log an error')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Could not convert commission'), 'Error in log')

    def test_parsing_amount(self):
        """
        Three columns used in price,  Price (10) Quantity (50) and Fees (-5)
        if quantity or fees do not convert just use price
        :return:
        """
        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type']

        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Amount'], -505.0, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,0,CAD,123,Trades,Type']

        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Amount'], 0, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,,CAD,123,Trades,Type']

        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Amount'], 0, 'Amount')


        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,Foo,CAD,123,Trades,Type']
        with self.assertLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['Amount'], 0, 'Amount')
            self.assertEqual(len(captured.records), 1, 'Log an error')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Failed to convert Amount'), 'Error in log')

    def test_parsing_xa_type(self):
        """
        Three columns used in price,  Price (10) Quantity (50) and Fees (-5)
        if quantity or fees do not convert just use price
        :return:
        """
        clean_data = (
            (FUND, '2020-03-06 12:00:00 AM,DEP,,BAR,desc,0,0,0,505.0,CAD,123,Deposit,Type'),
            (FUND, '2020-03-06 12:00:00 AM,CON,,BAR,desc,0,0,0,505.0,CAD,123,Deposit,Type'),
            (FUND, '2020-03-06 12:00:00 AM,FCH,,BAR,desc,0,0,0,505.0,CAD,123,Fees and rebates,Type'),
            (REDEEM, '2020-03-06 12:00:00 AM,FCH,,BAR,desc,0,0,0,-505.0,CAD,123,Fees and rebates,Type'),
            (FUND, '2020-03-06 12:00:00 AM,TFO,,BAR,desc,0,0,0,505.0,CAD,123,Transfers,Type'),
            (FUND, '2020-03-06 12:00:00 AM,TF6,,BAR,desc,0,0,0,505.0,CAD,123,Transfers,Type'),
            (FUND, '2020-03-06 12:00:00 AM,FED,,BAR,desc,0,0,0,505.0,CAD,123,Other,Type'),
            (REDEEM, '2020-03-06 12:00:00 AM,HST,,BAR,desc,0,0,0,-505.0,CAD,123,Other,Type'),
            (REDEEM, '2020-03-06 12:00:00 AM,CON,,BAR,desc,0,0,0,-505.0,CAD,123,Withdrawals,Type'),
            (REDEEM, '2020-03-06 12:00:00 AM,EFT,,BAR,desc,0,0,0,-505.0,CAD,123,Withdrawals,Type'),
            (REDEEM, '2020-03-06 12:00:00 AM,WDR,,BAR,desc,0,0,0,-505.0,CAD,123,Withdrawals,Type'),

            (BUY, '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type'),
            (SPLIT, '2020-03-06 12:00:00 AM,DIS,MYE.TO,BAR,MY Equity,50.0,0,0,0,CAD,123,Dividends,Type'),
            (SELL, '2020-03-06 12:00:00 AM,Sell,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,495.0,CAD,123,Trades,Type'),
            (DIV, '2020-03-06 12:00:00 AM,DIV,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Dividends,Type'),

            # (JUNK, '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,FX conversion,Type'),

        )

        # Test blue sky results
        for result, data in clean_data:
            data_text = [self.csv_header, data]
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade(csv.reader(data_text), 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['XAType'], result, data)

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Sell,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,Trades,Type']
        with self.assertNoLogs(level='DEBUG') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')

            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['XAType'], Transaction.SELL, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Foo,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,Trades,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
            self.assertEqual(my_obj.pd.iloc[0]['XAType'], JUNK, 'Invalid Record')
            self.assertEqual(len(captured.records), 1, 'Log an error')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Unexpected XA value'), 'Error in log')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Foo,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,FOO,Type']
        with self.assertLogs(level='ERROR') as captured:
            my_obj = QuestTrade(csv.reader(data_text), 'test')
            self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')
            self.assertEqual(len(captured.records), 1, 'Log an error')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
            self.assertTrue(captured.records[0].msg.startswith('Unexpected XA value'), 'Error in log')
