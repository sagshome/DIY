import logging
import numpy as np
import pandas as pd

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from unittest.mock import patch
from pandas import Timestamp

from django.test import TestCase, override_settings
from django.contrib.auth.models import User

from stocks.models import ExchangeRate, Inflation, Equity, EquityEvent, EquityValue, Account, Transaction, DataSource, Portfolio
from base.models import Profile

from base.utils import normalize_date, next_date, normalize_today

logger = logging.getLogger(__name__)


@override_settings(NO_CACHE=True)
class BasicSetup(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(username='test', is_superuser=False, is_staff=False, is_active=True)
        self.equities = [
            Equity.objects.create(symbol='CETF.TO', name='Eq CAN_ETF', equity_type='Equity',region='Canada', currency='CAD', searchable=False, validated=True),
            Equity.objects.create(symbol='USEQ', name='Eq US_EQUITY', equity_type='Equity', region='US', currency='USD', searchable=False, validated=True),
        ]
        self.account = Account.objects.create(name="test001", user=self.user, account_type='Investment', currency='CAD', account_name='Bar_007', managed=True)
        self.months = [datetime(2022, 1, 1).date(), datetime(2022, 2, 1).date(),
                       datetime(2022, 3, 1).date(), datetime(2022, 4, 1).date(),
                       datetime(2022, 5, 1).date(), datetime(2022, 6, 1).date(),
                       ]

        self.exchange_rates = [{'us_to_can': 1.2719, 'can_to_us': 0.7862}, {'us_to_can': 1.2698, 'can_to_us': 0.7875},
                               {'us_to_can': 1.2496, 'can_to_us': 0.8003}, {'us_to_can': 1.2792, 'can_to_us': 0.7817},
                               {'us_to_can': 1.2648, 'can_to_us': 0.7906}, {'us_to_can': 1.2886, 'can_to_us': 0.776}]

        self.inflation = [{'cost': 145.3, 'inflation': 0.9027777777777857}, {'cost': 146.8, 'inflation': 1.032346868547832},
                          {'cost': 148.9, 'inflation': 1.430517711171658}, {'cost': 149.8, 'inflation': 0.6044325050369413},
                          {'cost': 151.9, 'inflation': 1.4018691588785008}, {'cost': 152.9, 'inflation': 0.6583278472679394}]
        index = 0
        for month in self.months:
            EquityValue.objects.create(equity=self.equities[0], real_date=month, price=10, source=DataSource.API.value)
            EquityValue.objects.create(equity=self.equities[1], real_date=month, price=20, source=DataSource.API.value)

            ExchangeRate.objects.create(date=month, us_to_can=self.exchange_rates[index]['us_to_can'], can_to_us=self.exchange_rates[index]['can_to_us'])
            Inflation.objects.create(date=month, cost=self.inflation[index]['cost'], inflation=self.inflation[index]['inflation'])
            index += 1

        EquityEvent.objects.create(real_date=self.months[1], equity=self.equities[0], value='0.05', event_type='Dividend', source=DataSource.API.value)
        EquityEvent.objects.create(real_date=self.months[4], equity=self.equities[0], value='0.05', event_type='Dividend', source=DataSource.API.value)

        Transaction.objects.create(account=self.account, real_date=self.months[0], value=1000, xa_action=Transaction.FUND)
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[1], price=10, quantity=50, xa_action=Transaction.BUY)

        self.pd_starting_dict = {
            'Date': {0: Timestamp('2022-01-01 00:00:00'),
                     1: Timestamp('2022-02-01 00:00:00'),
                     2: Timestamp('2022-03-01 00:00:00'),
                     3: Timestamp('2022-04-01 00:00:00'),
                     4: Timestamp('2022-05-01 00:00:00'),
                     5: Timestamp('2022-06-01 00:00:00')},
            'Funds': {0: 1000, 1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000},
            'Redeemed': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            'TransIn': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            'TransOut': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
            'NewCash': {0: 1000, 1: -497.5 , 2: 0, 3: 0, 4: 2.5, 5: 0},
            'Cash': {0: 1000, 1: 502.5, 2: 502.5, 3: 502.5, 4: 505, 5: 505},
            'Effective': {0: 0, 1: -500, 2: 0, 3: 0, 4: 0, 5: 0},
            'Cost': {0: 0, 1: 500, 2: 500, 3: 500, 4: 500, 5: 500},
            'TotalDividends': {0: 0, 1: 2.5, 2: 2.5, 3: 2.5, 4: 5.0, 5: 5.0},
            'Dividends': {0: 0, 1: 2.5, 2: 0, 3: 0, 4: 2.5, 5: 0},
            'Value': {0: 0, 1: 500, 2: 500, 3: 500, 4: 500, 5: 500},
            'Actual': {0: 1000, 1: 1002.5, 2: 1002.5, 3: 1002.5, 4: 1005, 5: 1005}}
        self.pd = pd.DataFrame.from_dict(self.pd_starting_dict)

        self.ed_starting_dict = {
            'Date':
                {0: Timestamp('2022-02-01 00:00:00'),
                 1: Timestamp('2022-03-01 00:00:00'),
                 2: Timestamp('2022-04-01 00:00:00'),
                 3: Timestamp('2022-05-01 00:00:00'),
                 4: Timestamp('2022-06-01 00:00:00')},
            'Equity': {0: 'CETF.TO', 1: 'CETF.TO', 2: 'CETF.TO', 3: 'CETF.TO', 4: 'CETF.TO'},
            'Object_ID': {0: 1, 1: 1, 2: 1, 3: 1, 4: 1},
            'Object_Type': {0: 'Equity', 1: 'Equity', 2: 'Equity', 3: 'Equity', 4: 'Equity'},
            'Shares': {0: 50.0, 1: 50.0, 2: 50.0, 3: 50.0, 4: 50.0},
            'Cost': {0: 500.0, 1: 500.0, 2: 500.0, 3: 500.0, 4: 500.0},
            'Price': {0: 10.0, 1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0},
            'Dividends': {0: 2.5, 1: 0.0, 2: 0.0, 3: 2.5, 4: 0.0},
            'TotalDividends': {0: 2.5, 1: 2.5, 2: 2.5, 3: 5.0, 4: 5.0},
            'Value': {0: 500.0, 1: 500.0, 2: 500.0, 3: 500.0, 4: 500.0},
            'TBuy': {0: 500.0, 1: 500.0, 2: 500.0, 3: 500.0, 4: 500.0},
            'TSell': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0},
            'RelGain': {0: 2.5, 1: 2.5, 2: 2.5, 3: 5.0, 4: 5.0},
            'UnRelGain': {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0},
            'RelGainPct': {0: 0.5, 1: 0.5, 2: 0.5, 3: 1.0, 4: 1.0},
            'UnRelGainPct': {0: 0, 1: 0, 2: 0, 3: 0, 4: 0},
            'AvgCost': {0: 10.0, 1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0}}

        self.ed = pd.DataFrame.from_dict(self.ed_starting_dict)


class DataFrameTest(BasicSetup):

    def test_nochange(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        self.assertEqual(self.account.get_pattr('Funds', self.months[len(self.months)-1]), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', self.months[len(self.months)-1]), 0, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', self.months[len(self.months)-1]), 1000, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', self.months[len(self.months)-1]), 500, 'Value as Expected')
        self.assertEqual(self.account.get_pattr('Cost', self.months[len(self.months) - 1]), 500, 'Value as Expected')

    def test_day_change(self):
        """
        On the trade day we bought 50@10,  then sold 10@11
        :return:
        """
        Transaction.objects.create(account=self.account, user=self.user, equity=self.equities[0], date=self.months[1],
                                   price=11, quantity=10, xa_action=Transaction.SELL)

        self.assertEqual(self.account.get_pattr('Value', self.months[1]), 400, 'PD Value')  # Price should not change - still 10
        self.assertEqual(self.account.get_pattr('Cash', self.months[1]), 610, 'PD Cash')
        self.assertEqual(self.account.get_pattr('Actual', self.months[1]), 1010, 'PD Value')  # Price should not change - still 10


class AccountMgmtTest(BasicSetup):
    """
    Test Closing and Account and transferring it to another
    """
    def setUp(self):
        super().setUp()
        self.portfolio = Portfolio.objects.create(name='Portfolio', user=self.user, currency='CAD')
        self.new_account = Account.objects.create(name='New', account_type='Investment', account_name='002', managed=False, currency='CAD', user=self.user, portfolio=self.portfolio)

    def test_cache(self):
        print (self.account.e_pd.to_dict())


    @freeze_time("2022-06-01")
    def test_can_close(self):
        result = self.account.can_close(datetime(2022,6,1).date())
        self.assertFalse(result, 'Can not close without transfer when equities exist')
        self.assertEqual(str(result), 'Can not close this account,  it still has active equities', 'Error Message Correct')

        result = self.account.can_close(self.months[0])
        self.assertFalse(result, 'Can not close with later transactions')
        self.assertTrue(str(result).startswith('Close date must be later then'), 'Error Message Correct')

        result = self.new_account.can_close(self.months[0])
        self.assertFalse(result, 'Can not close no transactions')
        self.assertTrue(str(result).startswith('Can not close an account with no transactions - Delete instead'), 'Error Message Correct')

        self.new_account._end = self.months[0]
        self.new_account.save()
        result = self.new_account.can_close(self.months[0])
        self.assertFalse(result, 'already Closed')
        self.assertTrue(str(result).startswith('Account is already closed'), 'Error Message Correct')

        self.new_account._end = None
        self.new_account.save()

        result = self.account.can_close(self.months[len(self.months)-1], self.new_account)
        self.assertFalse(result, 'Must be in the same portfolio')
        self.assertTrue(str(result).startswith('Can not Transfer to shares between different portfolios'), 'Error Message Correct')

        self.account.portfolio = self.portfolio
        self.account.save()
        result = self.account.can_close(self.months[len(self.months)-1], self.new_account)
        self.assertTrue(result, 'Must be in the same portfolio')

    @freeze_time("2022-06-01")
    def test_nochange(self):

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 1000, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 500, 'Value as Expected')
        self.account.portfolio = self.portfolio
        self.account.save()

        self.account.close(self.months[len(self.months)-1], self.new_account)

        self.assertTrue(self.account._end, self.months[len(self.months)-1])
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -1000, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 0, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 0, 'Value as Expected')

        self.assertEqual(self.new_account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.new_account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.new_account.get_pattr('Actual', datetime.today().date()), 1000, 'Actual as Expected')
        self.assertEqual(self.new_account.get_pattr('Value', datetime.today().date()), 500, 'Value as Expected')

    @freeze_time("2022-06-01")
    def test_with_profits(self):
        e = EquityValue.objects.get(equity=self.equities[0], date=self.months[5])
        e.price = 20
        e.save()

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 1500, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 1000, 'Value as Expected')

        self.account.portfolio = self.portfolio
        self.account.save()

        self.account.close(self.months[len(self.months)-1], self.new_account)

        self.assertTrue(self.account._end, self.months[len(self.months)-1])
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -1000, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('TransOut', datetime.today().date()), -500, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 0, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 0, 'Value as Expected')

        self.assertEqual(self.new_account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.new_account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.new_account.get_pattr('Actual', datetime.today().date()), 1500, 'Actual as Expected')
        self.assertEqual(self.new_account.get_pattr('Value', datetime.today().date()), 1000, 'Value as Expected')
        self.assertEqual(self.new_account.get_pattr('TransIn', datetime.today().date()), 500, 'Value as Expected')

    @freeze_time("2022-06-01")
    def test_with_losses(self):
        e = EquityValue.objects.get(equity=self.equities[0], date=self.months[5])
        e.price = 5
        e.save()

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 750, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 250, 'Value as Expected')
        self.assertEqual(self.account.get_pattr('Cash', datetime.today().date()), 500, 'Value as Expected')

        self.account.portfolio = self.portfolio
        self.account.save()

        self.account.close(self.months[len(self.months)-1], self.new_account)

        self.assertTrue(self.account._end, self.months[len(self.months)-1])
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -1000, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('TransOut', datetime.today().date()), 250, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 0, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 0, 'Value as Expected')

        self.assertEqual(self.new_account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.new_account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.new_account.get_pattr('Actual', datetime.today().date()), 750, 'Actual as Expected')
        self.assertEqual(self.new_account.get_pattr('Value', datetime.today().date()), 250, 'Value as Expected')
        self.assertEqual(self.new_account.get_pattr('TransIn', datetime.today().date()), -250, 'Value as Expected')
        self.assertEqual(self.new_account.get_pattr('Cash', datetime.today().date()), 500, 'Value as Expected')

    @freeze_time("2022-06-01")
    def test_with_prior_redeem(self):
        e = EquityValue.objects.get(equity=self.equities[0], date=self.months[5])
        e.price = 20
        e.save()

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 1500, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 1000, 'Value as Expected')
        self.assertEqual(self.account.get_pattr('Cash', datetime.today().date()), 500, 'Value as Expected')

        Transaction.objects.create(account=self.account, real_date=self.months[3], value=650, xa_action=Transaction.REDEEM)
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[3], quantity=10, price=15, xa_action=Transaction.SELL)

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -650, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Cash', datetime.today().date()), 0, 'Value as Expected')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 800, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 800, 'Value as Expected')

        self.account.portfolio = self.portfolio
        self.account.save()

        self.account.close(self.months[len(self.months)-1], self.new_account)

        self.assertTrue(self.account._end, self.months[len(self.months)-1])
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -1000, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('TransOut', datetime.today().date()), -450, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 0, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 0, 'Value as Expected')

        self.assertEqual(self.new_account.get_pattr('Funds', datetime.today().date()), 350, 'Funding as Expected.')
        self.assertEqual(self.new_account.get_pattr('Redeemed', datetime.today().date()), 0, 'Redeemed as Expected.')
        self.assertEqual(self.new_account.get_pattr('Actual', datetime.today().date()), 800, 'Actual as Expected')
        self.assertEqual(self.new_account.get_pattr('Value', datetime.today().date()), 800, 'Value as Expected')
        self.assertEqual(self.new_account.get_pattr('TransIn', datetime.today().date()), 450, 'Value as Expected')
        self.assertEqual(self.new_account.get_pattr('Cash', datetime.today().date()), 0, 'Value as Expected')
