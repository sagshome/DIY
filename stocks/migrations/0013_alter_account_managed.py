# Generated by Django 5.0.10 on 2024-12-20 15:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0012_alter_account_account_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='managed',
            field=models.BooleanField(default=True, help_text='Set when Dividends will be reinvested'),
        ),
    ]
