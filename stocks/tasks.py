import logging
import os
import time

from celery import shared_task
from datetime import datetime
from django.conf import settings
from django.core.cache import cache

from django.contrib.auth.models import User
from base.models import Profile
from base.utils import get_simple_cache

from stocks.models import Equity, Inflation, ExchangeRate, Account, Portfolio, Transaction

logger = logging.getLogger(__name__)


@shared_task
def cleanup_uploads():
    """
    Delete non-cached files that are older than 10 minutes
    """

    cutoff_time = time.time() - 600 # 10 minutes
    directory = settings.MEDIA_ROOT.joinpath('uploads')

    # Process files
    for filename in os.listdir(directory):
        if get_simple_cache(f'file:{filename}'):
            continue

        file_path = os.path.join(directory, filename)
        if not os.path.isfile(file_path):
            continue

        file_mtime = os.path.getmtime(file_path)
        if file_mtime < cutoff_time:
            os.remove(file_path)


@shared_task
def daily_update():
    # Your cleanup logic here
    key = settings.ALPHAVANTAGEAPI_KEY if settings.ALPHAVANTAGEAPI_KEY else None
    for equity in Equity.objects.all().order_by('last_updated'):
        # Find useless transactions

        equity.update(force=True, key=key, daily=True)

    Inflation.update()
    ExchangeRate.update()

    for account in Account.objects.all():
        logger.debug('Resetting account(%s) %s' % (account.id, account))
        account.reset()
        account.update_static_values()


@shared_task
def hourly_update():
    for equity in Equity.objects.filter(searchable=True):
        equity.yp_update(daily=False)


@shared_task
def add_to_cache(user_id):
    """
    Update the redis cache if the values are not already cached
    """
    if not settings.NO_CACHE:
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