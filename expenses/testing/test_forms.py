from datetime import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.models import Category, SubCategory, Item
from expenses.forms import SubCategoryForm, TemplateForm, UploadFileForm, ItemListEditForm


class CleanTests(TestCase):

    def setUp(self):

        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.user = User.objects.create_user(username='test', password='test')
        self.category = Category.objects.create(name='test')
        self.subcategory = SubCategory.objects.create(name='test1', category=self.category)
        self.item = Item.objects.create(date=datetime.now().date(), description='foo', amount=100, category=self.category, subcategory=self.subcategory,
                                        ignore=False, split=None, amortized=None, notes='Notes')

    def test_subcategory(self):
        form_data = {'category': self.category, 'user': self.user, 'name': 'test'}
        form = SubCategoryForm(data=form_data, initial={'user': self.user})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['name'], 'Test', 'Forced capitalization')

        subcategory = SubCategory.objects.create(category=self.category, name='Test')
        form = SubCategoryForm(data=form_data, initial={'user': self.user})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'name': ['This subcategory already exists']})

        user2 = User.objects.create_user(username='test2', password='test2')
        subcategory.user = user2
        subcategory.save()

        form = SubCategoryForm(data=form_data, initial={'user': self.user})
        self.assertTrue(form.is_valid(), 'Duplicate subcategories support when owned by user')

        form = SubCategoryForm(data=form_data, initial={'user': user2})
        self.assertFalse(form.is_valid(), 'Duplicate subcategories support when owned by user')
        self.assertDictEqual(form.errors, {'name': ['This subcategory already exists']})

    def test_templates(self):
        form_data = {"user": self.user, 'type': "starts", "expression": "foobar", "category": self.category, "subcategory": self.subcategory, "ignore": False}
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertTrue(form.is_valid())

        form_data["expression"] = "foo$bar"
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'expression': ['Expression can not contain a "$" character']})

        form_data["expression"] = "foobar"
        form_data["type"] = "starts"
        form = TemplateForm(data=form_data, initial={'expression': 'bar'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'expression': ['Expression foobar is not valid with "Starts With"  bar']})

        form_data["type"] = "ends"
        form = TemplateForm(data=form_data, initial={'expression': 'foo'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'expression': ['Expression foobar is not valid with "Ends With"  foo']})

        form_data["type"] = "contains"
        form = TemplateForm(data=form_data, initial={'expression': 'snafu'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'expression': ['Expression foobar is not valid with "Contains"  snafu']})

        form_data = {"user": self.user, 'type': "starts", "expression": "foobar", "category": self.category, "subcategory": self.subcategory, "ignore": True}
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'ignore': ['You can not Ignore a record if you have supplied a category']})

        form_data = {"user": self.user, 'type': "starts", "expression": "foobar", "category": self.category, "subcategory": None, "ignore": False}
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'subcategory': ['A subcategory is required if you enter a category']})

        form_data = {"user": self.user, 'type': "starts", "expression": "foobar", "category": None, "subcategory": self.subcategory, "ignore": False}
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'__all__': ['A template must specify "Ignore" or a Category/Subcategory pair']})

        form_data = {"user": self.user, 'type': "starts", "expression": "foobar", "category": None, "subcategory": None, "ignore": True}
        form = TemplateForm(data=form_data, initial={'expression': 'foobar'})
        self.assertTrue(form.is_valid())

    def test_uploads(self):
        good_values = ('.csv', '.ods', '.xls', '.xlsx')
        uploaded_file = SimpleUploadedFile('test.csv', 'foobar'.encode('utf-8'), content_type="text/plain")

        for value in good_values:
            uploaded_file = SimpleUploadedFile(f'test{value}', 'foobar'.encode('utf-8'), content_type="text/plain")

            # Instantiate the form with the file
            form = UploadFileForm({'has_headings': True}, {'upload_file': uploaded_file})
            self.assertTrue(form.is_valid())

        uploaded_file = SimpleUploadedFile('test.txt', 'foobar'.encode('utf-8'), content_type="text/plain")
        form = UploadFileForm({'has_headings': False}, {'upload_file': uploaded_file})
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'upload_file': ['Warning: file type .txt is not supported.']})

    def test_itemlist(self):
        data = {'date': self.item.date, 'description':self.item.description, 'amount': self.item.amount}
        form = ItemListEditForm(data=data, instance=self.item)
        self.assertTrue(form.is_valid())

        data['category'] = self.category
        form = ItemListEditForm(data=data, instance=self.item)
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'__all__': [f'Error: Category {self.category.name} missing Subcategory.']})

        data.pop('category')
        data['subcategory'] = self.subcategory
        form = ItemListEditForm(data=data, instance=self.item)
        self.assertFalse(form.is_valid())
        self.assertDictEqual(form.errors, {'__all__': [f'Error: Subcategory {self.subcategory.name} missing Category.']})

        data['category'] = self.category
        form = ItemListEditForm(data=data, instance=self.item)
        self.assertTrue(form.is_valid())

# Used in the search javascript

