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

logger = logging.getLogger(__name__)

DEFAULT_LOOKUP = {"bestMatches": [{"1. symbol": "BCE.TRT",
                                        "2. name": "MYE this is better Inc",
                                        "3. type": "Equity",
                                        "4. region": "Toronto",
                                        "5. marketOpen": "09:30",
                                        "6. marketClose": "16:00",
                                        "7. timezone": "UTC-05",
                                        "8. currency": "CAD",
                                        "9. matchScore": "1.0000"}]}

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


@override_settings(NO_CACHE=True)
class BasicSetup(TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create(username='test', is_superuser=False, is_staff=False, is_active=True)
        Profile.objects.create(user=self.user, currency='CAN')
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
            ExchangeRate.objects.create(date=month, us_to_can=self.exchange_rates[index]['us_to_can'], can_to_us=self.exchange_rates[index]['can_to_us'])
            Inflation.objects.create(date=month, cost=self.inflation[index]['cost'], inflation=self.inflation[index]['inflation'])
            index += 1


        self.portfolio = Portfolio.objects.create(name='portfolio', user=self.user, currency='CAD')
        self.investment_account = InvestmentAccount.objects.create(name="inv001", user=self.user, currency='CAD', account_name='inv_007', managed=False)
        self.cash_account = CashAccount.objects.create(name="cash001", user=self.user, currency='CAD', account_name='cash_007', managed=False)
        self.value_account = ValueAccount.objects.create(name="val001", user=self.user, currency='CAD', account_name='val_007', managed=False)

        self.target_investment_account = InvestmentAccount.objects.create(name="inv002", user=self.user, currency='CAD', managed=False)
        self.target_value_account = ValueAccount.objects.create(name="val002", user=self.user, currency='CAD', managed=False)
        self.target_cash_account = CashAccount.objects.create(name="cash002", user=self.user, currency='CAD', managed=False)
        self.target_accounts = [
            self.target_investment_account,
            self.target_value_account,
            self.target_cash_account,
        ]

        self.cash_equity = Equity.objects.get(symbol=self.cash_account.f_key)
        self.value_equity = Equity.objects.get(symbol=self.value_account.f_key)
        self.equities = [
            Equity.objects.create(symbol='CETF.TO', name='Eq CAN_ETF', equity_type='Equity',region='Canada', currency='CAD', searchable=False, validated=True),
            Equity.objects.create(symbol='USEQ', name='Eq US_EQUITY', equity_type='Equity', region='US', currency='USD', searchable=False, validated=True),
        ]

        for month in self.months:
            EquityValue.objects.create(equity=self.equities[0], real_date=month, price=10, source=DataSource.API.value)
            EquityValue.objects.create(equity=self.equities[1], real_date=month, price=20, source=DataSource.API.value)
            FundValue.objects.create(equity=self.cash_equity, real_date=month, value=500, source=DataSource.USER.value)
            FundValue.objects.create(equity=self.value_equity, real_date=month, value=1000, source=DataSource.USER.value)

        EquityEvent.objects.create(real_date=self.months[1], equity=self.equities[0], value='0.05', event_type='Dividend', source=DataSource.API.value)
        EquityEvent.objects.create(real_date=self.months[4], equity=self.equities[0], value='0.05', event_type='Dividend', source=DataSource.API.value)

        Transaction.objects.create(account=self.investment_account, real_date=self.months[0], value=1000, xa_action=Transaction.FUND)
        Transaction.objects.create(account=self.investment_account, equity=self.equities[0], real_date=self.months[1], price=10, quantity=50, xa_action=Transaction.BUY)
        Transaction.objects.create(account=self.value_account, real_date=self.months[0], value=1000, xa_action=Transaction.FUND)
