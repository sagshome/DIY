import csv
import logging

from copy import deepcopy
from datetime import datetime
from freezegun import freeze_time
from unittest.mock import patch, Mock

from django.test import TestCase
from expenses.importers import ExpenseImporter, Generic, CIBC_Visa
from expenses.models import Item, Category, SubCategory, Template

logger = logging.getLogger(__name__)

class DefaultData(TestCase):
    def setUp(self):
        super().setUp()
        self.cat1 = Category.objects.create(name='Cat1')
        self.cat2 = Category.objects.create(name='Cat2')
        self.subcat1 = SubCategory.objects.create(name='SubCat1-1', category=self.cat1)
        self.subcat2 = SubCategory.objects.create(name='SubCat1-2', category=self.cat1)
        self.subcat3 = SubCategory.objects.create(name='SubCat2-1', category=self.cat2)
        self.subcat4 = SubCategory.objects.create(name='SubCat2-2', category=self.cat2)

class TestCIBC_Visa(DefaultData):

    def setUp(self):
        super().setUp()
        self.data = [
            '2017-12-29,"FARM BOY #90 NEPEAN, ON",21.69,,4500********9312',
            '2017-12-29,"LCBO/RAO #23 NEPEAN, ON",39.54,,4500********0011',
            '2017-12-29,"THE HOME DEPOT",,21.29,4500********9312',
            '2017-12-29,"LCBO/RAO #670 NEPEAN, ON",32.75,,4500********9312',
            '2017-12-29,"1057 SAJE BAYSHORE NEPEAN, ON",101.64,,4500********9312',
        ]
        self.xa_date = datetime(2017,12,29).date()

    def test_import_simple(self):

        CIBC_Visa(csv.reader(self.data), 'VISA')
        self.assertEqual(Item.objects.count(), 5, 'Created 5 item')
        self.assertEqual(Item.objects.filter(category__isnull=True).count(), 5, 'No Categories')
        item: Item = Item.objects.get(date=self.xa_date, description='FARM BOY #90 NEPEAN, ON')
        self.assertIsNone(item.category)
        self.assertIsNone(item.subcategory)
        self.assertFalse(item.ignore)
        self.assertEqual(item.amount, 21.69)
        self.assertEqual(item.source, 'VISA')

        item = Item.objects.get(date=self.xa_date, description='THE HOME DEPOT')
        self.assertEqual(item.amount, -21.29, 'Credit applied as negative')


    def test_import_with_templates(self):
        t1 = Template.objects.create(type='starts', expression='LCBO/RAO', category=self.cat1, subcategory=self.subcat1)
        t2 = Template.objects.create(type='ends', expression='HOME DEPOT', category=self.cat1, subcategory=self.subcat2)
        t3 = Template.objects.create(type='contains', expression='SAJE', ignore=True)

        CIBC_Visa(csv.reader(self.data), 'VISA')
        self.assertEqual(Item.objects.count(), 5, 'Created 5 item')
        self.assertEqual(Item.objects.filter(category__isnull=True).count(), 2, 'Farm Boy and SAJE')
        self.assertEqual(Item.objects.filter(ignore=True).count(), 1, 'Ignore SAJE')
        self.assertEqual(Item.objects.filter(category=self.cat1).count(), 3, 'LCBO and Home Depot')
        self.assertEqual(Item.objects.filter(subcategory=self.subcat1).count(), 2, 'LCBO')


        t1.refresh_from_db()
        t2.refresh_from_db()
        t3.refresh_from_db()
        self.assertEqual(t1.count, 2)
        self.assertEqual(t2.count, 1)
        self.assertEqual(t3.count, 1)

class TestGeneric(TestCase):

    current = datetime(2020,9,1).date()

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.xa_date = datetime(2020, 9, 1).date()
        self.xa_description = 'CBD Source of Food'
        self.category = Category.objects.create(name='foo')
        self.subcategory = SubCategory.objects.create(name='bar', category=self.category)
        self.template = Template.objects.create(expression='^CBD Source',
                                                category=self.category, subcategory=self.subcategory)

    def test_import_simple(self):
        data = [
            'Date,Transaction,Amount',
            f'{self.xa_date},{self.xa_description},5'
        ]

        Generic(csv.reader(data), 'test')
        self.assertEqual(Item.objects.count(), 1, 'Created an item')
        item: Item = Item.objects.get(date=self.xa_date, description=self.xa_description)
        self.assertIsNone(item.category)
        self.assertIsNone(item.subcategory)
        self.assertEqual(item.amount, 5.0)
        self.assertEqual(item.source, 'test')


    def test_import_with_template(self):
        data = [
            'Date,Transaction,Amount,Detail',
            f'{self.xa_date},{self.xa_description},5, FooBar'
        ]

        Generic(csv.reader(data), 'test')
        self.assertEqual(Item.objects.count(), 1, 'Created an item')
        item: Item = Item.objects.get(date=self.xa_date, description=self.xa_description)
        self.assertEqual(item.category, self.category)
        self.assertEqual(item.subcategory, self.subcategory)

    def test_import_without_template(self):
        data = [
            'Date,Transaction,Amount,Detail',
            f'{self.xa_date},{self.xa_description},5, FooBar'
        ]

        Template.objects.filter(pk=self.template.pk).update(expression='Fish and Chips')

        Generic(csv.reader(data), 'test')
        self.assertEqual(Item.objects.count(), 1, 'Created an item')
        item: Item = Item.objects.get(date=self.xa_date, description=self.xa_description)
        self.assertIsNone(item.category)
        self.assertIsNone(item.subcategory)
