import logging
import pandas as pd
from django.core.management.base import BaseCommand
from wealth.models import Account, Investment, Value, clear_caches
from base.models import Inflation, ExchangeRate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update all wealth data'

    def handle(self, *args, **options):
        Investment.daily_update()
        Value.update_dividends()
        Inflation.update()
        ExchangeRate.update()
        for a in Account.objects.all():
            a.rebuild()
        clear_caches()

