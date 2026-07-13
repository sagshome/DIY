import logging
import pandas as pd
from datetime import datetime, date
from django.utils import timezone
from django.core.management.base import BaseCommand
from base.models import DataSource
from wealth.models import Dividend, Investment, Value, clear_caches


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Adjust Price/Dividends before <date> (due to a stock split) by a factor of <factor>.\n this is required since values are adjust via the API'

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="The date the of the stock split")
        parser.add_argument("--symbol", type=str, help="The stock ticker symbol of the stock that split")
        parser.add_argument("--factor", type=int, help="The factor to adjust dividends by,  default is 2 for a stock split of 2 shares to one")

    def handle(self, *args, **options):
        try:
            this_date = pd.Timestamp(options['date']).date()
        except:  # far too vague
            print (f'Unable to convert {options["date"]} to a valid date.')
            exit (1)
        try:
            investment = Investment.objects.get(symbol=options['symbol'])
        except Investment.DoesNotExist:
            print (f'Stock symbol {options["symbol"]} is not loaded - nothing to do.')
            exit (2)

        factor = 2 if not options['factor'] else options['factor']

        dividends = Dividend.objects.filter(investment=investment, date__lte=this_date, source__gt=DataSource.ADMIN)
        print(f'{dividends.count()} - Dividend entries to process...')

        for d in dividends:
            d.value = d.value * factor
            d.source = DataSource.ADMIN.value
            d.save()
        print('Updating previous payouts...')
        Dividend.update_cash()

        values = Value.objects.filter(investment=investment, date__lte=this_date, source__gt=DataSource.ADMIN)
        print(f'{values.count()} - Value entries to process...')

        for v in values:
            v.close_value = v.close_value * factor
            v.open_value = v.open_value * factor
            v.source = DataSource.ADMIN
            v.split_fix = True
            v.save()

        clear_caches()


