from django.core.management.base import BaseCommand
from wealth.importers import import_from_diy


class Command(BaseCommand):
    help = 'Import DIY Data'

    def handle(self, *args, **options):
        # Investment.objects.all().delete()
        # Account.objects.all().delete()
        # time.sleep(5)
        import_from_diy()
