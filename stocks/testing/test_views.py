import os

from django.template.response import TemplateResponse
from freezegun import freeze_time
from datetime import datetime

from django.contrib.auth.models import User
from django.urls.base import reverse
from django.test import Client, TestCase, override_settings, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from urllib.parse import urlencode

from base.models import Profile
from stocks.models import Equity, FundValue, EquityValue, Transaction, Account, Portfolio
from stocks.testing.setup import BasicSetup


class AuthorizedTest(BasicSetup):

    def test_logged_in(self):
        """
        Test are here to ensure I don't remove the login required by accident
        """
        self.client = Client()
        result = self.client.get(reverse('stocks_main'))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_add'))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_details', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_edit', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_delete', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('value_account_reconcile', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('cash_account_reconcile', kwargs={'pk': self.cash_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_table', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_table', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))

        result = self.client.get(reverse('account_table', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 302)
        self.assertTrue(result.url.startswith('/accounts/login/'))


    def test_other_user(self):
        """
        Just in case I accidentally remove the user check.
        """
        self.client = Client()

        other_user = User.objects.create(username='Other')
        Profile.objects.create(user=other_user, currency='CAN')
        self.client.force_login(other_user)

        result = self.client.get(reverse('account_details', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('account_edit', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('account_delete', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('value_account_reconcile', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 404)

class ViewTest(BasicSetup):
    def setUp(self):
        super().setUp()
        # print(self.__class__.__name__, self._testMethodName)
        self.client = Client()
        self.client.force_login(self.user)
        self.account = self.investment_account


    @freeze_time("2022-06-01")
    def test_main(self):
        """
        value account value is 1000
        cash account value is 500
        """
        result = self.client.get(reverse('stocks_main'))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.context_data['account_list_data']), 7, 'List returned')
        self.assertEqual(result.context_data['account_list_data'][0]['Value'], 1000, 'Sorted by value.')
        self.assertEqual(result.context_data['account_list_data'][0]['Id'], self.value_account.id, 'Sorted by value.')

        self.investment_account.user = None
        self.investment_account.save()
        FundValue.objects.filter(equity=Equity.objects.get(symbol=self.cash_account.f_key), date=datetime(2022,6,1).date()).update(value=1001)
        result = self.client.get(reverse('stocks_main'))
        self.assertEqual(len(result.context_data['account_list_data']), 6, 'List excludes none owned')
        self.assertEqual(result.context_data['account_list_data'][0]['Value'], 1001, 'Sorted by value.')
        self.assertEqual(result.context_data['account_list_data'][0]['Id'], self.cash_account.id, 'Sorted by value.')


        self.value_account.portfolio = self.portfolio
        self.value_account.save()
        self.target_value_account.portfolio = self.portfolio
        self.target_value_account.save()

        result = self.client.get(reverse('stocks_main'))
        self.assertEqual(len(result.context_data['account_list_data']), 4, 'List excludes in Portfolio')
        self.assertEqual(result.context_data['account_list_data'][0]['Value'], 1001, 'Sorted by value.')
        self.assertEqual(result.context_data['account_list_data'][0]['Id'], self.cash_account.id, 'Sorted by value.')

        FundValue.objects.filter(equity=Equity.objects.get(symbol=self.value_account.f_key), date=datetime(2022,6,1).date()).update(value=1002)

        result = self.client.get(reverse('stocks_main'))
        self.assertEqual(len(result.context_data['account_list_data']), 4, 'List excludes in Portfolio')
        self.assertEqual(result.context_data['account_list_data'][0]['Value'], 1002, 'Sorted by value.')
        self.assertEqual(result.context_data['account_list_data'][0]['Id'], self.portfolio.id, 'Sorted by value.')

    def test_account_add(self):
        result = self.client.get(reverse('account_add'))
        self.assertEqual(result.status_code, 200)

        result = self.client.post(reverse('account_add'), {'account_name': 'fooc', 'name': 'barc', 'account_type': 'Cash', 'currency': 'CAD',
                                                           'user':self.user.id, 'managed': False})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.url, reverse('stocks_main'))
        account = Account.objects.get(name='barc', user=self.user)
        self.assertTrue(Equity.objects.filter(symbol=account.f_key).exists())

        result = self.client.post(reverse('account_add'), {'name': 'foov', 'account_type': 'Value', 'currency': 'CAD',
                                                           'user':self.user.id, 'managed': False})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(result.url, reverse('stocks_main'))
        account = Account.objects.get(name='foov', user=self.user)
        self.assertTrue(Equity.objects.filter(symbol=account.f_key).exists())

        result = self.client.post(reverse('account_add'), {'name': 'fooi', 'account_type': 'Investment', 'currency': 'CAD',
                                                           'user':self.user.id, 'managed': False})
        self.assertEqual(result.status_code, 302)
        self.assertTrue(Account.objects.filter(account_name='fooi', user=self.user).exists(), 'Default account name test')

    def test_account_details(self):
        result = self.client.get(reverse('account_details', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 200)

        self.assertEqual(result.context_data['object_type'], 'Account')
        self.assertEqual(result.context_data['can_update'], True)
        self.assertEqual(result.context_data['view_type'], 'Chart')

    def test_account_edit(self):
        acct = self.investment_account
        result = self.client.get(reverse('account_edit', kwargs={'pk': acct.id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context_data['view_verb'], 'Edit')
        self.assertEqual(result.context_data['form'].initial['currency'], acct.currency)
        self.assertEqual(result.context_data['form'].initial['managed'], acct.managed)
        self.assertEqual(result.context_data['form'].initial['account_type'], acct.account_type)
        self.assertEqual(result.context_data['form'].initial['name'], acct.name)
        self.assertEqual(result.context_data['form'].initial['user'], self.user)

        post_data = {'user': self.user.id, 'managed': acct.managed, 'currency': acct.currency,
                     'account_type': acct.account_type, 'name': acct.name, 'account_name': acct.account_name}

        url = reverse('account_edit', kwargs={'pk': self.investment_account.id})
        result = self.client.post(url, post_data)
        self.assertEqual(result.status_code, 302)
        updated = Account.objects.get(id=self.investment_account.id)
        self.assertEqual(self.investment_account.currency, updated.currency)
        self.assertEqual(self.investment_account.account_type, updated.account_type)
        self.assertEqual(self.investment_account.name, updated.name)
        self.assertEqual(self.investment_account.managed, updated.managed)
        self.assertEqual(self.user, updated.user)

        post_data['account_name'] = 'ERROR'
        result = self.client.post(url, post_data)
        self.assertEqual(result.status_code, 200)
        post_data['account_name'] = self.investment_account.account_name

        post_data['account_type'] = 'ERROR'
        result = self.client.post(url, post_data)
        self.assertEqual(result.status_code, 200)
        post_data['account_type'] = self.investment_account.account_type

        post_data['managed'] = not self.investment_account.managed
        post_data['currency'] = 'USD'
        post_data['name'] = 'New Name'
        post_data['portfolio'] = self.portfolio.id
        result = self.client.post(url, post_data)
        self.assertEqual(result.status_code, 302)
        updated = Account.objects.get(id=self.investment_account.id)
        self.assertNotEqual(updated.currency, self.investment_account.currency)
        self.assertNotEqual(updated.managed, self.investment_account.managed)
        self.assertNotEqual(updated.name, self.investment_account.name)
        self.assertEqual(updated.portfolio, self.portfolio)

        post_data['portfolio'] = None
        result = self.client.post(url, post_data)
        self.assertEqual(result.status_code, 302)
        updated = Account.objects.get(id=self.investment_account.id)
        self.assertIsNone(updated.portfolio)

    def test_account_delete(self):
        result = self.client.get(reverse('account_delete', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 200)

        self.assertEqual(result.context_data['object_type'], 'Account')
        self.assertIsNotNone(result.context_data['extra_text'])
        self.assertIsNotNone(result.context['success_url'])

        result = self.client.post(reverse('account_delete', kwargs={'pk': self.investment_account.id}), {'success_url': 'foo'})
        self.assertEqual(result.status_code, 302)
        self.assertFalse(Account.objects.filter(id=self.investment_account.id).exists())

    def test_value_account_reconcile(self):
        expected = [
            {'date':datetime(2022, 6, 1).date(),'reported_date':datetime(2022, 6, 1).date(),'value':1000,'source':'USER','deposited':0,'withdrawn': 0},
            {'date':datetime(2022, 5, 1).date(),'reported_date':datetime(2022, 5, 1).date(),'value':1000,'source':'USER','deposited':0,'withdrawn': 0},
            {'date':datetime(2022, 4, 1).date(),'reported_date':datetime(2022, 4, 1).date(),'value':1000,'source':'USER','deposited':0,'withdrawn': 0},
            {'date':datetime(2022, 3, 1).date(),'reported_date':datetime(2022, 3, 1).date(),'value':1000,'source':'USER','deposited':0,'withdrawn': 0},
            {'date':datetime(2022, 2, 1).date(),'reported_date':datetime(2022, 2, 1).date(),'value':1000,'source':'USER','deposited':0,'withdrawn': 0},
            {'date':datetime(2022, 1, 1).date(),'reported_date':datetime(2022, 1, 1).date(),'value':1000,'source':'USER','deposited':1000,'withdrawn': 0},
        ]
        account = self.value_account
        result = self.client.get(reverse('value_account_reconcile', kwargs={'pk': account.id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.context['formset'].initial), 6, 'Every month with a value record gets a form')
        self.assertEqual(result.context['formset'].initial, expected)
        pass

    def test_cash_account_reconcile(self):
        expected = [
            {'date':datetime(2022, 6, 1).date(),'reported_date':datetime(2022, 6, 1).date(),'value':500,'source':'USER'},
            {'date':datetime(2022, 5, 1).date(),'reported_date':datetime(2022, 5, 1).date(),'value':500,'source':'USER'},
            {'date':datetime(2022, 4, 1).date(),'reported_date':datetime(2022, 4, 1).date(),'value':500,'source':'USER'},
            {'date':datetime(2022, 3, 1).date(),'reported_date':datetime(2022, 3, 1).date(),'value':500,'source':'USER'},
            {'date':datetime(2022, 2, 1).date(),'reported_date':datetime(2022, 2, 1).date(),'value':500,'source':'USER'},
            {'date':datetime(2022, 1, 1).date(),'reported_date':datetime(2022, 1, 1).date(),'value':500,'source':'USER'},
        ]
        account = self.cash_account
        result = self.client.get(reverse('cash_account_reconcile', kwargs={'pk': account.id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.context['formset'].initial), 6, 'Every month with a value record gets a form')
        self.assertEqual(result.context['formset'].initial, expected)
        pass

    def test_account_table(self):
        result = self.client.get(reverse('account_table', kwargs={'pk': self.investment_account.id}))
        self.assertEqual(result.status_code, 200)

        self.assertEqual(result.context_data['object_type'], 'Account')
        self.assertEqual(result.context_data['can_reconcile'], True)
        self.assertEqual(result.context_data['view_type'], 'Data')

    def test_account_equity_details(self):
        data = [{'Date': '2022-Jun', 'Shares': 50.0, 'Cost': 500.0, 'Value': 500.0, 'Price': 10.0, 'TotalDividends': 5.0, 'AvgCost': 10.0, 'AdjValue': 505.0},
                {'Date': '2022-May', 'Shares': 50.0, 'Cost': 500.0, 'Value': 500.0, 'Price': 10.0, 'TotalDividends': 5.0, 'AvgCost': 10.0, 'AdjValue': 505.0},
                {'Date': '2022-Apr', 'Shares': 50.0, 'Cost': 500.0, 'Value': 500.0, 'Price': 10.0, 'TotalDividends': 2.5, 'AvgCost': 10.0, 'AdjValue': 502.5},
                {'Date': '2022-Mar', 'Shares': 50.0, 'Cost': 500.0, 'Value': 500.0, 'Price': 10.0, 'TotalDividends': 2.5, 'AvgCost': 10.0, 'AdjValue': 502.5},
                {'Date': '2022-Feb', 'Shares': 50.0, 'Cost': 500.0, 'Value': 500.0, 'Price': 10.0, 'TotalDividends': 2.5, 'AvgCost': 10.0, 'AdjValue': 502.5}]

        result = self.client.get(reverse('account_equity_details', kwargs={'container_type': 'Account', 'pk': self.investment_account.id, 'id': 0}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('account_equity_details', kwargs={'container_type': 'Account', 'pk': 0, 'id': self.equities[0].id}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('account_equity_details', kwargs={'container_type': 'Account', 'pk': self.investment_account.id, 'id': self.equities[0].id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context['data'], data)
        self.assertEqual(result.context['account_type'], 'Account')
        self.assertEqual(result.context['container'], Account.objects.get(id=self.investment_account.id))
        self.assertEqual(result.context['xas'].count(), 1)
        self.assertEqual(result.context['equity'], self.equities[0])

        result = self.client.get(reverse('account_equity_details', kwargs={'container_type': 'Account', 'pk': self.investment_account.id, 'id': self.equities[1].id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context['data'], [])
        self.assertEqual(result.context['xas'].count(), 0)
        self.assertEqual(result.context['equity'], self.equities[1])

        Account.objects.filter(id=self.investment_account.id).update(portfolio=self.portfolio)
        result = self.client.get(reverse('account_equity_details', kwargs={'container_type': 'Portfolio', 'pk': self.portfolio.id, 'id': self.equities[0].id}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context['data'], data)
        self.assertEqual(result.context['account_type'], 'Portfolio')
        self.assertEqual(result.context['container'], self.portfolio)
        self.assertEqual(result.context['xas'].count(), 1)
        self.assertEqual(result.context['equity'], self.equities[0])

    def test_update_account_date(self):
        expected = [
            {'Equity': self.equities[0], 'Object_ID': 5, 'Cost': 500.0, 'Value': 500.0, 'Shares': 50.0, 'Dividends': 2.5, 'TotalDividends': 2.5,
            'Price': 10.0, 'equity_id': 5, 'Bought': 500.0, 'Bought_Price': 10.0, 'Reinvested': None, 'Reinvested_Price': None, 'Sold': None,
             'Sold_Price': None}]

        result = self.client.get(reverse('update_account_date', kwargs={'a_pk': self.investment_account.id, 'date_str': 'FooBar-2022'}))
        self.assertEqual(result.status_code, 404)

        result = self.client.get(reverse('update_account_date', kwargs={'a_pk': self.investment_account.id, 'date_str': 'Feb-2022'}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context['formset'].initial, expected)

        result = self.client.get(reverse('update_account_date', kwargs={'a_pk': self.investment_account.id, 'date_str': 'Feb-1961'}))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context['formset'].initial, [])  # A pretty useless page.