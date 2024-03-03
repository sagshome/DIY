import logging
import os
import sys

from copy import deepcopy
from datetime import datetime, date
from freezegun import freeze_time
from unittest.mock import patch, mock_open, Mock

from django.test import TestCase, override_settings
from stocks.importers import QuestTrade, FUND, BUY, SELL, DIV, REDEEM, JUNK
from stocks.models import ExchangeRate, Inflation, Equity, EquityAlias, EquityEvent, EquityValue, Portfolio, Transaction, DataSource
from stocks.utils import normalize_date, next_date, last_date, normalize_today

logger = logging.getLogger(__name__)
DEFAULT_QUERY = {
    "Meta Data": {
        "1. Information": "Monthly Adjusted Prices and Volumes",
        "2. Symbol": "BCE.TRT",
        "3. Last Refreshed": "2021-01-15",
        "4. Time Zone": "US/Eastern"
    },
    "Monthly Adjusted Time Series": {
        "2020-12-31": {
            "1. open": "56.6600",
            "2. high": "58.6700",
            "3. low": "54.3100",
            "4. close": "54.4300",
            "5. adjusted close": "45.4614",
            "6. volume": "98974886",
            "7. dividend amount": "0.8325"
        },
        "2020-11-30": {
            "1. open": "53.8800",
            "2. high": "57.3750",
            "3. low": "52.5200",
            "4. close": "56.3000",
            "5. adjusted close": "46.3546",
            "6. volume": "49176318",
            "7. dividend amount": "0.0000"
        },
        "2020-10-30": {
            "1. open": "55.2700",
            "2. high": "56.8400",
            "3. low": "53.1850",
            "4. close": "53.5400",
            "5. adjusted close": "44.0822",
            "6. volume": "41046718",
            "7. dividend amount": "0.0000"
        },
        "2020-09-30": {
            "1. open": "56.0600",
            "2. high": "57.5100",
            "3. low": "54.4200",
            "4. close": "55.2200",
            "5. adjusted close": "45.4654",
            "6. volume": "83069227",
            "7. dividend amount": "0.8325"
        },
        "2020-08-31": {
            "1. open": "56.2800",
            "2. high": "58.2100",
            "3. low": "56.0500",
            "4. close": "56.0600",
            "5. adjusted close": "45.4822",
            "6. volume": "35434424",
            "7. dividend amount": "0.0000"
        },
        "2020-07-31": {
            "1. open": "56.6400",
            "2. high": "57.7000",
            "3. low": "54.3300",
            "4. close": "56.1600",
            "5. adjusted close": "45.5633",
            "6. volume": "32047363",
            "7. dividend amount": "0.0000"
        },
        "2020-06-30": {
            "1. open": "57.0000",
            "2. high": "60.1400",
            "3. low": "55.7900",
            "4. close": "56.6200",
            "5. adjusted close": "45.9365",
            "6. volume": "74705435",
            "7. dividend amount": "0.8325"
        },
        "2020-05-29": {
            "1. open": "55.9400",
            "2. high": "57.5800",
            "3. low": "53.2500",
            "4. close": "57.2300",
            "5. adjusted close": "45.7633",
            "6. volume": "39833587",
            "7. dividend amount": "0.0000"
        },
        "2020-04-30": {
            "1. open": "56.0600",
            "2. high": "59.3100",
            "3. low": "54.6900",
            "4. close": "56.2900",
            "5. adjusted close": "45.0116",
            "6. volume": "47054239",
            "7. dividend amount": "0.0000"
        },
        "2020-03-31": {
            "1. open": "59.4200",
            "2. high": "63.9000",
            "3. low": "46.0300",
            "4. close": "57.7300",
            "5. adjusted close": "46.1631",
            "6. volume": "126482836",
            "7. dividend amount": "0.8325"
        },
        "2020-02-28": {
            "1. open": "62.6800",
            "2. high": "65.2750",
            "3. low": "58.8750",
            "4. close": "58.9500",
            "5. adjusted close": "46.3657",
            "6. volume": "48102080",
            "7. dividend amount": "0.0000"
        },
        "2020-01-31": {
            "1. open": "60.2500",
            "2. high": "63.3900",
            "3. low": "59.2800",
            "4. close": "62.3600",
            "5. adjusted close": "49.0477",
            "6. volume": "30837083",
            "7. dividend amount": "0.0000"
        },
    }
}
DEFAULT_LOOKUP = {"bestMatches": [{"1. symbol": "BCE.TRT",
                                   "2. name": "MYE this is better Inc",
                                   "3. type": "Equity",
                                   "4. region": "Toronto",
                                   "5. marketOpen": "09:30",
                                   "6. marketClose": "16:00",
                                   "7. timezone": "UTC-05",
                                   "8. currency": "CAD",
                                   "9. matchScore": "1.0000"}]}
'''
{
    "bestMatches": [
        {
            "1. symbol": "BCE.TRT",
            "2. name": "BCE Inc",
            "3. type": "Equity",
            "4. region": "Toronto",
            "5. marketOpen": "09:30",
            "6. marketClose": "16:00",
            "7. timezone": "UTC-05",
            "8. currency": "CAD",
            "9. matchScore": "1.0000"
        }
    ]
}

{
    "bestMatches": []
}

{
    "bestMatches": [
        {
            "1. symbol": "B",
            "2. name": "Barnes Group Inc",
            "3. type": "Equity",
            "4. region": "United States",
            "5. marketOpen": "09:30",
            "6. marketClose": "16:00",
            "7. timezone": "UTC-04",
            "8. currency": "USD",
            "9. matchScore": "1.0000"
        },
        {
            "1. symbol": "B.TRV",
            "2. name": "BCM Resources Corp",
            "3. type": "Equity",
            "4. region": "Toronto Venture",
            "5. marketOpen": "09:30",
            "6. marketClose": "16:00",
            "7. timezone": "UTC-05",
            "8. currency": "CAD",
            "9. matchScore": "0.5000"
        },
        
'''


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

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'other_stub').process()

        self.assertEqual(Portfolio.objects.all().count(), 1, 'New Stub is ignored')
        self.assertEqual(this['EffectiveCost'].item(), 1000, 'ReImport does not process old records')
        self.assertEqual(p.last_import, datetime(2020,3,3).date(), 'ImportDate Not updated')

        data_text = [self.csv_header]
        data_text.append('2020-03-04 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type')

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'other_stub').process()

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

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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

        get.side_effect = [self.mock_lookup, self.mock_empty]
        with patch('builtins.open', mock_open(read_data='\n'.join(data))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()
            self.assertEqual(len(my_obj.equities), 2, 'Added one')


    @patch('requests.get')
    def test_equities_1(self, get):
        data = [self.csv_header, '2020-03-03 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x']
        get.side_effect = [self.mock_lookup, self.mock_empty]
        with patch('builtins.open', mock_open(read_data='\n'.join(data))):
            my_obj = QuestTrade('no_file', 'test')
            self.assertEqual(len(my_obj.equities), 0, 'Empty')
            my_obj.process()
            self.assertEqual(len(my_obj.equities), 1, 'Added one')

    @patch('requests.get')
    def test_equities_2(self, get):
        data = [self.csv_header,
                '2020-03-22 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x',
                '2020-03-23 12:00:00 AM,Buy,MYE.TO,x,BCE,50.0,10.0,-5.0,-505.0,CAD,123,Trades,x']
        get.side_effect = [self.mock_lookup, self.mock_empty]

        with patch('builtins.open', mock_open(read_data='\n'.join(data))):
            my_obj = QuestTrade('no_file', 'test')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(Equity.objects.count(), 1)
        e = Equity.objects.all()[0]
        p = Portfolio.objects.get(name='test_Type')
        t = Transaction.objects.get(portfolio=p, xa_action=Transaction.BUY)
        self.assertEqual(t.value, 505.0, 'Total value inluceds commission')
        self.assertEqual(t.price, 10.1, "Include commission in price")

        self.assertEqual(e.symbol, 'MYE.TRT', 'Set symbol to TRT')
        self.assertEqual(e.currency, 'CAD')
        self.assertEqual(e.region, 'TRT')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()
        self.assertEqual(Transaction.objects.count(), 2, 'Initial Transactions')

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()
        self.assertEqual(Transaction.objects.count(), 2, 'Initial extra BUYS')


    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_match_on_real_name(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-03 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-03-03 12:00:00 AM,Buy,MYF.TO,BAR,MY Equity2,10.0,10.0,-5.0,-105.0,USD,123,Trades,Type',
            '2020-04-03 12:00:00 AM,Buy,MYF.TO,BAR,MY Equity2,10.0,20.0,-5.0,-105.0,USD,123,Trades,Type',
            '2020-05-03 12:00:00 AM,Buy,MYF.TO,BAR,MY Equity2,10.0,15.0,-5.0,-105.0,USD,123,Trades,Type',
            '2020-03-06 12:00:00 AM,DIV,XXX.TO,,FOO Bar INC Div,0,0,0,5,USD,123,Dividends,Type',
            '2020-04-06 12:00:00 AM,DIV,XXX.TO,,FOO Bar INC Div,0,0,0,5,USD,123,Dividends,Type',
            '2020-05-06 12:00:00 AM,DIV,XXX.TO,,FOO Bar INC Div,0,0,0,5,USD,123,Dividends,Type',
            '2020-06-03 12:00:00 AM,Sell,MYF.TO,,MY Equity2,50.0,15.0,-5.0, 745.0,CAD,123,Trades,Type',
            '2020-06-23 12:00:00 AM,EFT,,ELECTRONIC FUND TRANSFER,0.0,0.0,0.0,0.0,-602.00,CAD,123,Withdrawals,Type',

        ]
        second_lookup = deepcopy(DEFAULT_LOOKUP)
        second_lookup["bestMatches"][0]["2. name"] = "FOO Bar INC"
        second_lookup["bestMatches"][0]["8. currency"] = "USD"
        mock2 = Mock()
        mock2.status_code = 200
        mock2.json.return_value = second_lookup

        get.side_effect = [self.mock_lookup, mock2, self.mock_query, self.mock_empty]

        e = Equity.objects.create(symbol='myf.trt', name='FOO Bar INC', equity_type='ETF',  validated=True,
                                  searchable=False, last_updated=datetime(2020, 3, 1).date())

        EquityValue.objects.create(equity=e, date=datetime(2020, 4, 1).date(), price=5,
                                   source=DataSource.API.value)
        EquityValue.objects.create(equity=e, date=datetime(2020, 5, 1).date(), price=6,
                                   source=DataSource.ESTIMATE.value)
        EquityValue.objects.create(equity=e, date=datetime(2020, 6, 1).date(), price=7,
                                   source=DataSource.UPLOAD.value)

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()

        self.assertEqual(Transaction.objects.count(), 7, 'Buy * 4, Sell, Fund, Withdraw')

        deposit = Transaction.objects.get(xa_action=Transaction.FUND)
        withdraw = Transaction.objects.get(xa_action=Transaction.REDEEM)
        sell = Transaction.objects.get(xa_action=Transaction.SELL)
        buy = Transaction.objects.filter(xa_action=Transaction.BUY)

        ev = EquityValue.objects.get(equity=e, date=datetime(2020, 4, 1).date())
        self.assertEqual(ev.price, 5, 'API is better source')
        self.assertEqual(ev.source, DataSource.API.value)
        ev = EquityValue.objects.get(equity=e, date=datetime(2020, 5, 1).date())
        self.assertEqual(ev.price, 20.5, 'Upload is better source')
        self.assertEqual(ev.source, DataSource.UPLOAD.value)
        ev = EquityValue.objects.get(equity=e, date=datetime(2020, 6, 1).date())
        self.assertEqual(ev.price, 7, 'Keep original Upload')
        self.assertEqual(ev.source, DataSource.UPLOAD.value)

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
            my_obj.process()
        self.assertEqual(Transaction.objects.count(), 7, 'Nothing New')

        self.assertEqual(deposit.value, 1000.0)
        self.assertEqual(withdraw.value, -602.0)
        self.assertEqual(sell.value, -755.0)
        self.assertEqual(sell.price, 15.1, 'Includes commission')
        self.assertEqual(sell.quantity, -50.0)

    @freeze_time('2020-09-01')
    @patch('requests.get')
    def test_buy_and_sell(self, get):
        data_text = [
            self.csv_header,
            '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type',
            '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type',
            '2020-05-20 12:00:00 AM,Sell,MYE.TO,,MY Equity,-10.0,20.0,-5.0,195.0,CAD,123,Trades,Type'

        ]
        get.side_effect = [self.mock_lookup, self.mock_empty]

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertRaises(Exception) as context:
                my_obj = QuestTrade('no_file', 'test')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            my_obj = QuestTrade('no_file', 'test')
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
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')
                self.assertEqual(len(captured.records), 1, 'Quiet with no date')
                self.assertEqual(captured.records[0].levelname, 'DEBUG', 'Error only with DEBUG')
                self.assertTrue(captured.records[0].msg.startswith('Invalid date 2020-fish-03'), 'Error in log')

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')

        data_text = [self.csv_header,
                    ',CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')

        data_text = [self.csv_header,
                     '2020-03-03 12:00:00 AM,CON,,BAR,desc,0.00000,0.00000000,0.00,1000.00,CAD,123,Deposits,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')

    def test_parsing_price(self):
        """
        Three columns used in price,  Price (10) Quantity (50) and Fees (-5)
        if quantity or fees do not convert just use price
        :return:
        """
        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Trades,Type']

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 10.1, 'Price incluces commission')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10,-5.0,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 10.1, 'Integers are ok')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,foo,-5.0,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 0, 'Try that')
                self.assertEqual(len(captured.records), 1, 'Log an error')
                self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
                self.assertTrue(captured.records[0].msg.startswith('Could not convert price'), 'Error in log')


        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,bar,foo,-5.0,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 0, 'Try that')
                self.assertEqual(len(captured.records), 2, 'Log an error')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,bar,10,-5.0,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 10, 'Try that')
                self.assertEqual(len(captured.records), 2, 'Log an error (twice!)')
                self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
                self.assertTrue(captured.records[0].msg.startswith('Failed to convert Quantity'), 'Error in log')
                self.assertEqual(captured.records[0].msg, captured.records[1].msg, 'Hit twice with QT')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,,10,-5.0,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Price'], 10, 'Try that')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50,10,-bar,-505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
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

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Amount'], -505.0, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,0,CAD,123,Trades,Type']

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Amount'], 0, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,,CAD,123,Trades,Type']

        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['Amount'], 0, 'Amount')


        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,Foo,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
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
            (BUY, '2020-03-06 12:00:00 AM,DIS,MYE.TO,BAR,MY Equity,50.0,0,0,0,CAD,123,Dividends,Type'),
            (SELL, '2020-03-06 12:00:00 AM,Sell,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,495.0,CAD,123,Trades,Type'),
            (DIV, '2020-03-06 12:00:00 AM,DIV,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,Dividends,Type'),

            (JUNK, '2020-03-06 12:00:00 AM,Buy,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,-505.0,CAD,123,FX conversion,Type'),

        )

        # Test blue sky results
        for result, data in clean_data:
            data_text = [self.csv_header, data]
            with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
                with self.assertNoLogs(level='DEBUG') as captured:
                    my_obj = QuestTrade('no_file', 'test')
                    self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                    self.assertEqual(my_obj.pd.iloc[0]['XAType'], result, data)

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Sell,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertNoLogs(level='DEBUG') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['XAType'], Transaction.SELL, 'Amount')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Foo,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,Trades,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 1, 'Record Processed')
                self.assertEqual(my_obj.pd.iloc[0]['XAType'], JUNK, 'Invalid Record')
                self.assertEqual(len(captured.records), 1, 'Log an error')
                self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
                self.assertTrue(captured.records[0].msg.startswith('Unexpected XA value'), 'Error in log')

        data_text = [self.csv_header,
                     '2020-03-06 12:00:00 AM,Foo,MYE.TO,BAR,MY Equity,50.0,10.0,-5.0,505.0,CAD,123,FOO,Type']
        with patch('builtins.open', mock_open(read_data='\n'.join(data_text))):
            with self.assertLogs(level='ERROR') as captured:
                my_obj = QuestTrade('no_file', 'test')
                self.assertEqual(len(my_obj.pd), 0, 'Record Skipped')
                self.assertEqual(len(captured.records), 1, 'Log an error')
                self.assertEqual(captured.records[0].levelname, 'ERROR', 'Error')
                self.assertTrue(captured.records[0].msg.startswith('Unexpected XA value'), 'Error in log')
