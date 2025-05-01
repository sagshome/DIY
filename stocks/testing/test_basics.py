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


class AccountSetup(BasicSetup):
    def setUp(self):
        super().setUp()
        self.account = self.investment_account

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


class DataFrameTest(AccountSetup):

    def test_nochange(self):
        """
        Three month window
        default inflation = 0,  exchange rate = 1
        :return:
        """
        self.account._end = self.months[len(self.months) - 1]
        self.account.save()

        expected_dict = self.pd.to_dict()
        generated_dict = self.account.p_pd.to_dict()
        for key in expected_dict.keys():
            if key != 'Effective':  # Ignore effective,  it is to precise to compare this way
                self.assertEqual(generated_dict[key], expected_dict[key], f'Comparing Account DF - Key {key}')
        self.assertEqual(round(self.account.get_pattr('Effective', self.months[len(self.months) - 1]), 0), 1052, 'Value as Expected')

        expected_dict = self.ed.to_dict()
        generated_dict = self.account.e_pd.to_dict()
        for key in expected_dict.keys():
            if not key == 'Object_ID':
                self.assertEqual(generated_dict[key], expected_dict[key], f'Comparing Equity DF - Key {key}')


    def test_day_change(self):
        """
        On the trade day we bought 50@10,  then sold 10@11
        :return:
        """
        Transaction.objects.create(account=self.account, user=self.user, equity=self.equities[0], date=self.months[1],
                                   price=11, quantity=10, xa_action=Transaction.SELL)

        self.assertEqual(self.account.get_pattr('Value', self.months[1]), 400, 'PD Value')  # Price should not change - still 10
        self.assertEqual(self.account.get_pattr('Cash', self.months[1]), 612, 'PD Cash')
        self.assertEqual(self.account.get_pattr('Actual', self.months[1]), 1012, 'PD Value')  # Price should not change - still 10


class SimpleTests(SimpleTestCase):

    def test_StringTranslations(self):
        self.assertEqual(Transaction.transaction_value('Deposit'), Transaction.FUND)


