# Generated by Django 5.0.9 on 2024-09-27 14:03

from django.db import migrations, models
from stocks.models import API

def create_initial(apps, schema_editor):
    API.objects.create(name='BOC', base='https://www.bankofcanada.ca/valet/observations/', _active=True)
    API.objects.create(name='AVURL', base='https://www.alphavantage.co/query?function=', _active=True)



class Migration(migrations.Migration):

    dependencies = [
        ('base', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='URL',
            fields=[
                ('name', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('base', models.CharField(max_length=132)),
                ('_active', models.BooleanField(default=True)),
                ('_last_fail', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.RunPython(create_initial)

    ]
