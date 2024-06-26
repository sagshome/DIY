import logging

from django.conf import settings
from stocks.models import Equity, Inflation, ExchangeRate, Portfolio

logger = logging.getLogger(__name__)

def daily_update():
    # Your cleanup logic here
    if settings.ALPHAVANTAGEAPI_KEY:
        max_calls = 20
        total_calls = 0
        for equity in Equity.objects.filter(searchable=True).order_by('last_updated'):
            if total_calls >= max_calls:  # We will get the others tomorrow
                equity.fill_equity_holes()
            else:
                total_calls += 1
                equity.update(key=settings.ALPHAVANTAGEAPI_KEY)

        Inflation.update()

        ExchangeRate.update()

        for portfolio in Portfolio.objects.all():
            portfolio.update_static_values()
