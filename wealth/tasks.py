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

from .models import Investment

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

    ### over all users,  who have active accounts with any of these investements,  send them an email ping to update the investment is question
