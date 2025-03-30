import os

from django.contrib.auth.models import User
from django.urls.base import reverse
from django.test import Client, TestCase, override_settings, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from urllib.parse import urlencode

from expenses.models import Category, SubCategory

class BasicSetup(TestCase):
    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.user = User.objects.create(username='_test', is_superuser=False, is_staff=False, is_active=True)
        self.client = Client()
        self.client.force_login(self.user)

        self.cat1 = Category.objects.create(name='Cat1')
        self.cat2 = Category.objects.create(name='Cat2')
        self.subcat1 = SubCategory.objects.create(name='SubCat1-1', category=self.cat1)
        self.subcat2 = SubCategory.objects.create(name='SubCat1-2', category=self.cat1)
        self.subcat3 = SubCategory.objects.create(name='SubCat2-1', category=self.cat2)
        self.subcat4 = SubCategory.objects.create(name='SubCat2-2', category=self.cat2)

    def test_subcategory(self):
        result = self.client.get(reverse('subcategory_add'))
        self.assertEqual(result.status_code, 200)

        result = self.client.post(reverse('subcategory_add'), {'category': self.cat1.id, 'name': 'foobar', 'user':self.user.id})
        self.assertEqual(result.status_code, 302)
        self.assertTrue(SubCategory.objects.filter(category=self.cat1, name='Foobar').exists(), 'SubCategory creation failed')
        self.assertEqual(result.url, '/expenses/main/', 'Default return URL')
        SubCategory.objects.filter(category=self.cat1, name='Foobar').delete()

        result = self.client.post(reverse('subcategory_add'), {'success_url': 'foobar', 'category': self.cat1.id, 'name': 'foobar', 'user': self.user.id})
        self.assertEqual(result.status_code, 302)
        self.assertTrue(SubCategory.objects.filter(category=self.cat1, name='Foobar').exists(), 'SubCategory creation failed')
        self.assertEqual(result.url, 'foobar', 'requested return URL')
        SubCategory.objects.filter(category=self.cat1, name='Foobar').delete()






