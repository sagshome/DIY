import logging
import pandas as pd
from django.core.management.base import BaseCommand
from wealth.models import Investment, clear_caches, Value
from base.models import Inflation, ExchangeRate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update data'

    def handle(self, *args, **options):
        Investment.daily_update()
        Value.update_dividends()
        Inflation.update()
        ExchangeRate.update()
        clear_caches()

