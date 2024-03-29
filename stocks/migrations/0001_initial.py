# Generated by Django 5.0.1 on 2024-03-05 19:41

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Equity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(max_length=32, verbose_name='Trading symbol')),
                ('name', models.CharField(blank=True, max_length=128, null=True, verbose_name='Equities Full Name')),
                ('equity_type', models.CharField(blank=True, choices=[('Equity', 'Equity/Stock'), ('ETF', 'Exchange Traded Fund'), ('MF', 'Mutual Fund'), ('MM', 'Money Market')], max_length=10, null=True)),
                ('region', models.CharField(blank=True, choices=[('TRT', 'Toronto'), ('', 'United States')], max_length=10, null=True)),
                ('currency', models.CharField(blank=True, choices=[('CAD', 'Canadian Dollar'), ('USD', 'US Dollar')], max_length=3, null=True)),
                ('last_updated', models.DateField(blank=True, null=True)),
                ('searchable', models.BooleanField(default=True)),
                ('validated', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='ExchangeRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('us_to_can', models.FloatField()),
                ('can_to_us', models.FloatField()),
                ('source', models.PositiveIntegerField(choices=[(1, 'MANUAL'), (2, 'API'), (3, 'UPLOAD'), (4, 'ESTIMATE')], default=4)),
            ],
        ),
        migrations.CreateModel(
            name='Inflation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('cost', models.FloatField()),
                ('inflation', models.FloatField()),
                ('source', models.PositiveIntegerField(choices=[(1, 'MANUAL'), (2, 'API'), (3, 'UPLOAD'), (4, 'ESTIMATE')], default=4)),
            ],
        ),
        migrations.CreateModel(
            name='Portfolio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Enter a unique name for this portfolio', max_length=128, unique=True)),
                ('explicit_name', models.CharField(blank=True, help_text='The name as imported', max_length=128, null=True, unique=True)),
                ('managed', models.BooleanField(default=True)),
                ('currency', models.CharField(blank=True, choices=[('CAD', 'Canadian Dollar'), ('USD', 'US Dollar')], default='CAD', max_length=3, null=True)),
                ('cost', models.IntegerField(blank=True, null=True)),
                ('value', models.IntegerField(blank=True, null=True)),
                ('dividends', models.IntegerField(blank=True, null=True)),
                ('start', models.DateField(blank=True, null=True)),
                ('end', models.DateField(blank=True, help_text='Date this portfolio was Closed', null=True)),
                ('last_import', models.DateField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='EquityAlias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.TextField()),
                ('name', models.TextField()),
                ('equity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stocks.equity')),
            ],
        ),
        migrations.CreateModel(
            name='EquityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('value', models.FloatField()),
                ('event_type', models.TextField(choices=[('Dividend', 'Dividend'), ('SplitAD', 'Stock Split with Adjusted Dividends'), ('Split', 'Stock Split')], max_length=10)),
                ('source', models.IntegerField(choices=[(1, 'MANUAL'), (2, 'API'), (3, 'UPLOAD'), (4, 'ESTIMATE')], default=1)),
                ('equity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stocks.equity')),
            ],
        ),
        migrations.CreateModel(
            name='EquityValue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('price', models.FloatField()),
                ('source', models.IntegerField(choices=[(1, 'MANUAL'), (2, 'API'), (3, 'UPLOAD'), (4, 'ESTIMATE')], default=1)),
                ('equity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stocks.equity')),
            ],
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('price', models.FloatField()),
                ('quantity', models.FloatField()),
                ('value', models.FloatField(blank=True, null=True)),
                ('xa_action', models.IntegerField(choices=[(1, 'Fund'), (2, 'Buy'), (3, 'Reinvested Dividend'), (4, 'Sell'), (6, 'Interest'), (5, 'Redeem')])),
                ('equity', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='stocks.equity')),
                ('portfolio', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='stocks.portfolio')),
            ],
        ),
    ]
