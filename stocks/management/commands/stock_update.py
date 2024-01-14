import logging

from django.core.management.base import BaseCommand
from stocks.models import Equity, Portfolio, Inflation, ExchangeRate

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update the Equity Values (refresh from external DB) as well as the profiles that access them'

    def handle(self, *args, **options):
        logger.warning('Starting update')
        max_calls = 15
        total_calls = 0
        for equity in Equity.objects.filter(searchable=True).order_by('last_updated'):
            if total_calls >= max_calls:  # We will get the others tomorrow
                equity.fill_equity_holes()
            else:
                total_calls += 1
                equity.update()

        Inflation.update()

        ExchangeRate.update()

        for portfolio in Portfolio.objects.all():
            portfolio.update_static_values()

        logger.warning('Finished update')
