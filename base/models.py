from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


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

    def __str__(self):
        return(self.user.email)


'''
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
'''