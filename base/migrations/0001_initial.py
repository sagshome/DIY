# Generated by Django 5.0.10 on 2025-03-04 15:34

import django.db.models.deletion
import phonenumber_field.modelfields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='API',
            fields=[
                ('name', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('base', models.CharField(blank=True, max_length=132, null=True)),
                ('fail_reason', models.CharField(default='Manual Suspension', max_length=132)),
                ('fail_length', models.IntegerField(blank=True, default=10800, null=True)),
                ('_active', models.BooleanField(default=True)),
                ('_last_fail', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', phonenumber_field.modelfields.PhoneNumberField(max_length=128, region=None)),
                ('currency', models.CharField(choices=[('CAD', 'Canadian Dollar'), ('USD', 'US Dollar')], default='CAD', max_length=3)),
                ('address1', models.CharField(blank=True, max_length=100, null=True)),
                ('address2', models.CharField(blank=True, max_length=100, null=True)),
                ('city', models.CharField(blank=True, max_length=100, null=True)),
                ('country', models.CharField(max_length=2)),
                ('state', models.CharField(blank=True, max_length=2, null=True)),
                ('postal_code', models.CharField(blank=True, max_length=20, null=True)),
                ('av_api_key', models.CharField(blank=True, max_length=24, null=True)),
                ('birth_date', models.DateField(blank=True, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
