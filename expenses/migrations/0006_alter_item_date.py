# Generated by Django 4.2 on 2024-08-19 13:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0005_item_split'),
    ]

    operations = [
        migrations.AlterField(
            model_name='item',
            name='date',
            field=models.DateField(verbose_name='Date'),
        ),
    ]
