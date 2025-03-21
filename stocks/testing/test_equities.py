import logging

from datetime import datetime
from freezegun import freeze_time
from unittest.mock import patch, Mock

from django.test import TestCase

from stocks.models import Equity, EquityEvent, EquityValue, DataSource, FundValue, Account
from stocks.testing.setup import DEFAULT_LOOKUP, DEFAULT_QUERY

logger = logging.getLogger(__name__)


class BasicSetup(TestCase):

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.account = Account.objects.create(name="test001", account_type='Value', currency='CAD', account_name='Bar_007', managed=True)
        self.equity: Equity = Equity.objects.create(symbol='e', equity_type='Equity', name='equity nAme', searchable=False, validated=True)
        self.equity2: Equity = Equity.objects.create(symbol=self.account.f_key, currency='CAD', name=self.account.f_key, equity_type='Value')

        self.original = {
            datetime(2022,3,1).date(): 10.0,
            datetime(2022, 6, 1).date(): 13.0,
            datetime(2022, 12, 1).date(): 7.0
        }
        for item in self.original:
            EquityValue.objects.create(equity=self.equity, real_date=item, price=self.original[item], source=DataSource.API.value)

        for item in self.original:
            FundValue.objects.create(equity=self.equity2, real_date=item, value=self.original[item], source=DataSource.API.value)

    def test_defaults(self):
        self.assertEqual(self.equity.symbol, 'E', 'Test Forced UpperCase symbol')
        self.assertEqual(self.equity.name, 'equity nAme', 'Test Name is case preserved')
        self.assertEqual(self.equity.region, 'Canada', 'Test region default is Canada')
        self.assertEqual(self.equity.currency, 'CAD', 'Test currerency is CAD')
        self.assertEqual(self.equity.equity_type, 'Equity', 'Default Equity Type')
        self.assertIsNone(self.equity.last_updated, 'Ensure no default value on last updated')

    @freeze_time("2023-02-01")
    def test_fill_holes(self):
        self.maxDiff = 2000
        original = dict(EquityValue.objects.filter(equity=self.equity).values_list('date', 'price'))
        self.assertDictEqual(original, self.original, 'Test PRE holes')
        self.equity.fill_holes()
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
            datetime(2022, 12, 1).date(): 7.0,
            datetime(2023, 1, 1).date(): 7.0,
            datetime(2023, 2, 1).date(): 7.0,
        }

        update = dict(EquityValue.objects.filter(equity=self.equity).values_list('date', 'price'))
        self.assertDictEqual(update, updated, 'Test Filled holes')

    @freeze_time("2023-02-01")
    def test_fill_value_holes(self):
        self.maxDiff = 2000
        original = dict(FundValue.objects.filter(equity=self.equity2).values_list('date', 'value'))

        self.assertDictEqual(original, self.original, 'Test PRE holes')
        self.equity2.fill_holes()
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
            datetime(2022, 12, 1).date(): 7.0,
            datetime(2023, 1, 1).date(): 7.0,
            datetime(2023, 2, 1).date(): 7.0,
        }
        update = dict(FundValue.objects.filter(equity=self.equity2).values_list('date', 'value'))
        self.assertDictEqual(update, updated, 'Test Filled holes')

    @freeze_time("2023-02-01")
    def test_all_is_quiet(self):
        updated = {  # PreCreate the Estimated Values
            datetime(2022, 4, 1).date(): 11.0,
            datetime(2022, 5, 1).date(): 12.0,
            datetime(2022, 7, 1).date(): 12.0,
            datetime(2022, 8, 1).date(): 11.0,
            datetime(2022, 9, 1).date(): 10.0,
            datetime(2022, 10, 1).date(): 9.0,
            datetime(2022, 11, 1).date(): 8.0,
            datetime(2023, 1, 1).date(): 7.0,
            datetime(2023, 2, 1).date(): 7.0,

        }
        for item in updated:
            EquityValue.objects.create(equity=self.equity, real_date=item, price=updated[item], source=DataSource.API.value)

        with patch.object(EquityValue, 'save', autospec=True) as mock_save:
            # Perform actions that should not trigger the save method
            self.equity.fill_holes()
            mock_save.assert_not_called()

