# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)
import csv
import logging
import os
import json

import numpy as np
import pandas as pd

from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List, Dict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMessage
from django.db.models import Sum, Avg
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, Http404
from django.urls import reverse
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin

from base.utils import DIYImportException, normalize_today, normalize_date
from base.models import Profile

from .models import Account, Portfolio, Equity, EquityEvent, EquityValue, Transaction, BaseContainer, FundValue, DataSource
from .tasks import equity_new_estimates
from .forms import TransactionForm, PortfolioForm, AccountCloseForm, TransactionEditForm, AccountForm, UploadFileForm, AccountAddForm, TransactionSetValueForm, ManualUpdateEquityForm, AddEquityForm, SimpleCashReconcileFormSet, SimpleReconcileFormSet, ReconciliationFormSet
from .importers import QuestTrade, Manulife, ManulifeWealth, StockImporter, HEADERS


logger = logging.getLogger(__name__)


class BaseDeleteView(LoginRequiredMixin, DeleteView):
    template_name = 'stocks/basic_confirm_delete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['success_url'] = self.request.META.get('HTTP_REFERER', '/')
        return context

    def get_success_url(self):
        try:
            url = self.request.POST["success_url"]
        except AttributeError:
            url = super().get_success_url()
        return url


class AccountDeleteView(BaseDeleteView):
    model = Account
    template_name = 'stocks/basic_confirm_delete.html'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Account'
        context['extra_text'] = 'Deleting an account is permanent - All transaction will be removed..'
        return context


class PortfolioDeleteView(BaseDeleteView):
    model = Portfolio

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Portfolio'
        context['extra_text'] = 'Deleting a portfolio will NOT delete the accounts it contains,  you will need to delete them separately.'
        return context


class TransactionDeleteView(BaseDeleteView):
    model = Transaction

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Transaction'
        context['extra_text'] = 'Deleting a Transaction is permanent'
        return context


class StocksMain(LoginRequiredMixin, ListView):
    model = Account
    template_name = 'stocks/stocks_main.html'

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)

        account_list_data = []
        for portfolio in Portfolio.objects.filter(user=self.request.user):
            account_list_data.append(portfolio.summary)
        for account in Account.objects.filter(user=self.request.user, portfolio__isnull=True):
            account_list_data.append(account.summary)

        account_list_data = sorted(account_list_data, key=lambda x: x['Value'], reverse=True)
        context['account_list_data'] = account_list_data
        return context


class ContainerTableView(LoginRequiredMixin, DetailView):
    template_name = 'stocks/account_table.html'

    @staticmethod
    def container_data(myobj: BaseContainer):
        """
        Produce a trimmed down dataframe from the first to the last record
        """
        end = myobj.end
        equity_data = myobj.e_pd.groupby('Date').agg({'Cost': 'sum', 'TotalDividends': 'sum', 'Value': 'sum'}).reset_index()
        if len(myobj.p_pd):
            equity_data = pd.merge(equity_data, myobj.p_pd, how='right')

        equity_data.replace(np.nan, 0, inplace=True)  # Clear up any bad numbers
        equity_data.sort_values(by=['Date'], inplace=True, ascending=False)  # Sort by date in reverse order
        if end:
            return equity_data[equity_data['Date'] <= pd.to_datetime(end)]
        return equity_data


class AccountTableView(ContainerTableView):
    model = Account

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        a: Account = context['account']
        elist = a.equities.order_by('symbol')
        summary_data = self.container_data(a)
        try:
            summary_data['Date'] = summary_data['Date'].dt.strftime('%b-%Y')
            summary_data = json.loads(summary_data.to_json(orient='records'))
        except AttributeError:
            summary_data = {}
        # Build the table data as [date, (shares, value), (shares, value)... total_value
        return {'account': a,
                'summary_data': summary_data,
                'equities': elist,
                'view_type': 'Data',
                'equity_count': elist.count(),
                'can_reconcile': True,
                'object_type': 'Account',
                'xas': a.transactions.all().order_by('-real_date'),
                }


class PortfolioTableView(ContainerTableView):
    model = Portfolio

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        p: Portfolio = context['portfolio']
        elist = p.equities.order_by('symbol')
        summary_data = self.container_data(p)
        summary_data['Date'] = summary_data['Date'].dt.strftime('%b-%Y')

        # Build the table data as [date, (shares, value), (shares, value)... total_value
        return {'account': p,
                'account_list': p.account_set.all().order_by('-_start'),
                'summary_data': json.loads(summary_data.to_json(orient='records')),
                'equities': elist,
                'view_type': 'Data',
                'equity_count': elist.count(),
                'object_type': 'Portfolio',
                'can_reconcile': False
                }


class ContainerDetailView(LoginRequiredMixin, DetailView):

    template_name = 'stocks/container_detail.html'

    @staticmethod
    def equity_data(myobj: BaseContainer):
        this_date = np.datetime64(normalize_today())
        df = myobj.e_pd
        equity_data = df.loc[df['Date'] == this_date].groupby(['Date', 'Equity', 'Object_ID', 'Object_Type']).agg(
            {'Shares': 'sum', 'Cost': 'sum', 'Price': 'max', 'Dividends': 'max',
             'TotalDividends': 'sum', 'Value': 'sum', 'AvgCost': 'max',
             'RelGain': 'sum', 'UnRelGain': 'sum', 'RelGainPct': 'mean', 'UnRelGainPct': 'mean'}).reset_index()

        equity_data.replace(np.nan, 0, inplace=True)
        equity_data.sort_values(by=['Value'], inplace=True, ascending=False)
        return equity_data


class PortfolioDetailView(ContainerDetailView):
    model = Portfolio

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        p: Portfolio = context['portfolio']

        funded = p.transactions.filter(xa_action=Transaction.FUND)
        redeemed = p.transactions.filter(xa_action=Transaction.REDEEM)
        if funded.count() == 0:
            funded = 0
        else:
            funded = funded.aggregate(Sum('value'))['value__sum']
        if redeemed.count() == 0:
            redeemed = 0
        else:
            redeemed = redeemed.aggregate(Sum('value'))['value__sum'] * -1

        account_list_data = []
        for account in Account.objects.filter(user=self.request.user, portfolio=p):
            account_list_data.append(account.summary)
        account_list_data = sorted(account_list_data, key=lambda x: x['Value'], reverse=True)
        context['account_list_data'] = account_list_data

        return {'account': p,
                'account_list_data': account_list_data,
                'xas': p.transactions.order_by('-real_date', 'xa_action'),
                'can_update': False,
                'funded': funded,
                'redeemed': abs(redeemed),
                'view_type': 'Chart',
                'equity_list_data': json.loads(self.equity_data(p).to_json(orient='records')),
                'object_type': 'Portfolio',
                }


class AccountDetailView(ContainerDetailView):
    model = Account

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        profile = Profile.objects.get(user=self.request.user)
        can_update = True if profile.av_api_key else False
        account: Account = context['account']

        funded = account.transactions.filter(xa_action=Transaction.FUND)
        redeemed = account.transactions.filter(xa_action=Transaction.REDEEM)
        if funded.count() == 0:
            funded = 0
        else:
            funded = funded.aggregate(Sum('value'))['value__sum']
        if redeemed.count() == 0:
            redeemed = 0
        else:
            redeemed = redeemed.aggregate(Sum('value'))['value__sum'] * -1

        return {'account': account,
                'xas': account.transactions.order_by('-real_date', 'xa_action'),
                'can_update': can_update,
                'funded': funded,
                'redeemed': redeemed,
                'view_type': 'Chart',
                'equity_list_data': json.loads(self.equity_data(account).to_json(orient='records')),
                'object_type': 'Account',
                }


class PortfolioView(LoginRequiredMixin):
    model = Portfolio
    template_name = 'stocks/portfolio.html'
    form_class = PortfolioForm

    def get_success_url(self):
        return reverse('stocks_main', kwargs={})

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial


class PortfolioAdd(PortfolioView, CreateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Create'
        return context


class AccountCloseView(LoginRequiredMixin, UpdateView):
    model = Account
    template_name = 'stocks/account_close.html'
    form_class = AccountCloseForm

    def get_success_url(self):
        try:
            url = self.request.POST["success_url"]
        except AttributeError:
            url = reverse('stocks_main', kwargs={})
        return url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['success_url'] = self.request.META.get('HTTP_REFERER', '/')
        return context

    def get_initial(self):
        super().get_initial()
        accounts = Account.objects.filter(user=self.request.user, account_type=self.object.account_type, _end__isnull=True).exclude(id=self.object.id)
        if self.object.portfolio:
            accounts = accounts.filter(portfolio=self.object.portfolio)
        self.initial['accounts'] = accounts
        self.initial['user'] = self.request.user.id
        try:
            self.initial['_end'] = self.object.transactions.latest('real_date').real_date
        except Transaction.DoesNotExist:
            self.initial['_end'] = self.object.id
        return self.initial

    def form_valid(self, form):
        # Access the updated form instance
        updated_data = form.cleaned_data
        funded = self.object.get_pattr('Funds', normalize_date(self.object.end))
        value = self.object.get_eattr('Value', normalize_date(self.object.end))

        if value != 0:
            if updated_data['accounts']:
                Transaction.objects.create(user=self.request.user, real_date=self.object.end, price=0, quantity=0, value=value - funded,
                                           xa_action=Transaction.TRANS_OUT, account=self.object.account)
                Transaction.objects.create(user=self.request.user, real_date=updated_data['_end'], price=0, quantity=0, value=funded,
                                           xa_action=Transaction.TRANS_IN, account=updated_data['accounts'])
            else:
                Transaction.objects.create(user=self.request.user, real_date=self.object.end, price=0, quantity=0, value=funded,
                                       xa_action=Transaction.REDEEM, account=self.object)
        return super().form_valid(form)


class PortfolioEdit(PortfolioView, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


class TransactionEdit(LoginRequiredMixin, UpdateView):
    model = Transaction
    template_name = 'stocks/add_transaction.html'
    form_class = TransactionEditForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_success_url(self):
        try:
            url = self.request.POST["success_url"]
        except AttributeError:
            url = reverse('account_details', kwargs={'pk': self.object.account.id})
        return url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        context['account'] = context['object'].account
        context['success_url'] = self.request.META.get('HTTP_REFERER', '/')
        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if request.method == 'POST':
            if self.object and self.object.equity:
                for account_id in Transaction.objects.filter(equity=self.object.equity).values_list('account', flat=True).distinct():
                    Account.objects.get(id=account_id).reset()
        return response


class AccountEdit(LoginRequiredMixin, UpdateView, DateMixin):
    model = Account
    template_name = 'stocks/add_account.html'
    date_filed = 'end'
    form_class = AccountForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse('stocks_main')

    def get_initial(self):
        original = Account.objects.get(pk=self.kwargs['pk'])
        return {'name': original.name,
                'currency': original.currency,
                'managed': original.managed,
                'account_type': original.account_type,
                'user': original.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


@login_required
def account_update(request, pk):
    #profile = Profile.objects.get(user=request.user)
    #if not profile.av_api_key:
    #    return HttpResponse(status=404)

    account = get_object_or_404(Account, pk=pk, user=request.user)
    account.update()
    return HttpResponse(status=200)


@login_required
def upload_file(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            bin_file = form.cleaned_data['csv_file'].read()
            try:
                text_file = bin_file.decode('utf-8')
                reader = csv.reader(text_file.splitlines())
                try:
                    if form.cleaned_data["csv_type"] == 'QuestTrade':
                        importer = QuestTrade(form.cleaned_data['new_account_currency'], reader, request.user)
                    elif form.cleaned_data["csv_type"] == 'Manulife':
                        importer = Manulife(form.cleaned_data['new_account_currency'], reader, request.user)
                    elif form.cleaned_data["csv_type"] == 'Wealth':
                        importer = ManulifeWealth(form.cleaned_data['new_account_currency'], reader, request.user)
                    else:  # Must be generic
                        importer = StockImporter(form.cleaned_data['new_account_currency'], reader, request.user, HEADERS, managed=False)
                    importer.process()
                    for account in Account.objects.filter(user=request.user):
                        account.reset()  # Maybe overkill but how often do we import files
                    if len(importer.warnings) != 0:
                        return render(request, "stocks/uploadfile.html",
                                      {"form": form, 'custom_warnings': importer.warnings})
                except DIYImportException as e:
                    return render(request, "stocks/uploadfile.html", {"form": form, 'custom_error': str(e)})
            except UnicodeDecodeError:
                return render(request, "stocks/uploadfile.html", {"form": form, 'custom_error': 'File is invalid.'})
    else:
        form = UploadFileForm()
    return render(request, "stocks/uploadfile.html", {"form": form})


@login_required
def export_stocks_download(request):
    """
    Export equity / transaction data for the logged-in user.
    The format is suitable for reloading into the application using the 'default' format.
    """

    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="stock_exported.csv"'},
    )
    writer = csv.writer(response)
    writer.writerow(['Date', 'AccountName', 'AccountKey', 'Symbol', 'Region', 'Description', 'XAType', 'Currency', 'Quantity', 'Price', 'Amount'])

    accounts = Account.objects.filter(user=request.user)
    equities = []
    for account in accounts:
        for t in account.transactions:
            if t.equity:
                currency = t.equity.currency
                symbol = t.equity.symbol
                region = t.equity.region
                description = t.equity.name
                if t.equity not in equities:
                    equities.append(t.equity)
            else:
                currency = t.account.currency
                symbol = None
                description = None
                region = None

            writer.writerow([t.real_date.strftime('%Y-%m-%d'),
                             t.account.name, t.account.account_name, symbol, region, description, t.action_str, currency, t.quantity, t.price, t.value])

        # todo: Figure out the currency, this is a root problem for the e_pd as well
        # for element in account.e_pd.loc[account.e_pd['Dividends'] != 0].to_records():
        #    this_date = to_datetime(element[1]).strftime('%Y-%m-%d %H:%M:%S %p')
        #    symbol = element[2]
        #    amount = element[6] / element[3]
        #    writer.writerow([this_date,  t.account.name, t.account.account_name, symbol, None, 'DIV_VALUE', None, None, None, amount])

    # for v in EquityValue.objects.filter(equity__in=equities):
    #    writer.writerow([v.real_date.strftime('%Y-%m-%d %H:%M:%S %p'), None, None, v.equity.key, None, 'EQ_VALUE', v.equity.currency, None, v.price, None])
    return response


@login_required
def export_stocks(request):
    """
    Export equity / transaction data for the logged-in user.
    The format is suitable for reloading into the application using the 'default' format.
    """
    return render(request, "stocks/export.html", {
            'transactions': Transaction.objects.filter(user=request.user).count(),
            'equities': Transaction.objects.filter(user=request.user, equity__isnull=False).values_list('equity').distinct().count(),
            'funds': Transaction.objects.filter(user=request.user, equity__isnull=True).count()
            })


@login_required
def add_account(request):
    if request.method == "POST":
        form = AccountAddForm(request.POST, initial={'user': request.user})
        if form.is_valid():
            account_type = form.cleaned_data['account_type']
            Account(user=request.user,
                              account_name=form.cleaned_data['account_name'],
                              name=form.cleaned_data['name'],
                              account_type=account_type,
                              currency=form.cleaned_data['currency'],
                              managed=form.cleaned_data['managed']).save()
            account = Account.objects.get(user=request.user, account_name=form.cleaned_data['account_name'])
            if account.account_type == 'Cash':
                Equity.objects.create(symbol=account.f_key, currency=account.currency, name=account.f_key, equity_type='Cash')
            elif account.account_type == 'Value':
                Equity.objects.create(symbol=account.f_key, currency=account.currency, name=account.f_key, equity_type='Value')
            return HttpResponseRedirect(reverse('stocks_main'))

    form = AccountAddForm(initial={'user': request.user, 'currency': request.user.profile.currency, 'managed': False})
    return render(request, 'stocks/add_account.html', {'form': form})


@login_required
def add_transaction(request, account_id):
    account = get_object_or_404(Account, id=account_id, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user, 'account': account })
        if form.is_valid():
            equity = form.cleaned_data['equity'] if 'equity' in form.cleaned_data else None
            transaction = Transaction(user=request.user,
                                      real_date=form.cleaned_data['real_date'],
                                      price=form.cleaned_data['price'],
                                      quantity=form.cleaned_data['quantity'],
                                      value=form.cleaned_data['value'],
                                      xa_action=form.cleaned_data['xa_action'],
                                      account=account,
                                      equity=equity,
                                      )
            transaction.save()
            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                equity = transaction.equity.id if transaction.equity else None
                form = TransactionForm(initial={'user': request.user,
                                                'account': account,
                                                'equity': equity,
                                                'real_date': transaction.real_date,
                                                'xa_action': transaction.xa_action})

            else:
                account.reset()
                if 'success_url' in form.cleaned_data:
                    return HttpResponseRedirect(form.cleaned_data['success_url'])
                else:
                    return HttpResponseRedirect(reverse('stocks_main', kwargs={}))
    else:  # Initial get
        form = TransactionForm(initial={'user': request.user,
                                        'account': account,
                                        'real_date': datetime.now().date()})

    context = {
        'success_url': request.META.get('HTTP_REFERER', '/'),
        'form': form,
        'account': account,
        'view_verb': 'Add',

    }
    response = render(request, 'stocks/add_transaction.html', context)
    return response


def set_transaction(request, account_id, action):
    account = get_object_or_404(Account, id=account_id, user=request.user)
    if action == 'balance':
        xa_action = Transaction.BALANCE
    elif action == 'fund':
        xa_action = Transaction.FUND
    elif action == 'withdraw':
        xa_action = Transaction.REDEEM
    elif action == 'value':
        xa_action = Transaction.VALUE
    else:
        raise Http404('Action %s is not supported' % action)

    initial = {'user': request.user, 'xa_action': xa_action, 'account': account}

    if request.method == 'POST':
        form = TransactionSetValueForm(request.POST, initial=initial)
        if form.is_valid():
            valid = True
            value = form.cleaned_data['value']
            real_date = form.cleaned_data['real_date']
            if (account.account_type in ['Cash'] and xa_action == Transaction.BALANCE) or \
                    (account.account_type == 'Value' and xa_action == Transaction.VALUE):
                result = account.set_value(value, real_date, increment=False)
                if not result:
                    form.add_error(None, str(result))
                    valid = False
            elif xa_action in [Transaction.FUND, Transaction.REDEEM] and account.account_type != 'Cash':
                logger.debug('Fund/Redeem request for account:%s' % account)
                Transaction(user=request.user, account=account, xa_action=xa_action, real_date=form.cleaned_data['real_date'],
                            value=form.cleaned_data['value'], price=0, quantity=0).save()
                if 'number' in form.cleaned_data and form.cleaned_data['number']:
                    this_date = form.cleaned_data['real_date']
                    for _ in range(form.cleaned_data['number']):
                        this_date = this_date + relativedelta(months=1)
                        Transaction(user=request.user, account=account, xa_action=xa_action, real_date=this_date,
                                    value=form.cleaned_data['value'], price=0, quantity=0).save()
                if account.account_type == 'Value':
                    value = value * -1 if xa_action == Transaction.REDEEM else value
                    logger.debug('Update Values base on :%s' % value)
                    result = account.set_value(value, real_date, increment=True)
                    if not result:
                        form.add_error(None, str(result))
                        valid = False
            else:
                raise Http404('Action %s is not supported for account type' % (action, account.account_type))
            if valid:
                account.reset()
                if 'success_url' in form.cleaned_data:
                    return HttpResponseRedirect(form.cleaned_data['success_url'])
                else:
                    return HttpResponseRedirect(reverse('stocks_main'))
        else:
            pass
    else:
        form = TransactionSetValueForm(initial=initial)
    return render(request, 'stocks/add_transaction.html', {
        'success_url': request.META.get('HTTP_REFERER', '/'),
        'form': form,
        'view_verb': 'Quick',
        'account': account,
        'action_locked': True})


@login_required
def account_equity_date_update(request, p_pk, e_pk, date_str):
    """

    """
    account = get_object_or_404(Account, pk=p_pk, user=request.user)
    equity = get_object_or_404(Equity, pk=e_pk)
    this_date = datetime.strptime(date_str, '%Y-%m-%d 00:00:00').date()
    shares = round(account.get_eattr('Shares', this_date, symbol=equity.symbol), 2)
    value = round(account.get_eattr('Value', this_date, symbol=equity.symbol), 2)
    price = round(EquityValue.lookup_price(equity, this_date), 2)

    if request.method == 'POST':
        form = ManualUpdateEquityForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['shares'] or form.cleaned_data['shares'] == 0:
                quantity = form.cleaned_data['shares'] - shares
                action = Transaction.BUY if quantity > 0 else Transaction.SELL
                Transaction.objects.create(account=account, equity=equity, xa_action=action, real_date=this_date, quantity=quantity, estimated=True)
                account.reset()

            if form.cleaned_data['price'] and form.cleaned_data['price'] != price:
                ev = EquityValue.objects.get(equity=equity, date=this_date)
                ev.price = form.cleaned_data['price']
                ev.source = DataSource.USER.value
                ev.save()
                for account in Account.objects.filter(id__in=Transaction.objects.filter(equity=equity).values_list('account', flat=True).distinct()):
                    account.reset()
            return HttpResponseRedirect(reverse('account_table', kwargs={'pk': account.id}))
        else:
            pass
    else:
        form = ManualUpdateEquityForm(initial={'account': account.id, 'equity': equity.id, 'report_date': this_date, 'shares': shares, 'value': value, 'price': price})
    return render(request, 'stocks/account_equity_date_update.html', context={'form': form, 'account': account, 'equity': equity})


@login_required
def account_update(request, pk):
    account = get_object_or_404(Account, pk=pk, user=request.user)

    profile = Profile.objects.get(user=request.user)
    key = profile.av_api_key if profile.av_api_key else None
    for equity in account.equities.filter(searchable=True):
        equity.yp_update(daily=False)
    return HttpResponse(status=200)


@login_required
def portfolio_update(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    profile = Profile.objects.get(user=request.user)
    key = profile.av_api_key if profile.av_api_key else None
    for equity in portfolio.equities.filter(searchable=True):
        equity.update(key=key, daily=False)
    return HttpResponse(status=200)


@login_required
def equity_update(request,  id):
    """

    :param request:
    :param pk:
    :param key:
    :return:
    """

    equity = get_object_or_404(Equity, id=id)
    equity.update(daily=False)
    for account in Account.objects.filter(id__in=Transaction.objects.filter(equity=equity).values_list('account', flat=True).distinct()):
        account.reset()
    return HttpResponse(status=200)




@login_required
def reconcile_value(request, pk):
    """
    Does not seem to be a standard way to do this,  so I will need to use a non-generic View
    """
    def set_initial() -> List[Dict]:
        """
        Build the list of dictionaries for the forms based on existing data
        """
        first_value = FundValue.objects.filter(fund__symbol=account.f_key).earliest('date')
        if account.end:
            last_value = FundValue.objects.filter(fund__symbol=account.f_key, date__lte=account.end).latest('date')
        else:
            last_value = FundValue.objects.filter(fund__symbol=account.f_key).latest('date')

        funded = dict(account.transactions.filter(xa_action=Transaction.FUND).annotate(month=TruncMonth('date')).
                      values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))
        redeemed = dict(account.transactions.filter(xa_action=Transaction.REDEEM).annotate(month=TruncMonth('date')).
                        values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))

        result = []
        for redeemed_key in redeemed.keys():
            if redeemed_key > last_value.date:
                result.append({'date': redeemed_key, 'reported_date': redeemed_key, 'value': 0, 'source': None,
                               'deposited': 0, 'withdrawn': redeemed[redeemed_key]})

        for record in FundValue.objects.filter(fund__symbol=account.f_key, date__lte=last_value.date).order_by('-date'):
            this_funded = funded[record.date] if record.date in funded else 0
            this_redeemed = redeemed[record.date] if record.date in redeemed else 0
            result.append({'date': record.date, 'reported_date': record.real_date, 'value': int(record.value), 'source': DataSource(record.source).name,
                           'deposited': int(this_funded), 'withdrawn': int(this_redeemed)})

        for funded_key in funded.keys():
            if funded_key < first_value.date:
                result.append({'date': funded_key, 'reported_date': funded_key, 'value': 0, 'source': None,
                               'deposited': funded[funded_key], 'withdrawn': 0})
        return result

    account = get_object_or_404(Account, pk=pk, account_type='Value', user=request.user)
    if request.method == 'POST':
        initial = set_initial()
        formset = SimpleReconcileFormSet(request.POST)
        if formset.is_valid():
            as_dict = {d['date']: d for d in initial}
            for form in formset:
                if as_dict[form.cleaned_data['date']]['reported_date'] != form.cleaned_data['reported_date'] or \
                        as_dict[form.cleaned_data['date']]['value'] != form.cleaned_data['value']:
                    logger.debug('Change date or value detected %s:%s' % (form.cleaned_data['reported_date'], form.cleaned_data['value']))
                    try:
                        fund_value = FundValue.objects.get(fund__symbol=account.f_key, date=form.cleaned_data['date'])
                    except FundValue.DoesNotExist:
                        fund = Equity.objects.get(symbol=account.f_key)
                        fund_value = FundValue(fund=fund, date=form.cleaned_data['date'])
                    fund_value.value = form.cleaned_data['value']
                    fund_value.real_date = form.cleaned_data['reported_date']
                    fund_value.source = DataSource.USER.value
                    fund_value.save()

                if as_dict[form.cleaned_data['date']]['deposited'] != form.cleaned_data['deposited']:
                    diff = form.cleaned_data['deposited'] - as_dict[form.cleaned_data['date']]['deposited']
                    # Case 1 - original was 0,  just make a deposit record
                    # Case 2 - this was more,  make a new deposit record
                    # Case 3 - this was less, since negative can not pass the clean,  a record or records must exist
                    if diff > 0:
                        Transaction.objects.create(real_date=form.cleaned_data['reported_date'], xa_action=Transaction.FUND, account=account, value=diff, estimated=False)
                    else:
                        diff = abs(diff)
                        for transaction in Transaction.objects.filter(date=form.cleaned_data['date'], xa_action=Transaction.FUND, account=account):
                            if transaction.value >= diff:
                                transaction.value -= diff
                                transaction.estimated = False
                                transaction.save()
                                break
                            else:
                                diff -= transaction.value
                                transaction.value = 0
                                transaction.estimated = False
                                transaction.save()

                if as_dict[form.cleaned_data['date']]['withdrawn'] != form.cleaned_data['withdrawn']:
                    diff = form.cleaned_data['withdrawn'] - as_dict[form.cleaned_data['date']]['withdrawn']
                    # Case 1 - original was 0,  just make a deposit record
                    # Case 2 - this was more,  make a new deposit record
                    # Case 3 - this was less, since negative can not pass the clean,  a record or records must exist
                    if diff > 0:
                        Transaction.objects.create(real_date=form.cleaned_data['reported_date'], xa_action=Transaction.REDEEM, account=account, value=diff, estimated=False)
                    else:
                        diff = abs(diff)
                        for transaction in Transaction.objects.filter(date=form.cleaned_data['date'], xa_action=Transaction.REDEEM, account=account):
                            if transaction.value >= diff:
                                transaction.value -= diff
                                transaction.estimated = False
                                transaction.save()
                                break
                            else:
                                diff -= transaction.value
                                transaction.value = 0
                                transaction.estimated = False
                                transaction.save()
            account.reset()
        else:
            pass

    initial = set_initial()  # This is called twice on POST since I may have changed the data.
    formset = SimpleReconcileFormSet(initial=initial)
    return render(request, 'stocks/value_reconciliation.html',
                  {'formset': formset, 'account': account, 'xas': account.transactions.order_by('real_date')})


@login_required
def reconcile_cash(request, pk):
    """
    Does not seem to be a standard way to do this,  so I will need to use a non-generic View
    """
    def set_initial() -> List[Dict]:
        """
        Build the list of dictionaries for the forms based on existing data
        """
        result = []
        for record in FundValue.objects.filter(fund__symbol=account.f_key).order_by('-date'):
            result.append({'date': record.date, 'reported_date': record.real_date, 'value': int(record.value), 'source': DataSource(record.source).name})
        return result

    account = get_object_or_404(Account, pk=pk, account_type='Cash', user=request.user)
    if request.method == 'POST':
        initial = set_initial()
        formset = SimpleCashReconcileFormSet(request.POST)
        if formset.is_valid():
            as_dict = {d['date']: d for d in initial}
            for form in formset:
                if as_dict[form.cleaned_data['date']]['reported_date'] != form.cleaned_data['reported_date'] or \
                        as_dict[form.cleaned_data['date']]['value'] != form.cleaned_data['value']:
                    logger.debug('Change date or value detected %s:%s' % (form.cleaned_data['reported_date'], form.cleaned_data['value']))
                    try:
                        fund_value = FundValue.objects.get(fund__symbol=account.f_key, date=form.cleaned_data['date'])
                    except FundValue.DoesNotExist:
                        fund = Equity.objects.get(symbol=account.f_key)
                        fund_value = FundValue(fund=fund, date=form.cleaned_data['date'])
                    fund_value.value = form.cleaned_data['value']
                    fund_value.real_date = form.cleaned_data['reported_date']
                    fund_value.source = DataSource.USER.value
                    fund_value.save()
            account.reset()
        else:
            pass

    initial = set_initial()  # This is called twice on POST since I may have changed the data.
    formset = SimpleCashReconcileFormSet(initial=initial)
    return render(request, 'stocks/cash_reconciliation.html', {'formset': formset, 'account': account})


@login_required
def reconciliation(request, a_pk, date_str):
    '''
    Used for Investment Accounts
    '''

    account = get_object_or_404(Account, pk=a_pk, user=request.user)
    try:
        view_date = datetime.strptime(date_str, '%b-%Y').date()
        pd_date = pd.to_datetime(view_date)
    except ValueError:
        return render(request, '404.html',)

    account.e_pd['Date'] = account.e_pd['Date'].dt.strftime('%b-%Y')
    initial = account.e_pd.loc[account.e_pd['Date'] == pd_date][['Equity', 'Object_ID', 'Cost', 'Value', 'Shares', 'Dividends', 'TotalDividends', 'Price']].sort_values(by='Value', ascending=False).to_dict(orient='records')
    for record in initial:
        record['Cost'] = round(record['Cost'], 2)
        record['Value'] = round(record['Value'], 2)
        record['Shares'] = round(record['Shares'], 2)
        record['Price'] = round(record['Price'], 3)
        equity = Equity.objects.get(id=record['Object_ID'])
        record['Equity'] = equity
        record['Value'] = round(record['Value'], 2)
        record['equity_id'] = equity.id
        result = account.transactions.filter(equity=equity, date=view_date, xa_action__in=[Transaction.TRANS_IN, Transaction.BUY]).aggregate(Sum('value'), Avg('price'))
        record['Bought'] = result['value__sum']  # if result['value__sum'] else 0
        record['Bought_Price'] = result['price__avg']  # if result['price__avg'] else 0
        result = account.transactions.filter(equity=equity, date=view_date, xa_action=Transaction.REDIV).aggregate(Sum('value'), Avg('price'))
        record['Reinvested'] = result['value__sum']  # if result['value__sum'] else 0
        record['Reinvested_Price'] = result['price__avg']  # if result['price__avg'] else 0
        result = account.transactions.filter(equity=equity, date=view_date, xa_action__in=[Transaction.TRANS_OUT, Transaction.SELL]).aggregate(Sum('value'), Avg('price'))
        record['Sold'] = result['value__sum']  # if result['value__sum'] else 0
        record['Sold_Price'] = result['price__avg']  # if result['price__avg'] else 0

    formset_errors = None
    if request.method == 'POST':
        formset = ReconciliationFormSet(request.POST)
        if formset.is_valid():
            source = DataSource.RECONCILED.value
            for form in formset:
                equity = Equity.objects.get(id=form.cleaned_data['equity_id'])
                logger.debug('Processing equity %s' % equity)
                for entry in initial:  # See if this form changed
                    if entry['equity_id'] == equity.id:
                        if form.data_changed(entry, 'Shares'):
                            # Big assume,   this was a REDIV since they did not just make a transaction
                            orig = entry['Shares']
                            transaction = Transaction(equity=equity, account=account, user=request.user, date=view_date, price=0, value=0, esimated=True)
                            if entry['Shares'] > form.cleaned_data['Shares']:
                                transaction.quantity = entry['Shares'] - form.cleaned_data['Shares']
                                transaction.xa_action = Transaction.SELL
                            else:
                                transaction.quantity = form.cleaned_data['Shares'] - entry['Shares']
                                transaction.xa_action = Transaction.BUY
                            transaction.save()
                        if form.data_changed(entry, 'Price'):
                            try:
                                ev = EquityValue.objects.get(date=view_date, equity=equity)
                            except EquityValue.DoesNotExist:
                                ev = EquityValue(date=view_date, source=DataSource.ESTIMATE.value)
                            if ev.source > DataSource.RECONCILED.value:
                                ev.source = DataSource.RECONCILED.value
                                ev.price = form.cleaned_data['Price']
                                ev.save()
                                equity_new_estimates.delay(equity.id)  # Update the estimated recrods.
                        if form.data_changed(entry, 'Dividends'):
                            try:
                                event = EquityEvent.objects.get(date=view_date, event_type='Dividend', equity=equity)
                            except EquityEvent.DoesNotExist:
                                event = EquityEvent(date=view_date, event_type='Dividend', source=DataSource.ESTIMATE.value)
                            if event.source > DataSource.RECONCILED.value:
                                event.source = DataSource.RECONCILED.value
                                event.value = form.cleaned_data['Dividends']
                                event.save()
            account.reset()
            return HttpResponseRedirect(reverse('account_table', kwargs={'pk': account.id}))

        else:
            formset_errors = formset.errors
    else:
        formset = ReconciliationFormSet(initial=initial)
    return render(request, 'stocks/data_list.html', {'formset': formset, 'errors': formset_errors,
                                                     'account': account, 'date_str': date_str,
                                                     'xas': account.transactions.filter(date=view_date),
                                                     'success_url': request.META.get('HTTP_REFERER', '/')})


@login_required
def account_fund_details(request, container_type, pk, obj_type, id):
    """

    :param request:
    :param container_type:
    :param pk:
    :param symbol:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    if container_type in ['Account']:
        account = get_object_or_404(Account, pk=pk, user=request.user)
    else:
        account = get_object_or_404(Portfolio, pk=pk, user=request.user)


    equity = get_object_or_404(Equity, id=id)
    key = equity.key

    compare_to = None
    total_dividends = 0
    data = []
    new_df = account.e_pd.sort_values(by='Date').loc[account.e_pd['Equity'] == key]
    new_df.sort_values(by='Date', ascending=False, inplace=True, kind='quicksort')
    for element in new_df.to_records():
        extra_data = ''
        this_date = pd.Timestamp(element['Date'])
        if this_date in account.trade_dates(equity):
            quantity, price = account.trade_details(equity, this_date)
            if quantity < 0:
                extra_data = f'Sold {quantity} shares at ${price}'
            else:
                if price == 0:
                    extra_data = f'Received {quantity} shares (DRIP or Split)'
                else:
                    extra_data = f'Bought {quantity} shares at ${price}'

        if element['Shares'] == 0:
            total_dividends = equity_growth = 0
        else:
            total_dividends = element['TotalDividends']
            equity_growth = element['Value'] - element['Cost'] + total_dividends

        data.append({'date': this_date,
                     'shares': element['Shares'],
                     'value': element['Value'],
                     'cost': element['Cost'],
                     'loss': element['Cost'] - element['Value'] > 0,
                     'total_dividends': total_dividends,
                     'price': element['Price'],
                     'avgcost': element['AvgCost']})

    funded = account.transactions.filter(equity=equity, xa_action__in=(Transaction.BUY, Transaction.SELL)).aggregate(Sum('value'))['value__sum']
    profit = False
    if funded < 0:
        profit = True
        funded = funded * -1

    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data,
                   'account_type': container_type,
                   'account': account,
                   'equity': equity,
                   'funded': funded,
                   'profit': profit,
                   'dividends': total_dividends,

                   'xas': account.transactions.filter(equity=equity).order_by('-date'),
                   'compare_to': compare_to
                   })


@login_required
def account_equity_details(request, container_type, pk, id):
    """

    :param request:
    :param container_type:
    :param pk:
    :param symbol:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    if container_type in ['Account']:
        container = get_object_or_404(Account, pk=pk, user=request.user)
    else:
        container = get_object_or_404(Portfolio, pk=pk, user=request.user)

    equity = get_object_or_404(Equity, id=id)
    df = container.equity_dataframe(equity)
    df.sort_values(by='Date', ascending=False, inplace=True)
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%b')

    xas = container.transactions.filter(equity=equity).order_by('-date')

    return render(request, 'stocks/account_equity_detail.html',
                  {'data': json.loads(df.to_json(orient='records')),
                   'account_type': container_type,
                   'container': container,
                   'equity': equity,
                   'xas': xas,
                   })


@login_required
def add_equity(request):

    if request.method == 'POST':
        form = AddEquityForm(request.POST)
        if form.is_valid():
            subject = f"New Equity Request {form.cleaned_data['symbol']}"
            body = 'Requestor:%s\nSymbol:%s\nDescription:%s\nRegion:%s\nType:%s' % (
                request.user,
                form.cleaned_data['symbol'], form.cleaned_data['description'],
                form.cleaned_data['region'], form.cleaned_data['equity_type'])

            email_message = EmailMessage(subject, body, request.user.email, [os.environ['DIY_EMAIL_USER']])
            email_message.send()

            Equity.objects.create(symbol=form.cleaned_data['symbol'], region=form.cleaned_data['region'],
                                  name=form.cleaned_data['description'], equity_type=form.cleaned_data['equity_type'],
                                  searchable=False, validated=True)

            return HttpResponseRedirect(reverse('stocks_main'))

    else:  # Initial get
        form = AddEquityForm()

    context = {
        'success_url': request.META.get('HTTP_REFERER', '/'),
        'form': form,
    }
    return render(request, 'stocks/add_equity.html', context)

