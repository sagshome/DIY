import logging
import numpy as np

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import User

from stocks.models import ExchangeRate, Inflation, Equity, EquityEvent, EquityValue, Account, Transaction, DataSource, Portfolio
from base.models import Profile

from base.utils import normalize_date, next_date, normalize_today

logger = logging.getLogger(__name__)

class BasicSetup(TestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(username='test', is_superuser=False, is_staff=False, is_active=True)

        self.equities = [
            Equity.objects.create(symbol='CETF.TO', name='Eq CAN_ETF', equity_type='Equity',region='Canada', currency='CAD', searchable=False, validated=True),
            Equity.objects.create(symbol='USEQ', name='Eq US_EQUITY', equity_type='Equity', region='US', currency='USD', searchable=False, validated=True),
        ]

        self.account = Account.objects.create(name='Test', user=self.user, account_name='001', account_type='Investment', managed=False, currency='CAD')

        self.months = [datetime(2022, 1, 1).date(),
                       datetime(2022, 2, 1).date(),
                       datetime(2022, 3, 1).date(),
                       datetime(2022, 4, 1).date(),
                       datetime(2022, 5, 1).date(),
                       datetime(2022, 6, 1).date(),
                       ]

        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[0], price=10, source=DataSource.API.value)
        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[1], price=10, source=DataSource.API.value)
        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[2], price=10, source=DataSource.API.value)
        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[3], price=10, source=DataSource.API.value)
        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[4], price=10, source=DataSource.API.value)
        EquityValue.objects.create(equity=self.equities[0], real_date=self.months[5], price=10, source=DataSource.API.value)

        Transaction.objects.create(account=self.account, real_date=self.months[0], value=1000, xa_action=Transaction.FUND)
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[1], price=10, quantity=50, xa_action=Transaction.BUY)
        self.account.reset()  # Cached value may exist.


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
        self.new_account.reset()  # Cached value may exist.

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
        self.account.reset()

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
        self.account.reset()
        self.new_account.reset()

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
        self.account.reset()
        self.new_account.reset()

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
        self.account.reset()

        # Test the starting point
        self.assertEqual(self.account.get_pattr('Funds', datetime.today().date()), 1000, 'Funding as Expected.')
        self.assertEqual(self.account.get_pattr('Redeemed', datetime.today().date()), -650, 'Redeemed as Expected.')
        self.assertEqual(self.account.get_pattr('Cash', datetime.today().date()), 0, 'Value as Expected')
        self.assertEqual(self.account.get_pattr('Actual', datetime.today().date()), 800, 'Actual as Expected')
        self.assertEqual(self.account.get_pattr('Value', datetime.today().date()), 800, 'Value as Expected')

        self.account.portfolio = self.portfolio
        self.account.save()

        self.account.close(self.months[len(self.months)-1], self.new_account)
        self.account.reset()
        self.new_account.reset()

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
