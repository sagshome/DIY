# Generated by Django 5.0.10 on 2025-03-09 04:06

import datetime
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0021_equityevent_split_fixed_equityvalue_split_fixed_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='equity',
            name='currency',
            field=models.CharField(blank=True, choices=[('CAD', 'Canadian Dollar'), ('USD', 'US Dollar')], default='CAD', max_length=3, null=True),
        ),
        migrations.AlterField(
            model_name='equityevent',
            name='real_date',
            field=models.DateField(null=True, validators=[django.core.validators.MinValueValidator(datetime.date(1961, 1, 1)), django.core.validators.MaxValueValidator(datetime.date(2100, 1, 1))], verbose_name='Recorded Date'),
        ),
        migrations.AlterField(
            model_name='equityvalue',
            name='real_date',
            field=models.DateField(null=True, validators=[django.core.validators.MinValueValidator(datetime.date(1961, 1, 1)), django.core.validators.MaxValueValidator(datetime.date(2100, 1, 1))], verbose_name='Recorded Date'),
        ),
        migrations.AlterField(
            model_name='fundvalue',
            name='real_date',
            field=models.DateField(null=True, validators=[django.core.validators.MinValueValidator(datetime.date(1961, 1, 1)), django.core.validators.MaxValueValidator(datetime.date(2100, 1, 1))], verbose_name='Recorded Date'),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='real_date',
            field=models.DateField(null=True, validators=[django.core.validators.MinValueValidator(datetime.date(1961, 1, 1)), django.core.validators.MaxValueValidator(datetime.date(2100, 1, 1))], verbose_name='Transaction Date'),
        ),
    ]
