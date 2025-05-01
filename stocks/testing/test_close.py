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

from stocks.models import ExchangeRate, Inflation, Equity, EquityEvent, EquityValue, FundValue, Account, Transaction, DataSource, Portfolio, InvestmentAccount, ValueAccount, CashAccount
from base.models import Profile

from base.utils import normalize_date, next_date, normalize_today

from stocks.testing.setup import BasicSetup

logger = logging.getLogger(__name__)

class CloseInvestmentPermTest(BasicSetup):
    def setUp(self):
        super().setUp()
        self.account = self.investment_account

    def test_isclosed(self):
        self.account._end = self.months[5]
        self.account.save()

        result = self.account.can_close(self.months[5])
        self.assertFalse(result, 'already Closed')
        self.assertTrue(str(result).startswith('Account is already closed'), 'Error Message Correct')

    def test_noXAs(self):
        new_account = InvestmentAccount.objects.create(name="inv002", user=self.user, currency='CAD', account_name='inv_002', managed=False)

        result = new_account.can_close(self.months[5])
        self.assertFalse(result, 'no transactions')
        self.assertTrue(str(result).startswith('Can not close an account with no transactions - Delete instead'), 'Error Message Correct')

    def test_still_active(self):
        result = self.account.can_close(self.months[0])
        self.assertFalse(result, 'still active')
        self.assertTrue(str(result).startswith('Close date must be later then'), 'Error Message Correct')

    def test_with_value(self):
        result = self.account.can_close(self.months[5])
        self.assertFalse(result, 'with_value')
        self.assertTrue(str(result).startswith('Can not close this account,  it still has some value'), 'Error Message Correct')

        Transaction.objects.create(account=self.investment_account, equity=self.equities[0], real_date=self.months[5], price=10, quantity=50, xa_action=Transaction.SELL)
        result = self.account.can_close(self.months[5])
        self.assertTrue(result, 'cash is not value')


class CloseValuePermTest(BasicSetup):
    def setUp(self):
        super().setUp()
        self.account = self.value_account

    def test_isclosed(self):
        self.account._end = self.months[5]
        self.account.save()

        result = self.account.can_close(self.months[5])
        self.assertFalse(result, 'already Closed')
        self.assertTrue(str(result).startswith('Account is already closed'), 'Error Message Correct')

    def test_noXAs(self):

        result = self.target_investment_account.can_close(self.months[5])
        self.assertFalse(result, 'no transactions')
        self.assertTrue(str(result).startswith('Can not close an account with no transactions - Delete instead'), 'Error Message Correct')

    def test_with_value(self):
        result = self.account.can_close(self.months[5])
        self.assertFalse(result, 'with_value')
        self.assertTrue(str(result).startswith('Can not close this account,  it still has some value'), 'Error Message Correct')

        FundValue.objects.filter(equity=self.value_equity, date=normalize_date(self.months[5])).update(value=0)
        result = self.account.can_close(self.months[5])
        self.assertTrue(result, 'cash is not value')


class CloseCashPermTest(BasicSetup):
    def setUp(self):
        super().setUp()
        self.account = self.cash_account

    def test_can_close(self):
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[5])).update(value=0)
        result = self.account.can_close(self.months[5])
        self.assertTrue(result, 'already Closed')


    def test_cash_cant_transfer(self):
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[5])).update(value=0)
        for target in self.target_accounts:
            result = self.account.can_close(self.months[5], transfer_to=target)
            self.assertFalse(result, 'Can not transfer cash accounts')
            self.assertEqual(str(result), 'Cash accounts can not be transferred', 'Error Message Correct')

    def test_value_must_be_zero(self):
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[5])).update(value=100)
        result = self.account.can_close(self.months[5])
        self.assertFalse(result)
        self.assertEqual(str(result), 'Can not close this account,  it still has some value', 'Error Message Correct')

    def test_closing_late(self):
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[5])).update(value=0, source=DataSource.ESTIMATE.value)
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[4])).update(value=0, source=DataSource.USER.value)
        result = self.account.can_close(self.months[5])
        self.assertFalse(result)
        self.assertEqual(str(result), f'Account, must close on {self.months[4]}')

    def test_isclosed(self):
        FundValue.objects.filter(equity=self.cash_equity, date=normalize_date(self.months[5])).update(value=0)
        self.account._end = normalize_today()
        result = self.account.can_close(self.months[5])
        self.assertFalse(result)
        self.assertEqual(str(result), 'Account is already closed', 'Error Message Correct')


class CloseInvestmentTest(BasicSetup):
    def setUp(self):
        super().setUp()
        self.account = self.investment_account

    def test_no_transfer_error(self):
        with self.assertLogs(level='DEBUG') as captured:
            self.account.close(self.months[5])
            self.assertEqual(len(captured.records), 1)
            self.assertEqual(captured.records[0].levelname, 'DEBUG', 'Error only with DEBUG')
            self.assertTrue(captured.records[0].message.endswith('failed:Can not close this account,  it still has some value'))
        account = InvestmentAccount.objects.get(id=self.account.id)
        self.assertFalse(account.closed)

    def test_no_transfer(self):
        """
        Create a withdrawal request
        """
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=10, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5])
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1005).exists())
        account = InvestmentAccount.objects.get(id=self.account.id)
        self.assertEqual(account._end, self.months[5])

    def test_no_transfer_gain(self):
        """
        Create a withdrawal request
        """
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=11, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5])
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1055).exists())
        account = InvestmentAccount.objects.get(id=self.account.id)
        self.assertEqual(account._end, self.months[5])
        self.assertEqual(account.get_pattr('Funds',self.months[5]), 1000)
        self.assertEqual(account.get_pattr('Redeemed', self.months[5]), -1055)

    def test_no_transfer_loss(self):
        """
        Create a withdrawal request
        """
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=9, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5])
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-955).exists())
        account = InvestmentAccount.objects.get(id=self.account.id)
        self.assertEqual(account._end, self.months[5])
        self.assertEqual(account.get_pattr('Funds',self.months[5]), 1000)
        self.assertEqual(account.get_pattr('Redeemed', self.months[5]), -955)

    def test_investment_just_cash(self):
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=10, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5], transfer_to=self.target_investment_account)
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertEqual(Transaction.objects.filter(account=self.account, real_date=self.months[5]).count(), 2)
        self.assertEqual(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5]).count(), 1)

    def test_investment_no_change(self):
        self.account.close(self.months[5], transfer_to=self.target_investment_account)
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.investment_account, real_date=self.months[5], xa_action=Transaction.SELL, value=-500).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.BUY, value=500).exists())
        self.assertEqual(Transaction.objects.filter(account=self.account, real_date=self.months[5]).count(), 2)
        self.assertEqual(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5]).count(), 2)

    def test_investment_gain(self):
        EquityValue.objects.filter(equity=self.equities[0], real_date=self.months[5]).update(price=11)

        self.assertEqual(self.investment_account.get_pattr('Value', query_date=self.months[5]), 550)
        self.assertEqual(self.target_investment_account.get_pattr('Value', query_date=self.months[5]), 0)

        self.account.close(self.months[5], transfer_to=self.target_investment_account)
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.investment_account, real_date=self.months[5], xa_action=Transaction.SELL, value=-500).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.BUY, value=500).exists())
        self.assertTrue(Transaction.objects.filter(account=self.investment_account, real_date=self.months[5], xa_action=Transaction.TRANS_OUT, value=-50).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.TRANS_IN, value=50).exists())
        self.assertEqual(Transaction.objects.filter(account=self.account, real_date=self.months[5]).count(), 3)
        self.assertEqual(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5]).count(), 3)
        self.assertEqual(self.investment_account.get_pattr('Value', query_date=self.months[5]), 0)
        self.assertEqual(self.target_investment_account.get_pattr('Value', query_date=self.months[5]), 550)

    def test_investment_loss(self):
        EquityValue.objects.filter(equity=self.equities[0], real_date=self.months[5]).update(price=9)

        self.assertEqual(self.investment_account.get_pattr('Value', query_date=self.months[5]), 450)
        self.assertEqual(self.target_investment_account.get_pattr('Value', query_date=self.months[5]), 0)

        self.account.close(self.months[5], transfer_to=self.target_investment_account)
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.investment_account, real_date=self.months[5], xa_action=Transaction.SELL, value=-500).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.BUY, value=500).exists())
        self.assertTrue(Transaction.objects.filter(account=self.investment_account, real_date=self.months[5], xa_action=Transaction.TRANS_OUT, value=50).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5], xa_action=Transaction.TRANS_IN, value=-50).exists())
        self.assertEqual(Transaction.objects.filter(account=self.account, real_date=self.months[5]).count(), 3)
        self.assertEqual(Transaction.objects.filter(account=self.target_investment_account, real_date=self.months[5]).count(), 3)
        self.assertEqual(self.investment_account.get_pattr('Value', query_date=self.months[5]), 0)
        self.assertEqual(self.target_investment_account.get_pattr('Value', query_date=self.months[5]), 450)

    def test_value(self):
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=10, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5], transfer_to=self.target_value_account)

        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        value_record = FundValue.objects.get(equity=Equity.objects.get(symbol=self.target_value_account.f_key), date=self.months[5])
        self.assertEqual(value_record.value, 1005)  # Includes dividends
        self.assertEqual(Transaction.objects.filter(account=self.account, real_date=self.months[5]).count(), 3)
        self.assertEqual(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5]).count(), 2)

    def test_value_gain(self):
        """
        the transfer out value 55 going to a value account includes excess cash (+50) which includes dividends (+5)
        """
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=11, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5], transfer_to=self.target_value_account)

        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.TRANS_OUT, value=-55).exists())

        self.assertTrue(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5], xa_action=Transaction.TRANS_IN, value=55).exists())

        value_record = FundValue.objects.get(equity=Equity.objects.get(symbol=self.target_value_account.f_key), date=self.months[5])
        self.assertEqual(value_record.value, 1055)

    def test_value_loss(self):
        """
        the transfer out value 55 going to a value account includes excess cash (+50) which includes dividends (+5)
        """
        Transaction.objects.create(account=self.account, equity=self.equities[0], real_date=self.months[5], price=9, quantity=50,
                                   xa_action=Transaction.SELL)
        self.account.close(self.months[5], transfer_to=self.target_value_account)

        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.REDEEM, value=-1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.account, real_date=self.months[5], xa_action=Transaction.TRANS_OUT, value=45).exists())

        self.assertTrue(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5], xa_action=Transaction.FUND, value=1000).exists())
        self.assertTrue(Transaction.objects.filter(account=self.target_value_account, real_date=self.months[5], xa_action=Transaction.TRANS_IN, value=-45).exists())

        value_record = FundValue.objects.get(equity=Equity.objects.get(symbol=self.target_value_account.f_key), date=self.months[5])
        self.assertEqual(value_record.value, 955)
    def test_cash(self):
        pass


