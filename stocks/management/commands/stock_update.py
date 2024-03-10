import logging

from django.core.management.base import BaseCommand
from stocks.tasks import daily_update

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update the Equity Values (refresh from external DB) as well as the profiles that access them'

    def handle(self, *args, **options):
        daily_update()
