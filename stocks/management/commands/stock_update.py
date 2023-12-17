from django.core.management.base import BaseCommand, CommandError
from stocks.models import Equity, Portfolio
from stocks.utils import normalize_today

class Command(BaseCommand):
    help = 'Update the Equity Values (refresh from external DB) as well as the profiles that access them'

    def handle(self, *args, **options):
        max_calls = 15
        total_calls = 0
        for equity in Equity.objects.filter(searchable=True).order_by('last_updated'):
            if total_calls >= max_calls:  # We will get the others tomorrow
                break
            total_calls += 1
            equity.update()

        for portfolio in Portfolio.objects.all():
            portfolio.update_static_values()

