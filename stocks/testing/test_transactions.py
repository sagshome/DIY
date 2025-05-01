import logging
import numpy as np
import pandas as pd

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from unittest.mock import patch
from pandas import Timestamp

from django.test import SimpleTestCase, override_settings
from django.contrib.auth.models import User

from stocks.models import ExchangeRate, Inflation, Equity, EquityEvent, EquityValue, FundValue, Account, Transaction, DataSource, Portfolio, InvestmentAccount, ValueAccount, CashAccount
from base.models import Profile

from base.utils import normalize_date, next_date, normalize_today

from stocks.testing.setup import BasicSetup

logger = logging.getLogger(__name__)

class SaveTests(BasicSetup):

    def setUp(self):
        super().setUp()

    @freeze_time('2020-09-01')
    def test_transformations(self):
        transaction = Transaction.objects.create(account=self.investment_account, value=-500, xa_action=Transaction.FUND)
        self.assertEqual(transaction.value, 500, 'Fund is always positive')
        self.assertEqual(transaction.date, datetime(2020,9,1).date(), 'Default to today')
        self.assertEqual(transaction.real_date, datetime(2020,9,1).date(), 'Default to today')

        transaction = Transaction.objects.create(account=self.investment_account, real_date=datetime(2021,9,7).date(), value=500, xa_action=Transaction.FUND)
        self.assertEqual(transaction.value, 500, 'Fund is always positive')
        self.assertEqual(transaction.date, datetime(2021,9,1).date(), 'Normalized')
        self.assertEqual(transaction.real_date, datetime(2021,9,7).date(), 'Honored')

        transaction = Transaction.objects.create(account=self.investment_account, date=datetime(2021,9,7).date(), value=-500, xa_action=Transaction.REDEEM)
        self.assertEqual(transaction.value, -500, 'Redeem is always negative')
        self.assertEqual(transaction.date, datetime(2021,9,1).date(), 'Normalized')
        self.assertEqual(transaction.real_date, datetime(2021,9,7).date(), 'Honored')

        transaction = Transaction.objects.create(account=self.investment_account, value=500, xa_action=Transaction.REDEEM)
        self.assertEqual(transaction.value, -500, 'Redeem is always negative')

        transaction = Transaction.objects.create(account=self.investment_account, equity=self.equities[0], quantity=-5, price=10, xa_action=Transaction.BUY)
        self.assertEqual(transaction.quantity, 5, 'Buy Quantity is always positive')
        self.assertEqual(transaction.price, 10, 'Price is always positive')
        self.assertEqual(transaction.value, 50, 'Buy is always negative')

        transaction = Transaction.objects.create(account=self.investment_account, equity=self.equities[0], quantity=5, price=-10, xa_action=Transaction.BUY)
        self.assertEqual(transaction.quantity, 5, 'Buy Quantity is always positive')
        self.assertEqual(transaction.price, 10, 'Price is always positive')
        self.assertEqual(transaction.value, 50, 'Buy is always negative')

        transaction = Transaction.objects.create(account=self.investment_account, equity=self.equities[0], value=-456, quantity=5, price=-10, xa_action=Transaction.BUY)
        self.assertEqual(transaction.quantity, 5, 'Buy Quantity is always positive')
        self.assertEqual(transaction.price, 10, 'Price is always positive')
        self.assertEqual(transaction.value, 456, 'Value when explicit lives.')


