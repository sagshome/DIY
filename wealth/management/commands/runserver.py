# When running myserver (debugging) reset
from wealth.models import clear_caches
import logging
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticFilesRunserverCommand,
)

logger = logging.getLogger(__name__)

class Command(StaticFilesRunserverCommand):
    def handle(self, *args, **options):
        logger.info('Resting all caches')
        clear_caches()
        super().handle(*args, **options)


