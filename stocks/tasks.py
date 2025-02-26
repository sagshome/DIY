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
    key = settings.ALPHAVANTAGEAPI_KEY if settings.ALPHAVANTAGEAPI_KEY else None
    for equity in Equity.objects.all().order_by('last_updated'):
        equity.update(force=True, key=key, daily=True)

    Inflation.update()
    ExchangeRate.update()

    for account in Account.objects.all():
        account.reset()
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


@shared_task
def equity_new_estimates(equity_id):
    try:
        equity = Equity.objects.get(id=equity_id)
        equity.fill_equity_value_holes()
    except Equity.DoesNotExist:
        logger.error('Failed to update estimates for equity id %s' % equity_id)