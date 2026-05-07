import logging
import pandas as pd
from django.core.management.base import BaseCommand
from stocks.models import Transaction, Equity

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Dump all Transactions in a format for suitable for importing'

    def handle(self, *args, **options):
        for e in Equity.objects.all():
            e.update()
