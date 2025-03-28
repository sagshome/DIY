# Generated by Django 5.0.10 on 2025-01-21 16:53

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0016_rename_accountfundvalue_fundvalue_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='equityvalue',
            name='equity',
            field=models.ForeignKey(limit_choices_to={'equity_type': 'Investment'}, on_delete=django.db.models.deletion.CASCADE, to='stocks.equity'),
        ),
        migrations.AlterField(
            model_name='fundvalue',
            name='fund',
            field=models.ForeignKey(limit_choices_to={'equity_type': 'Value'}, on_delete=django.db.models.deletion.CASCADE, to='stocks.equity'),
        ),
        migrations.AlterField(
            model_name='fundvalue',
            name='source',
            field=models.IntegerField(choices=[(10, 'ADMIN'), (20, 'ADJUSTED'), (30, 'API'), (40, 'UPLOAD'), (50, 'USER'), (60, 'ESTIMATE')], default=50),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='xa_action',
            field=models.IntegerField(choices=[(1, 'Deposit'), (2, 'Buy'), (3, 'Reinvested Dividend'), (4, 'Sell'), (6, 'Dividends/Interest'), (5, 'Withdraw'), (7, 'Sold for Fees'), (8, 'Transferred In'), (9, 'Transferred Out'), (10, 'Value'), (11, 'Balance')], help_text='Select a Account'),
        ),
    ]
