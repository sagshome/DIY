import logging
import pandas as pd
from django.core.management.base import BaseCommand
from wealth.models import Dividend, Investment, clear_caches
from base.models import Inflation, ExchangeRate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update data - quickly during the day'

    def handle(self, *args, **options):
        Investment.in_day_update()
