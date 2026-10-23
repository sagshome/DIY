import logging

from celery import shared_task
from datetime import datetime
from django.conf import settings
from django.core.cache import cache

from django.contrib.auth.models import User


from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.db.models import Max

from base.models import Inflation, ExchangeRate
from .models import Account, Investment, Value, clear_caches

logger = logging.getLogger(__name__)

@shared_task
def fail_warn():
    """
    Designed to run weekly,  please set up the cron / task to do as such.
    """

    days_for_stale = 180  # Six months stale

    cutoff = timezone.now().date() - timedelta(days=days_for_stale)

    stale_investments = Investment.objects.annotate(
        last_value_date=Max('values__date')  # or 'values__date' if related_name
    ).filter(
        last_value_date__lt=cutoff
    )

@shared_task
def wealth_daily_update():
    # todo: Same as management Task
    Investment.daily_update()
    Value.update_dividends()
    Inflation.update()
    ExchangeRate.update()
    for a in Account.objects.all():
        a.rebuild()
    clear_caches()

@shared_task
def wealth_inday_update():
    # todo: Same as management Task
    Investment.in_day_update()
    clear_caches()
