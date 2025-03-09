import logging

from datetime import datetime
from freezegun import freeze_time
from unittest.mock import patch, Mock

from django.test import TestCase

from stocks.models import Equity, EquityEvent, EquityValue, DataSource
from stocks.testing.setup import DEFAULT_LOOKUP, DEFAULT_QUERY

logger = logging.getLogger(__name__)


class BasicSetup(TestCase):

    def setUp(self):
        # Result on too many calls
        # {
        #     "Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day. Please subscribe to any of the premium plans at https://www.alphavantage.co/premium/ to instantly remove all daily rate limits."
        # }
        # on success we do not get "Information record
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.equity: Equity = Equity.objects.create(symbol='e', name='equity nAme', searchable=False, validated=True)
        self.original = {
            datetime(2022,3,1).date(): 10.0,
            datetime(2022, 6, 1).date(): 13.0,
            datetime(2022, 12, 1).date(): 7.0
        }
        for item in self.original:
            EquityValue.objects.create(equity=self.equity, real_date=item, price=self.original[item], source=DataSource.API.value)

    def test_defaults(self):
        self.assertEqual(self.equity.symbol, 'E', 'Test Forced UpperCase symbol')
        self.assertEqual(self.equity.name, 'equity nAme', 'Test Name is case preserved')
        self.assertEqual(self.equity.region, 'Canada', 'Test region default is Canada')
        self.assertEqual(self.equity.currency, 'CAD', 'Test currerency is CAD')
        self.assertEqual(self.equity.equity_type, 'Equity', 'Default Equity Type')
        self.assertIsNone(self.equity.last_updated, 'Ensure no default value on last updated')

    def test_fill_holes(self):
        self.maxDiff = 2000
        original = dict(EquityValue.objects.filter(equity=self.equity).values_list('date', 'price'))

        self.assertDictEqual(original, self.original, 'Test PRE holes')
        self.equity.fill_equity_value_holes()
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


