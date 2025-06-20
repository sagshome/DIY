import logging
import requests

from datetime import datetime, timedelta, UTC, date
from phonenumber_field.modelfields import PhoneNumberField
from requests.exceptions import ConnectTimeout, ConnectionError
from requests.models import Response
from tzlocal import get_localzone
from django.db import models
from django.contrib.auth.models import User

from .utils import BoolReason

# We can not import CURRENCIES since it will be an import loop - from stocks.models import CURRENCIES
CURRENCIES = (
    ('CAD', 'Canadian Dollar'),
    ('USD', 'US Dollar'),
)

logger = logging.getLogger(__name__)

COLORS = ['#FF6F61', '#6B8E23', '#4A90E2', '#F5A623', '#46f0f0', '#9013FE', '#E4C1D9', '#8B572A',
          '#FEC89A', '#F5E6CC', '#FFD8B1', '#B5EAD7', '#C3B1E1', '#FFF4B1', '#D4A5E6', '#CBE8F0', '#000075', '#808080', '#50E3C2',
          '#ffffff', '#000000']

PALETTE = {'green': '#2ECC71',
           'coral': '#FF6F61',
           'olive': '#6B8E23',
           'blue': '#4A90E2',
           'turquoise': '#50E3C2',
           'yellow': '#F5A623',
           'purple': '#9013FE',
           'rose': '#E4C1D9',
           'brown': '#8B572A',
           'orange': '#FEC89A',
           'cost': '#000000',
           'value': '#2ECC71',
           'dividends': '#4A90E2',
           }

# FF6F61 (Coral Red) and #6B8E23 (Olive Drab) are complementary because they are on opposite sides of the color wheel, creating a striking contrast.
# 4A90E2 (Sky Blue) and #F5A623 (Golden Yellow) provide a warm-cool color pairing, which is visually dynamic but not jarring.
# 50E3C2 (Turquoise) complements #9013FE (Purple), providing a balance of cool hues with a slight pop of vivid color.
# D0021B (Red) and #8B572A (Chestnut Brown) create a grounded, earthy combination that feels organic and balanced.

COUNTRIES = [('CA', 'Canada'),
             ('US', 'United States'),]


DIY_EPOCH = datetime(2014, 1, 1).date()  # Before this date.   I was too busy working


class Profile(models.Model):
    user: User = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = PhoneNumberField(blank=True, null=True)
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='CAD')
    address1 = models.CharField(max_length=100, blank=True, null=True)
    address2 = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=2, blank=True, null=True)
    state = models.CharField(max_length=2, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    av_api_key = models.CharField(max_length=24, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.user.username


class API(models.Model):
    """
    Support making an API offline and catch some traps and return a valid / invalid response
    """
    DEFAULT_FAIL_LENGTH: int = 60 * 60 * 3  # 3 Hours
    name = models.CharField(primary_key=True, null=False, blank=False, max_length=32)
    base = models.CharField(null=True, blank=True, max_length=132)
    fail_reason = models.CharField(null=False, blank=False, max_length=132, default='Manual Suspension')  # Via the admin tool
    fail_length: int = models.IntegerField(null=True, blank=True, default=DEFAULT_FAIL_LENGTH)  # Increase via admin tool if so desired
    _active = models.BooleanField(default=True)
    _last_fail: date = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls, name, extra=None):   # return a get.result or None
        try:
            url = cls.objects.get(name=name)
            test = url.ready_or_reset()
            if test:
                try:
                    return requests.get(url.base + extra)
                except ConnectTimeout:
                    reason = 'Connection Timeout'
                except ConnectionError:
                    reason = 'Connection Error'
                cls.pause(name, reason)
            else:
                reason = str(test)
        except API.DoesNotExist:
            reason = 'Configuration Error'
        # API did not work,  return an error
        result = Response()
        result.status_code = 500
        result.reason = reason
        return result

    @property
    def is_active(self):
        return self._active

    @property
    def last_fail(self):
        return DIY_EPOCH if not self._last_fail else self._last_fail

    @classmethod
    def pause(cls, name, reason='Undefined'):
        try:
            url = cls.objects.get(name=name)
            if url._active:
                url._active = False
                url._last_fail = datetime.now()
                url.fail_length = cls.DEFAULT_FAIL_LENGTH
                url.fail_reason = reason
                url.save()
        except cls.DoesNotExist:
            logger.warning('Trying to pause invalid url named:' % name)

    def ready_or_reset(self):
        if self.is_active:
            return BoolReason(True, 'API is Active')
        if self.last_fail < datetime.now(UTC) - timedelta(seconds=self.fail_length):
            self._active = True
            self.save()
            return BoolReason(True, 'API has been reset')

        return BoolReason(False, f'API is inactive since {self._last_fail.astimezone(get_localzone())}')

    @classmethod
    def status(cls, name):
        try:
            api = cls.objects.get(name=name)
            return api.ready_or_reset()
        except cls.DoesNotExist:
            return BoolReason(False, 'Configuration Error')
