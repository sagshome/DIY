# Generated by Django 5.0.9 on 2024-09-18 00:32

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0006_account_acccount_name'),
    ]

    operations = [
        migrations.RenameField(
            model_name='account',
            old_name='acccount_name',
            new_name='account_name',
        ),
    ]
