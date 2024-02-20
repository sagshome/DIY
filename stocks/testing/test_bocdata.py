import logging
import os
import sys

from datetime import datetime, date
from freezegun import freeze_time
from unittest.mock import patch, MagicMock

from django.test import TestCase

from stocks.models import ExchangeRate, Inflation, Equity, EquityAlias, EquityEvent, EquityValue, Portfolio, Transaction
from stocks.utils import normalize_date, next_date, last_date, normalize_today

logger = logging.getLogger(__name__)


class ExchangeRateTest(TestCase):

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        ExchangeRate.objects.create(date=datetime(2023,5, 1).date(), us_to_can=1.1, can_to_us=0.909)
        ExchangeRate.objects.create(date=datetime(2023,6, 1).date(), us_to_can=1.2, can_to_us=0.833)
        ExchangeRate.objects.create(date=datetime(2023,7, 1).date(), us_to_can=1.3, can_to_us=0.769)

        e = Equity.objects.create(symbol='FOO', name='bar', searchable=False, validated=True)
        EquityValue.objects.create(equity=e, date=datetime(2023,5, 1).date(), price=10.0)

    def test_defaults(self):
        self.assertEqual(ExchangeRate.can_to_us_rate(datetime(2023,5,1).date()), 0.909)
        self.assertEqual(ExchangeRate.us_to_can_rate(datetime(2023, 5, 1).date()), 1.1)
        self.assertEqual(ExchangeRate.can_to_us_rate(datetime(2023, 4, 1).date()), 1)
        self.assertEqual(ExchangeRate.us_to_can_rate(datetime(2023, 4, 1).date()), 1)

    @patch('requests.get')
    def test_update(self, my_request):
        json_data = {
            "terms": {"url": "not_used"},
            "seriesDetail": {"FXCADUSD": "not_used"},
            "observations": [
                {"d": "2023-08-22", "FXCADUSD": {"v": "0.7443"}, "FXUSDCAD": {"v": "1.3435"}},
                {"d": "2023-08-23", "FXCADUSD": {"v": "0.0.799"},"FXUSDCAD": {"v": "1.345"}},
                {"d": "2023-08-24", "FXCADUSD": {"v": "0.7510"}, "FXUSDCAD": {"v": "1.3315"}},
                {"d": "2023-08-25", "FXCADUSD": {"v": "0.8510"}, "FXUSDCAD": {"v": "1.2315"}},
            ]
        }
        self.assertEqual(ExchangeRate.can_to_us_rate(datetime(2023,7, 1).date()), 0.769)
        self.assertEqual(ExchangeRate.us_to_can_rate(datetime(2023,7, 1).date()), 1.3)

        my_request.return_value.status_code = 200
        my_request.return_value.json.return_value = json_data
        test_date = datetime(2023,8, 1).date()
        self.assertFalse(ExchangeRate.objects.filter(date=test_date).exists())
        ExchangeRate.update()
        self.assertTrue(ExchangeRate.objects.filter(date=test_date).exists())
        data = ExchangeRate.objects.filter(date=test_date).values()
        self.assertEqual(ExchangeRate.can_to_us_rate(test_date), 0.7443)
        self.assertEqual(ExchangeRate.us_to_can_rate(test_date), 1.3435)


class InflationRateTest(TestCase):

    def setUp(self):
        super().setUp()
        self.default_data = {"terms": {"url": "not_used"},
                             "seriesDetail": {"STATIC_INFLATIONCALC": "not_used"},
                             "observations": [
                                 {"d": "2022-01-01", "STATIC_INFLATIONCALC": {"v": "145.30000000"}},
                                 {"d": "2022-02-01", "STATIC_INFLATIONCALC": {"v": "146.80000000"}},
                                 {"d": "2022-03-01", "STATIC_INFLATIONCALC": {"v": "148.90000000"}},
                             ],
                             }
        # print(self.__class__.__name__, self._testMethodName)
        ExchangeRate.objects.create(date=datetime(2023,5, 1).date(), us_to_can=1.1, can_to_us=0.909)
        ExchangeRate.objects.create(date=datetime(2023,6, 1).date(), us_to_can=1.2, can_to_us=0.833)
        ExchangeRate.objects.create(date=datetime(2023,7, 1).date(), us_to_can=1.3, can_to_us=0.769)

        e = Equity.objects.create(symbol='FOO', name='bar', searchable=False, validated=True)
        EquityValue.objects.create(equity=e, date=datetime(2023,5, 1).date(), price=10.0)
