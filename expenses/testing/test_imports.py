import csv
import os
import pandas as pd

from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, SimpleTestCase
from django.urls.base import reverse

from typing import List

from expenses.importers import import_dataframe, find_headers_errors
from expenses.models import Item, Category, SubCategory, Template


class ImporterTests(TestCase):
    def setUp(self):
        super().setUp()

        self.user = User.objects.create_user(username='test', password='test')
        self.cat1 = Category.objects.create(name='Cat1')
        self.cat2 = Category.objects.create(name='Cat2')
        self.subcat1 = SubCategory.objects.create(name='SubCat1-1', category=self.cat1)
        self.subcat2 = SubCategory.objects.create(name='SubCat1-2', category=self.cat1)
        self.subcat3 = SubCategory.objects.create(name='SubCat2-1', category=self.cat2)
        self.subcat4 = SubCategory.objects.create(name='SubCat2-2', category=self.cat2)

    def test_basic(self):

        min_dict = [{'Date': '2017-12-29', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21.69, },
                    {'Date': '2017-12-29', 'Description': 'LCBO/RAO #23 NEPEAN, ON', 'Amount': 39.54, }]

        self.assertEqual(Item.objects.count(),0)
        df = pd.DataFrame.from_records(data=min_dict)
        import_dataframe(df, self.user)
        self.assertEqual(Item.objects.count(),len(min_dict))

        import_dataframe(df, self.user)
        self.assertEqual(Item.objects.count(), len(min_dict) * 2)

    def test_failures(self):

        with self.assertLogs(level='WARNING') as captured:
            df = pd.DataFrame()
            import_dataframe(df, self.user)
            self.assertEqual(len(captured.records), 1, 'Warning with empty DF')
            self.assertEqual(captured.records[0].levelname, 'WARNING', 'Attempted to import an empty dataframe')
            self.assertEqual(captured.records[0].message,'Attempted to import an empty dataframe')

        with self.assertLogs(level='ERROR') as captured:
            my_dict = [{'Foo': '2017-12-29', 'Bar': 'FARM BOY #90 NEPEAN, ON', 'FooBar': 21.69, }]
            df = pd.DataFrame.from_records(data=my_dict)
            import_dataframe(df, self.user)
            self.assertEqual(len(captured.records), 1, 'Error with invalid columns')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Attempted to import an empty dataframe')
            self.assertEqual(captured.records[0].message, 'Invalid Columns in DataFrame Foo,Bar,FooBar')

    def test_categories(self):
        my_dict = [{'Date': '2017-12-29', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21.69, 'Category': self.cat1.name, 'Subcategory': self.subcat1.name},
                   {'Date': '2017-12-29', 'Description': 'LCBO/RAO #23 NEPEAN, ON', 'Amount': 39.54, 'Category': self.cat2.name, 'Subcategory': self.subcat3.name}]

        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertEqual(Item.objects.count(), len(my_dict))
        self.assertTrue(Item.objects.filter(amount=21.69, category=self.cat1, subcategory=self.subcat1).exists())
        self.assertTrue(Item.objects.filter(amount=39.54, category=self.cat2, subcategory=self.subcat3).exists())

        my_dict = [{'Date': '2017-12-30', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21.69, 'Category': self.cat1.name, 'Subcategory': 'newsubcat'}]
        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertTrue(Item.objects.filter(amount=21.69, category=self.cat1, subcategory__name='newsubcat').exists())
        subcat = SubCategory.objects.get(name='newsubcat')
        self.assertTrue(subcat.category == self.cat1)

        my_dict = [{'Date': '2017-12-30', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21, 'Category': self.cat1.name, 'Subcategory': 'newsubcat'}]
        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertTrue(Item.objects.filter(amount=21, category=self.cat1, subcategory__name='newsubcat').exists())
        self.assertEqual(SubCategory.objects.filter(name='newsubcat').count(), 1)

    def test_categories_samesub(self):

        my_dict = [{'Date': '2017-12-29', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21.69, 'Category': self.cat1.name, 'Subcategory': self.subcat1.name},
                   {'Date': '2017-12-29', 'Description': 'LCBO/RAO #23 NEPEAN, ON', 'Amount': 39.54, 'Category': self.cat1.name, 'Subcategory': self.subcat1.name}]

        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertEqual(Item.objects.count(), len(my_dict))
        self.assertTrue(Item.objects.filter(amount=21.69, category=self.cat1, subcategory=self.subcat1).exists())
        self.assertTrue(Item.objects.filter(amount=39.54, category=self.cat1, subcategory=self.subcat1).exists())

    def test_other_fields(self):
        my_dict = [{'Date': '2017-12-30', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21, 'Hidden': True, 'Details': 'details', 'Notes': 'notes'}]
        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertTrue(Item.objects.filter(amount=21, ignore=True, details='details', notes='notes').exists())

        my_dict = [{'Date': '2017-12-30', 'Description': 'FARM BOY #90 NEPEAN, ON', 'Amount': 21, 'Hidden': False}]
        df = pd.DataFrame.from_records(data=my_dict)
        import_dataframe(df, self.user)
        self.assertTrue(Item.objects.filter(amount=21, ignore=False, details__isnull=True, notes__isnull=True).exists())


class HeaderTests(SimpleTestCase):

    def test_basic(self):
        result = find_headers_errors(['Date', 'Description', 'Amount'])
        self.assertFalse(result, 'Minimum headers test')

        result = find_headers_errors(['Description', 'Amount'])
        self.assertTrue(result, 'Missing Date')
        self.assertEqual(result[0][0], 'A Date column is required', 'Missing field in Column 0')

        result = find_headers_errors(['Date', 'Amount'])
        self.assertTrue(result, 'Missing Date')
        self.assertEqual(result[0][0], 'A Description column is required', 'Missing field in Column 0')

        result = find_headers_errors(['Description', 'Date'])
        self.assertTrue(result, 'Missing Date')
        self.assertEqual(result[0][0], 'Amount or Debit and Credit are required', 'Missing field in Column 0')

        result = find_headers_errors(['Date', 'Description', 'Amount', 'Debit', 'Credit'])
        self.assertTrue(result, 'Conflicting Date')
        self.assertEqual(result[3][0], 'Invalid when Amount is selected', 'Missing field in Column 0')
        self.assertEqual(result[4][0], 'Invalid when Amount is selected', 'Missing field in Column 0')

        result = find_headers_errors(['Date', 'Description', 'Amount', 'Date'])
        self.assertTrue(result, 'Duplicate')
        self.assertEqual(result[3][0], 'Duplicate heading selected', 'Missing field in Column 0')


class BasicSetup(TestCase):
    @staticmethod
    def create_csv(data: List, csv_file: str):
        with open(csv_file, "w", newline="") as file:
            writer = csv.writer(file)
            for row in data:
                writer.writerow(row.split(","))

    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.user = User.objects.create(username='_test', is_superuser=False, is_staff=False, is_active=True)
        self.client = Client()
        self.client.force_login(self.user)
        self.default_headers = 'Date,Description,Amount,foobar,Details'
        self.default_data = []
        self.formset_data = {
            "form-TOTAL_FORMS": "5",  # Two forms in this submission
            "form-INITIAL_FORMS": "5",
            "form-0-header": "ignore", "form-0-example0": "_", "form-0-example1": "_", "form-0-example2": "_", "form-0-example3": "_", "form-0-example4": "_",
            "form-1-header": "ignore", "form-1-example0": "_", "form-1-example1": "_", "form-1-example2": "_", "form-1-example3": "_", "form-1-example4": "_",
            "form-2-header": "ignore", "form-2-example0": "_", "form-2-example1": "_", "form-2-example2": "_", "form-2-example3": "_", "form-2-example4": "_",
            "form-3-header": "ignore", "form-3-example0": "_", "form-3-example1": "_", "form-3-example2": "_", "form-3-example3": "_", "form-3-example4": "_",
            "form-4-header": "ignore", "form-4-example0": "_", "form-4-example1": "_", "form-4-example2": "_", "form-4-example3": "_", "form-4-example4": "_",
        }
        self.noheader_data = [
            '2017-12-29,"FARM BOY #90 NEPEAN, ON",21.69,,4500********9312',
            '2017-12-29,"LCBO/RAO #23 NEPEAN, ON",39.54,,4500********0011',
            '2017-12-29,"THE HOME DEPOT",,21.29,4500********9312',
            '2017-12-29,"LCBO/RAO #670 NEPEAN, ON",32.75,,4500********9312',
            '2017-12-29,"1057 SAJE BAYSHORE NEPEAN, ON",101.64,,4500********9312',
        ]
        self.header_data = [
            'Date,Description,Amount,foobar,Details',
            '2017-12-29,"FARM BOY #90 NEPEAN, ON",21.69,,4500********9312',
            '2017-12-29,"LCBO/RAO #23 NEPEAN, ON",39.54,,4500********0011',
            '2017-12-29,"THE HOME DEPOT",,21.29,4500********9312',
            '2017-12-29,"LCBO/RAO #670 NEPEAN, ON",32.75,,4500********9312',
            '2017-12-29,"1057 SAJE BAYSHORE NEPEAN, ON",101.64,,4500********9312',
        ]


class UploadViewTest(BasicSetup):

    def test_noheaders(self):
        result = self.client.get(reverse('expenses_upload'))
        self.assertEqual(result.status_code, 200)

        content = '\n'.join(self.noheader_data)
        uploaded_file = SimpleUploadedFile('test.csv', content.encode('utf-8'), content_type="text/plain")
        result = self.client.post(reverse('expenses_upload'), data={'upload_file': uploaded_file, 'has_headings': False},  format="multipart")
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/expenses/upload/'))
        self.assertTrue(result.url.endswith('/False/confirm/'))
        file_path = default_storage.base_location.joinpath('uploads', result.url.split('/')[3])
        self.assertTrue(file_path.exists())
        os.remove(file_path)

    def test_headers(self):
        content = '\n'.join(self.header_data)
        uploaded_file = SimpleUploadedFile('test.csv', content.encode('utf-8'), content_type="text/plain")
        result = self.client.post(reverse('expenses_upload'), data={'upload_file': uploaded_file, 'has_headings': True}, format="multipart")

        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/expenses/upload/'))
        self.assertTrue(result.url.endswith('/process/'))
        file_path = default_storage.base_location.joinpath('uploads', result.url.split('/')[3])
        self.assertTrue(file_path.exists())
        os.remove(file_path)

    def test_bad_headers(self):

        self.header_data[0] = 'foo,Description,Amount,foobar,Details'

        content = '\n'.join(self.header_data)
        uploaded_file = SimpleUploadedFile('test.csv', content.encode('utf-8'), content_type="text/plain")
        result = self.client.post(reverse('expenses_upload'), data={'upload_file': uploaded_file, 'has_headings': True}, format="multipart")

        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/expenses/upload/'))
        self.assertTrue(result.url.endswith('/True/confirm/'))
        file_path = default_storage.base_location.joinpath('uploads', result.url.split('/')[3])
        os.remove(file_path)


class ColumnCorrectTest(BasicSetup):

    def setUp(self):
        super().setUp()
        self.file_name = 'testing.csv'
        self.file_path = default_storage.base_location.joinpath('uploads', self.file_name)

    def test_get(self):

        with self.assertLogs(level='ERROR') as captured:
            result = self.client.get(reverse('upload_confirm', kwargs={'uuid': self.file_name, 'headings': False}))
            self.assertEqual(len(captured.records), 1, 'Warning with empty DF')
            self.assertEqual(captured.records[0].levelname, 'ERROR', 'Log Level Test' )
            self.assertEqual(captured.records[0].message,f'File Not Found: {self.file_path}')
            self.assertEqual(result.status_code, 200)

        self.create_csv(self.noheader_data, self.file_path)

        with self.assertLogs(level='ERROR') as captured:
            result = self.client.get(reverse('upload_confirm', kwargs={'uuid': self.file_name, 'headings': False}))
            self.assertEqual(len(captured.records), 0, 'Good DF')
            self.assertEqual(result.status_code, 200)
        os.remove(self.file_path)

    def test_post(self):

        self.create_csv(self.noheader_data, self.file_path)
        self.formset_data["form-0-header"] = "Date"
        self.formset_data["form-1-header"] = "Description"
        self.formset_data["form-2-header"] = "Amount"
        result = self.client.post(reverse('upload_confirm', kwargs={'uuid': self.file_name, 'headings': False}), self.formset_data)
        pass


