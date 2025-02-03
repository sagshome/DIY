import logging

from celery import shared_task
from datetime import datetime
from django.conf import settings
from django.contrib.auth.models import User
from base.models import Profile

from stocks.models import Equity, Inflation, ExchangeRate, Account, Portfolio

logger = logging.getLogger(__name__)


@shared_task
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

    for equity in Equity.objects.all():
        equity.fill_equity_value_holes()
    Inflation.update()
    ExchangeRate.update()

    for account in Account.objects.all():
        account.update_static_values()


@shared_task
def hourly_update():
    for equity in Equity.objects.filter(searchable=True):
        equity.yp_update(daily=False)


@shared_task
def add_to_cache(user_id):
    logger.debug("Processing accounts for %s" % user_id)
    for account in Account.objects.filter(user_id=user_id):
        _ = account.p_pd  # Just to the math which will cache the results
        _ = account.e_pd
    for portfolio in Portfolio.objects.all():
        _ = portfolio.p_pd  # Just to the math which will cache the results
        _ = portfolio.e_pd

