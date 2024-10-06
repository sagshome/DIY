import logging

from django.conf import settings
from stocks.models import Equity, Inflation, ExchangeRate, Account

logger = logging.getLogger(__name__)


def daily_update():
    # Your cleanup logic here
    if settings.ALPHAVANTAGEAPI_KEY:
        max_calls = 20
        total_calls = 0
        for equity in Equity.objects.all().order_by('last_updated'):
            if total_calls >= max_calls or not equity.searchable:  # We will get the others tomorrow
                logger.debug('Filling Equity Holes for %s' % equity)
            else:
                total_calls += 1
                equity.update(key=settings.ALPHAVANTAGEAPI_KEY)
            equity.fill_equity_value_holes()
    Inflation.update()
    ExchangeRate.update()

    for account in Account.objects.all():
        account.update_static_values()


def stock_export():
    export_file = 'foo'

