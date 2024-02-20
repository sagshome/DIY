import logging
import os
import sys

from datetime import datetime, date
from freezegun import freeze_time
from unittest.mock import patch

from django.test import TestCase

from stocks.models import ExchangeRate, Inflation, Equity, EquityAlias, EquityEvent, EquityValue, Portfolio, Transaction
from stocks.utils import normalize_date, next_date, last_date, normalize_today

logger = logging.getLogger(__name__)


class BasicSetup(TestCase):

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.equity: Equity = Equity.objects.create(symbol='e', name='equity nAme', searchable=False, validated=True)
        self.original = {
            datetime(2022,3,1).date(): 10.0,
            datetime(2022, 6, 1).date(): 13.0,
            datetime(2022, 12, 1).date(): 7.0
        }
        for item in self.original:
            EquityValue.objects.create(equity=self.equity, date=item, price=self.original[item])

    def test_defaults(self):
        self.assertEqual(self.equity.symbol, 'E', 'Test Forced UpperCase symbol')
        self.assertEqual(self.equity.name, 'equity nAme', 'Test Name is case preserved')
        self.assertIsNone(self.equity.region, 'Test region default is Canada')
        self.assertIsNone(self.equity.currency, 'Test currerency is CDN')
        self.assertIsNone(self.equity.equity_type, 'Ensure no default equity type')
        self.assertIsNone(self.equity.last_updated, 'Ensure no default value on last updated')

    def test_fill_holes(self):
        self.maxDiff = 2000
        original = dict(EquityValue.objects.filter(equity=self.equity).values_list('date', 'price'))

        self.assertDictEqual(original, self.original, 'Test PRE holes')
        self.equity.fill_equity_holes()
        updated = {
            datetime(2022,3,1).date(): 10.0,
            datetime(2022, 4, 1).date(): 11.0,
            datetime(2022, 5, 1).date(): 12.0,
            datetime(2022, 6, 1).date(): 13.0,
            datetime(2022, 7, 1).date(): 12.0,
            datetime(2022, 8, 1).date(): 11.0,
            datetime(2022, 9, 1).date(): 10.0,
            datetime(2022, 10, 1).date(): 9.0,
            datetime(2022, 11, 1).date(): 8.0,
            datetime(2022, 12, 1).date(): 7.0
        }
        update = dict(EquityValue.objects.filter(equity=self.equity,
                                                 date__lte=datetime(2022, 12, 1).date()).
                      values_list('date', 'price'))
        self.assertDictEqual(update, updated, 'Test Filled holes')
