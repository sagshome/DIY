import logging
import requests

from datetime import datetime, timedelta
from requests.exceptions import ConnectTimeout, ConnectionError
from requests.models import Response

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


CURRENCIES = (
    ('CAD', 'Canadian Dollar'),
    ('USD', 'US Dollar')
)

COLORS = ['#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe',
          '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080',
          '#ffffff', '#000000']


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='CAD')
    av_api_key = models.CharField(max_length=24, null=True, blank=True)
    income = models.DecimalField(decimal_places=0, max_digits=9, default=0)
    # knowledge = forms.ChoiceField(choices=KNOWLEDGE)
    worth = models.DecimalField(decimal_places=0, max_digits=9, default=0)
    goals = models.DecimalField(decimal_places=0, max_digits=9, default=0)

    def __str__(self):
        return self.user.username


class URL(models.Model):
    '''
    Support making an API offline and catch some traps and return a valid / invalid response
    '''

    ERROR_SECONDS = 60 * 60 * 3  # Or 3 hours

    name = models.CharField(primary_key=True, null=False, blank=False, max_length=32)
    base = models.CharField(null=False, blank=False, max_length=132)
    _active = models.BooleanField(default=True)
    _last_fail = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls, name, extra=None):   # return a get.result or None
        reason = ''
        try:
            url = cls.objects.get(name=name)
            if url.ready_or_reset():
                try:
                    return requests.get(url.base + extra)
                except ConnectTimeout:
                    reason = 'Connection Timeout'
                except ConnectionError:
                    reason = 'Connection Error'
                url._active = False
                url._last_fail = datetime.now()
                url.save()

        except URL.DoesNotExist:
            reason = 'Configuration Error'

        result = Response()
        result.status_code = 500
        result.reason = reason
        return result

    def ready_or_reset(self):
        if self._active:
            return True
        if self._last_fail < datetime.now() - timedelta(seconds=self.ERROR_SECONDS):
            self._active = True
            self.save()
            return True
        return False


'''
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
'''