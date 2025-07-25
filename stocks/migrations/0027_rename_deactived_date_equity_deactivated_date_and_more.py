# Generated by Django 5.0.10 on 2025-06-21 19:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0026_cashaccount_valueaccount_remove_account_derived_type'),
    ]

    operations = [
        migrations.RenameField(
            model_name='equity',
            old_name='deactived_date',
            new_name='deactivated_date',
        ),
        migrations.AddField(
            model_name='equity',
            name='alternate_symbol',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='Alternate API Symbol'),
        ),
        migrations.AlterField(
            model_name='equity',
            name='equity_type',
            field=models.CharField(blank=True, choices=[('Equity', 'Equity/ETF'), ('Cash', 'Bank Accounts'), ('Value', 'Value Account'), ('Fund', 'Mutual Fund')], default='Equity', max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='xa_action',
            field=models.IntegerField(choices=[(1, 'Deposit'), (2, 'Buy'), (3, 'Reinvested Dividend'), (4, 'Sell'), (6, 'Dividends/Interest'), (5, 'Withdraw'), (7, 'Fees Paid'), (8, 'Transfer In'), (9, 'Transfer Out'), (10, 'Value'), (11, 'Balance')], help_text='Select a Account'),
        ),
    ]
