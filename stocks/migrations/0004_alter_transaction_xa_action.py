# Generated by Django 4.2 on 2024-06-24 14:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0003_alter_portfolio_name_alter_portfolio_unique_together'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='xa_action',
            field=models.IntegerField(choices=[(1, 'Fund'), (2, 'Buy'), (3, 'Reinvested Dividend'), (4, 'Sell'), (6, 'Interest'), (5, 'Redeem')], help_text='Select a Portfolio'),
        ),
    ]
