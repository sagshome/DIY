# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)
import asyncio
import csv
import logging
import os
import json

from datetime import datetime, date

import plotly.io as pio
import plotly.graph_objects as go

import numpy as np
import pandas as pd

from typing import List, Dict
from dateutil.relativedelta import relativedelta

from pandas import DataFrame, to_datetime

from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet, Sum, Avg, Q
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear

from django.core.mail import EmailMultiAlternatives, EmailMessage
from django.forms import modelformset_factory

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, Http404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin
from django.http import JsonResponse

from .models import Equity, Account, DataSource, Transaction, EquityEvent, EquityValue, Portfolio, BaseContainer, FundValue, ACCOUNT_COL
from .forms import *
from .importers import QuestTrade, Manulife, ManulifeWealth, StockImporter, HEADERS
from base.utils import DIYImportException, normalize_today, normalize_date, DateUtil
from .tasks import daily_update
from base.models import Profile, COLORS, PALETTE


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


class PortfolioDataView(LoginRequiredMixin, DetailView):
    model = Portfolio
    template_name = 'stocks/portfolio_data.html'

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p: Portfolio = context['portfolio']

        accounts = {}
        all_dates = pd.DataFrame(columns=['Date'])
        all_accounts = p.account_set.all().order_by('-_start')
        for account in all_accounts:
            logger.debug('Processing account:%s' % account)
            funded = list(account.transactions.filter(xa_action=Transaction.FUND).annotate(month=TruncMonth('date')). \
                          values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))
            redeemed = list(account.transactions.filter(xa_action=Transaction.REDEEM).annotate(month=TruncMonth('date')). \
                            values('month').annotate(sum=Sum('value')).values_list('month', 'sum'))
            funded = pd.DataFrame(funded,  columns=['Date', 'Funded'])
            redeemed = pd.DataFrame(redeemed,  columns=['Date', 'Withdrawn'])
            funded['Date'] = pd.to_datetime(funded['Date'])
            redeemed['Date'] = pd.to_datetime(redeemed['Date'])
            try:
                df = account.e_pd.groupby('Date', as_index=False).sum('Value')[['Date', 'Value']]
                try:
                    df = df.merge(funded, on='Date', how='outer')
                    df = df.merge(redeemed, on='Date', how='outer')

                    df = df.replace(np.nan, 0)
                    df = df.infer_objects(copy=False)

                    df['Date'] = df['Date'].dt.date
                    all_dates = all_dates.merge(df['Date'], on='Date', how='outer')
                    # df = df[(df['Value'] != 0) & (df['Funded'] != 0) & (df['Withdrawn'] != 0)]
                    accounts[account] = df
                except ValueError:
                    logger.error('Merge Error Portfolio:%s Account:%s' % (p, account))
            except KeyError:
                logger.error('Group Error Portfolio:%s Account:%s' % (p, account))
        process_dates = all_dates['Date'].to_list()
        process_dates.sort(reverse=True)
        rows = {}
        for this_date in process_dates:
            rows[this_date] = []
            for account in accounts:
                matched = accounts[account].loc[accounts[account]['Date'] == this_date]
                if matched.empty:
                    rows[this_date].extend([None, None, None, None])
                else:
                    value = matched['Value'].item()
                    funded = matched['Funded'].item()
                    withdrawn = matched['Withdrawn'].item()
                    if value == 0 and funded == 0 and withdrawn == 0:
                        rows[this_date].extend([None, None, None, None])
                    else:
                        if account.account_type == 'Investment':
                            rows[this_date].extend([value, funded, withdrawn, account.id])
                        else:
                            rows[this_date].extend([value, funded, withdrawn, None])

        context['accounts'] = all_accounts
        context['data'] = rows
        return context


class AccountView(LoginRequiredMixin, ListView):
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
            equity_data = pd.merge(equity_data, myobj.p_pd)

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
        data = list()
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

    template_name = 'stocks/account_detail.html'

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
        return reverse('stocks_main', kwargs={})

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
        if self.object.account_type == 'Value':
            value = self.object.get_pattr('Redeemed', normalize_date(self.object.end))
        else:
            value = self.object.get_eattr('Value', normalize_date(self.object.end))

        if value != 0:
            if updated_data['accounts']:
                Transaction.objects.create(user=self.request.user, real_date=self.object.end, price=0, quantity=0, value=value - funded,
                                           xa_action=Transaction.TRANS_OUT, account=self.object.account)
                Transaction.objects.create(user=self.request.user, real_date=updated_data['_end'], price=0, quantity=0, value=funded,
                                           xa_action=Transaction.TRANS_IN, account=updated_data['accounts'])
            else:
                Transaction.objects.create(user=self.request.user, real_date=self.object.end, price=0, quantity=0, value=funded,
                                       xa_action=Transaction.REDEEM, account=self.object.account)
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
            action = form.cleaned_data['xa_action']
            if action in [Transaction.FUND, Transaction.REDEEM, Transaction.TRANS_IN, Transaction.TRANS_OUT]:
                value = form.cleaned_data['value']
                if (action in [Transaction.FUND, Transaction.TRANS_IN] and value < 0) or (action in [Transaction.REDEEM, Transaction.TRANS_OUT] and value > 0):
                    value = value * -1
                new = Transaction.objects.create(user=request.user,
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=0,
                                                 value=value,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 account=account)

            elif (action == Transaction.BUY) or (action == Transaction.SELL):
                quantity = form.cleaned_data['quantity']
                if (action == Transaction.BUY and quantity < 0) or (action == Transaction.SELL and quantity > 0):
                    quantity = quantity * -1

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=form.cleaned_data['price'],
                                                 quantity=quantity,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 account=account)
            elif (action == Transaction.REDIV):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 account=account)
            elif (action == Transaction.FEES):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=Transaction.SELL,
                                                 account=account)

            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                equity = new.equity.id if new.equity else None
                form = TransactionForm(initial={'user': request.user,
                                                'account': account,
                                                'equity': equity,
                                                'real_date': new.real_date,
                                                'xa_action': new.xa_action})
            else:
                account.reset()
                return HttpResponseRedirect(form.cleaned_data['success_url'])
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
    return render(request, 'stocks/add_transaction.html', context)


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
                return HttpResponseRedirect(form.cleaned_data['success_url'])
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
def account_compare(request, pk, symbol):
    account: Account = get_object_or_404(Account, pk=pk, user=request.user)
    compare_equity: Equity = get_object_or_404(Equity, symbol=symbol)
    compare_to: DataFrame = account.switch(compare_equity)

    x = sorted(account.e_pd['Date'].unique())
    new = account.e_pd[['Date', 'EffectiveCost', 'InflatedCost', 'Value', 'TotalDividends']].groupby('Date').sum()
    comp = compare_to[['Date', 'Value',  'InflatedCost', 'TotalDividends']].groupby('Date').sum()
    total = new['Value']
    dividends = new['TotalDividends']
    inflation = new['InflatedCost']
    cost = new['EffectiveCost']
    compt = comp['Value']
    compd = comp['TotalDividends']

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=dividends, mode='lines', name='Total Dividends'))
    fig.add_trace(go.Scatter(x=x, y=total, mode='lines', name='Present Value'))
    fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Effective Cost'))
    fig.add_trace(go.Scatter(x=x, y=inflation, mode='lines', name='Inflation'))
    fig.add_trace(go.Scatter(x=x, y=compd, mode='lines', name=f'Dividends if...{compare_equity}'))
    fig.add_trace(go.Scatter(x=x, y=compt, mode='lines', name=f'Present Value if...{compare_equity}'))
    fig.update_layout(title='Return vs Cost', xaxis_title='Month', yaxis_title='Dollars')
    chart_html = pio.to_html(fig, full_html=False)
    return render(request, 'stocks/portfolio_compare.html',
                  {'account': account, 'compare_to': compare_equity, 'chart': chart_html})


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
        equity.yp_update(daily=False)
    return HttpResponse(status=200)


@login_required
def equity_update(request,  key):
    """

    :param request:
    :param pk:
    :param key:
    :return:
    """
    profile = Profile.objects.get(user=request.user)
    if not profile.av_api_key:
        return HttpResponse(status=404)

    equity = get_object_or_404(Equity, symbol=key)
    equity.update(key=profile.av_api_key)
    for account in Account.objects.filter(id__in=Transaction.objects.filter(equity=equity).values_list('account', flat=True).distinct()):
        account.reset()
    return HttpResponse(status=200)


@login_required
def account_equity_compare(request, pk, orig_id, compare_id):
    try:
        account = Account.objects.get(id=pk, user=request.user)
        compare_to = Equity.objects.get(id=compare_id)
        equity = Equity.objects.get(id=orig_id)
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = account.transactions.filter(equity=equity) if equity else account.transactions
    xas = xas.order_by('date')  # just to be safe
    xa_list = list(xas.values_list('date', flat=True))

    first_date = xas.first().date
    last_date = normalize_today()

    ct_div_dict = compare_to.event_dict()
    e_div_dict = equity.event_dict()

    ct_value_dict = compare_to.value_dict()
    e_value_dict = equity.value_dict()

    months = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta(months=1)

    cost = ct_shares = e_shares = ct_div = e_div = 0
    cost_list = []
    ct_value_list = []
    ct_div_list = []
    e_value_list = []
    e_div_list = []

    for this_date in months:
        if this_date in xa_list:
            result = xas.filter(date=this_date).aggregate(Sum('quantity'), Avg('price'))
            amount = result['quantity__sum']
            price = result['price__avg']
            cost += amount * price
            e_shares += amount
            ct_shares += (amount * price) / ct_value_dict[this_date]
        cost_list.append(cost)
        if e_shares:
            if this_date in ct_value_dict:
                ct_value_list.append(ct_shares * ct_value_dict[this_date])
            if this_date in e_value_dict:
                e_value_list.append(e_shares * e_value_dict[this_date])
            if this_date in ct_div_dict:
                ct_div += ct_shares * ct_div_dict[this_date]
            ct_div_list.append(ct_div)
            if this_date in e_div_dict:
                e_div += e_shares * e_div_dict[this_date]
            e_div_list.append(e_div)

    colors = COLORS.copy()
    ci = 0
    chart_data = {'labels': sorted(months), 'datasets': []}
    chart_data['datasets'].append({'label': 'Cost', 'type': 'line', 'fill': False, 'data': cost_list, 'borderColor': colors[0],
                                   'backgroundColor': colors[0]})
    chart_data['datasets'].append({'label': f'{equity.symbol} Value', 'type': 'line', 'fill': False, 'data': e_value_list, 'borderColor': colors[1],
                                   'backgroundColor': colors[1]})
    chart_data['datasets'].append({'label': f'{equity.symbol} Dividends', 'type': 'line', 'fill': False, 'data': e_div_list, 'borderColor': colors[2],
                                   'backgroundColor': colors[2]})
    chart_data['datasets'].append({'label': f'{compare_to.symbol} Value', 'type': 'line', 'fill': False, 'data': ct_value_list, 'borderColor': colors[3],
                                   'backgroundColor': colors[3]})
    chart_data['datasets'].append({'label': f'{compare_to.symbol} Dividends', 'type': 'line', 'fill': False, 'data': ct_div_list, 'borderColor': colors[4],
                                   'backgroundColor': colors[4]})

    return JsonResponse(chart_data)


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

        for record in FundValue.objects.filter(fund__symbol=account.f_key).order_by('-date'):
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
    return render(request, 'stocks/value_reconciliation.html', {'formset': formset, 'account': account})

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
            for form in formset:
                equity = Equity.objects.get(id=form.cleaned_data['equity_id'])
                logger.debug('Processing equity %s' % equity)
                for entry in initial:  # See if this form changed
                    if entry['equity_id'] == equity.id:
                        if form.data_changed(entry, 'Bought', 'Bought_Price'):
                            pass
                        if form.data_changed(entry, 'Reinvested', 'Reinvested_Price'):
                            pass
                        if form.data_changed(entry, 'Sold', 'Sold_Price'):
                            pass
                        if form.data_changed(entry, 'Price'):
                            pass
                        if form.data_changed(entry, 'Dividends'):
                            pass
                        break
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
def account_equity_details(request, container_type, pk, obj_type, id):
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
    fund = None
    key = equity.key

    compare_to = None
    total_dividends = 0
    data = []
    new_df = account.e_pd.sort_values(by='Date').loc[account.e_pd['Equity'] == key]
    new_df.sort_values(by='Date', ascending=False, inplace=True, kind='quicksort')
    for element in new_df.to_records():
        extra_data = ''
        this_date = pd.Timestamp(element['Date'])
        if obj_type == 'Fund':
            quantity = price = 0
        else:
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
    if obj_type == 'Fund':
        funded = 0
    else:
        funded = account.transactions.filter(equity=equity, xa_action__in=(Transaction.BUY, Transaction.SELL)).aggregate(Sum('value'))['value__sum']

    profit = False
    if funded and funded < 0:
        profit = True
        funded = funded * -1


    xas = account.transactions.filter(equity=equity).order_by('-date')

    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data,
                   'account_type': container_type,
                   'object_type': obj_type,
                   'account': account,
                   'equity': equity,
                   'funded': funded,
                   'profit': profit,
                   'dividends': total_dividends,
                   'xas': xas,
                   'compare_to': compare_to
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


@login_required
def get_action_list(request):
    account_id = request.GET.get("account_id")
    if account_id:
        account = Account.objects.get(id=account_id, user=request.user)

    value_map = {value:key for key, value in Transaction.TRANSACTION_TYPE}
    result = {}
    if account.account_type == 'Investment':
        my_set = ('Deposit', 'Withdraw', 'Buy',  'Sell', 'Reinvested Dividend', 'Dividends/Interest')
    if account.account_type == 'Cash':
        my_set = ('Value',)
    if account.account_type == 'Value':
        my_set = ('Deposit', 'Withdraw', 'Buy', 'Sell', 'Value')
    for item in my_set:
        result[value_map[item]] = item
    return render(request, "generic_selection.html", {"values": result})


@login_required
def get_equity_list(request):
    """
    API to get the proper set of equities, the number of shares and the number base on the action, profile and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    """
    this_date = datetime.now()
    action = None

    if request.GET.get("date"):
        try:
            this_date = datetime.strptime(request.GET.get("date"), '%Y-%m-%d')
        except ValueError:
            logger.error("Received a ill formed date %s" % request.GET.get("date"))

    if request.GET.get("action"):
        try:
            action = int(request.GET.get('action'))
        except ValueError:
            logger.error("Received a non-numeric action %s" % request.GET.get("action"))

    values = Equity.objects.filter(equity_type='Equity').exclude(deactived_date__lt=this_date)

    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES]:
        try:
            account = Account.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
            this_date = np.datetime64(normalize_date(this_date))
            subset = account.e_pd.loc[(account.e_pd['Date'] == this_date) & (account.e_pd['Shares'] > 0)]['Equity']
            values = values.filter(symbol__in=subset.values)
        except Account.DoesNotExist:
            logger.error('Someone %s is poking around, looking for %s' * (request.user, request.GET.get("portfolio_id")))
            pass
        except ValueError:
            pass  # No value supplied

    value_dictionary = dict()
    for e in values.order_by('symbol'):
        value_dictionary[e.id] = e

    return render(request, "generic_selection.html", {"values": value_dictionary})


@login_required
def get_equity_values(request):
    """
    API to get the proper set of equities base on the action, profile and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    """
    this_date = datetime.now()
    action = None


    try:
        this_date = datetime.strptime(request.GET.get("date"), '%Y-%m-%d')
    except ValueError:
        logger.error("Received a ill formed date %s" % request.GET.get("date"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    except TypeError:
        logger.error("Received a ill formed date %s" % request.GET.get("date"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    try:
        action = int(request.GET.get('action'))
    except ValueError:
        logger.error("Received a non-numeric action %s" % request.GET.get("action"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    try:
        account = Account.objects.get(id=request.GET.get('account_id'), user=request.user)
    except Account.DoesNotExist:
        logger.error("Account with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    try:
        equity = Equity.objects.get(id=request.GET.get('equity_id'))
    except Equity.DoesNotExist:
        logger.error("Equity with ID %s is not found." % request.GET.get("equity_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    price = 0
    if equity.equity_type == 'Equity':
        try:
            price = EquityValue.objects.get(equity=equity, date=normalize_date(this_date)).price
        except:
            pass

    shares = 0
    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES]:
        this_date = np.datetime64(normalize_date(this_date))
        shares = account.e_pd.loc[(account.e_pd['Date'] == this_date) & (account.e_pd['Equity'] == equity.key)]['Shares'].item()

    return JsonResponse({'shares': shares, 'price': price})


@login_required
def compare_equity_chart(request):

    try:
        account = Account.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
        compare_to = Equity.objects.get(id=request.GET.get("compare_id"))
        equity = Equity.objects.get(id=request.GET.get("equity_id"))
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = account.transactions.filter(equity=equity) if equity else account.transactions
    xas = xas.order_by('date')  # just to be safe
    xa_list = list(xas.values_list('date', flat=True))

    first_date = xas.first().date
    last_date = normalize_today()

    ct_div_dict = dict(EquityEvent.objects.filter(equity=compare_to, event_type='Dividend', date__gte=first_date).values_list('date', 'value'))
    e_div_dict = dict(EquityEvent.objects.filter(equity=equity, event_type='Dividend', date__gte=first_date).values_list('date', 'value'))
    ct_value_dict = dict(EquityValue.objects.filter(equity=compare_to, date__gte=first_date).values_list('date', 'price'))
    e_value_dict = dict(EquityValue.objects.filter(equity=equity, date__gte=first_date).values_list('date', 'price'))

    months = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta(months=1)

    cost = ct_shares = e_shares = ct_div = e_div = 0
    cost_list = []
    ct_value_list = []
    ct_div_list = []
    e_value_list = []
    e_div_list = []

    for this_date in months:
        if this_date in xa_list:
            result = xas.filter(date=this_date).aggregate(Sum('quantity'), Avg('price'))
            amount = result['quantity__sum']
            price = result['price__avg']
            cost += amount * price
            e_shares += amount
            ct_shares += (amount * price) / ct_value_dict[this_date]
        cost_list.append(cost)
        ct_value_list.append(ct_shares * ct_value_dict[this_date])
        e_value_list.append(e_shares * e_value_dict[this_date])
        if this_date in ct_div_dict:
            ct_div += ct_shares * ct_div_dict[this_date]
        ct_div_list.append(ct_div)
        if this_date in e_div_dict:
            e_div += e_shares * e_div_dict[this_date]
        e_div_list.append(e_div)

    colors = COLORS.copy()
    ci = 0
    chart_data = {'labels': sorted(months), 'datasets': []}
    chart_data['datasets'].append({'label': 'Cost', 'type': 'line', 'fill': False, 'data': cost_list, 'borderColor': colors[0],
                                   'backgroundColor': colors[0]})
    chart_data['datasets'].append({'label': f'{{Equity}} Value', 'type': 'line', 'fill': False, 'data': e_value_list, 'borderColor': colors[1],
                                   'backgroundColor': colors[1]})
    chart_data['datasets'].append({'label': f'{{Equity}} Dividends', 'type': 'line', 'fill': False, 'data': e_div_list, 'borderColor': colors[2],
                                   'backgroundColor': colors[2]})
    chart_data['datasets'].append({'label': f'{{compare_to}} Value', 'type': 'line', 'fill': False, 'data': ct_value_list, 'borderColor': colors[3],
                                   'backgroundColor': colors[3]})
    chart_data['datasets'].append({'label': f'{{compare_to}} Dividends', 'type': 'line', 'fill': False, 'data': ct_div_list, 'borderColor': colors[4],
                                   'backgroundColor': colors[4]})

    return JsonResponse(chart_data)


@login_required
def cost_value_chart(request):
    """
    The cost value chart is displayed with accounts,  portfolio and equities (in an account)
    """

    colors = COLORS.copy()
    chart_data = {'labels': None,
                  'datasets': []}

    object_id = request.GET.get('object_id')
    object_type = request.GET.get("object_type")
    equity_id = request.GET.get("symbol")

    df = my_object = None
    if object_type == 'Portfolio':
        try:
            my_object = Portfolio.objects.get(id=object_id, user=request.user)
        except Portfolio.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    else:
        try:
            my_object = Account.objects.get(id=object_id, user=request.user)
        except Account.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if equity_id:
        try:
            equity = Equity.objects.get(id=equity_id)
        except Equity.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        if not my_object:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        df = my_object.e_pd.loc[(my_object.e_pd['Equity'] == equity.key) & (my_object.e_pd['Shares'] != 0)]
        try:
            df['adjusted_value'] = df['Value'] + df['TotalDividends']
        except ValueError:   # No data it would appear
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        label1 = 'Cost'

    else:  # Portfolio or Account
        df = my_object.p_pd
        de = my_object.e_pd.groupby('Date', as_index=False).sum('Value')
        if len(de) == 0:
            df['Value'] = df['Funds']
        else:
            try:
                df = df.merge(de, on='Date', how='outer')
            except ValueError:   # No data it would appear
                return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

        df['Cost'] = df['Funds'] - df['Redeemed']
        if my_object.end:
            df = df.loc[df['Date'] <= pd.to_datetime(my_object.end)]
        df.fillna(0, inplace=True)
        label1 = 'Funding'

    if df.empty:
        chart_data = {}
    else:
        df['Date'] = df['Date'].dt.date
        chart_data['labels'] = sorted(df['Date'].unique())
        chart_data['datasets'].append({'label': label1, 'fill': False, 'data': df['Cost'].tolist(), 'borderColor': colors[2], 'backgroundColor': colors[2], 'tension': 0.1})
        chart_data['datasets'].append({'label': 'Value', 'fill': False,'data': df['Value'].tolist(),'borderColor': colors[1], 'backgroundColor': colors[1]})
        if equity_id:
            chart_data['datasets'].append(
                {'label': 'Value w/ Dividends', 'fill': False, 'data': df['adjusted_value'].tolist(), 'borderColor': colors[3], 'backgroundColor': colors[3]})

    return JsonResponse(chart_data)


@login_required
def acc_summary(request):
    '''
    Three modes,  1) Portfolio,  2) Account,  3) Everything
    '''
    colors = COLORS.copy()
    ci = 0

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')

    if object_type:
        if object_type == 'Account':
            accounts = Account.objects.filter(user=user, id=object_id)
        else:
            accounts = Account.objects.filter(user=user, portfolio_id=object_id)
    else:
        accounts = Account.objects.filter(user=user)

    if accounts.exists():
        start = accounts.filter(_start__isnull=False).earliest('_start')._start.strftime('%Y-%m-%d')
        if accounts.filter(_end__isnull=True).exists():
            end = normalize_today().strftime('%Y-%m-%d')
        else:
            end = accounts.latest('_end')._end.strftime('%Y-%m-%d')
    else:
        return JsonResponse({'labels': [], 'datasets': []})

    if not object_type:  # This is a 'Everything' - so remove accounts with a portfolio
        accounts = accounts.exclude(portfolio__isnull=False)

    date_range = pd.date_range(start=start, end=end, freq='MS')
    month_df = pd.DataFrame({'Date': date_range, 'Value': 0})

    labels = [this_date.strftime('%Y-%b') for this_date in month_df['Date'].to_list()]
    df = pd.DataFrame(columns=ACCOUNT_COL)
    datasets = []
    for account in accounts:
        color = colors[ci]
        ci += 1
        datasets.append({
            'label': account.name,
            'fill': False,
            'data': pd.concat([month_df, account.e_pd.loc[:, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
            'boarderColor': color, 'backgroundColor': color,
            'stack': 1,
            'order': 1,
        })
        df = pd.concat([df, account.p_pd]).groupby('Date', as_index=False).sum()

    if not object_type:  # This is a 'Everything' - process portfolios a portfolio
        for portfolio in Portfolio.objects.filter(user=user):
            color = colors[ci]
            ci += 1

            datasets.append({
                'label': portfolio.name,
                'fill': False,
                'data': pd.concat([month_df,  portfolio.e_pd.loc[:, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
                'boarderColor': color,  'backgroundColor': color,
                'stack': 1,
                'order': 1,
            })
            df = pd.concat([df, portfolio.p_pd]).groupby('Date', as_index=False).sum()

    df['Cost'] = df['Funds'] - df['Redeemed']
    datasets.append({
        'label': 'Cost',
        'fill': False,
        'data': df['Cost'].to_list(),
        'boarderColor': '#000000', 'backgroundColor': '#000000',
        'type': 'line',
        'order': 0,
    })

    return JsonResponse({'labels': labels, 'datasets': datasets})


@login_required
def equity_summary(request):
    colors = COLORS.copy()
    ci = 0

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')

    if not (object_id and object_type):
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if object_type == 'Account':
        this = get_object_or_404(Account, id=object_id, user=request.user)
    else:
        this = get_object_or_404(Portfolio, id=object_id, user=request.user)

    start = this.start
    end = this.end if this.end else normalize_today()
    if not (start and end):
        return JsonResponse({'status': 'false', 'message': 'Invalid Data'}, status=500)

    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')

    date_range = pd.date_range(start=start, end=end, freq='MS')
    month_df = pd.DataFrame({'Date': date_range, 'Value': 0})

    labels = [this_date.strftime('%Y-%b') for this_date in month_df['Date'].to_list()]
    df = pd.DataFrame(columns=ACCOUNT_COL)
    datasets = []
    for equity in this.equities:
        color = colors[ci]
        ci += 1
        datasets.append({
            'label': equity.symbol,
            'fill': False,
            'data': pd.concat([month_df, this.e_pd.loc[this.e_pd['Object_ID'] == equity.id, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
            'boarderColor': color, 'backgroundColor': color,
            'stack': 1,
            'order': 1,
        })
        df = pd.concat([df, this.p_pd]).groupby('Date', as_index=False).sum()

    cost_df = this.p_pd['Funds'] - this.p_pd['Redeemed']

    datasets.append({
        'label': 'Cost',
        'fill': False,
        'data': cost_df.to_list(),
        'boarderColor': '#000000', 'backgroundColor': '#000000',
        'type': 'line',
        'order': 0,
    })

    return JsonResponse({'labels': labels, 'datasets': datasets})


@login_required
def wealth_summary_chart(request):
    """
    Build the chart data required for the timespan with the following data
    1.  Cost
    2.  CPI Cost
    3.  Value
    4.  Dividends
    5.  Comparison Value
    """

    user = request.user
    date_util = DateUtil(period=request.GET.get('period'), span=request.GET.get('span'))
    dates = date_util.dates({'cost': 0, 'cpi_cost': 0, 'value': 0, 'dividends': 0, 'comp_value': 0})

    accounts = Account.objects.filter(user=user)
    for account in accounts:
        logger.debug('Processing %s:%s' % (account.id, account))
        for key in dates.keys():
            logger.debug('Processing date %s' % key)
            this_cost = account.get_pattr('Funds', key) - account.get_pattr('Redeemed', key)
            this_value = account.get_eattr('Value', key)
            dates[key]['cost'] += this_cost
            dates[key]['value'] += this_value

    # Lets get the data back to lists
    labels = []
    cost = []
    value = []
    for key in dates.keys():
        labels.append(date_util.date_to_label(key))
        cost.append(dates[key]['cost'])
        value.append(dates[key]['value'])

    chart_data = {'labels': labels,
                  'datasets': [
                      {'label': 'Cost', 'fill': False, 'data': cost, 'boarderColor': PALETTE['coral'],  'backgroundColor': PALETTE['coral'], 'tension': 0.1},
                      {'label': 'Value', 'fill': False, 'data': value, 'boarderColor': PALETTE['olive'],  'backgroundColor': PALETTE['olive']}
                      ]
                  }

    return JsonResponse(chart_data)


@login_required
def wealth_summary_pie(request):
    '''
    A quick pie chart - launched at login time
    '''
    data = []
    labels = []
    option_links = []
    for account in Account.objects.filter(user=request.user, portfolio__isnull=True, _end__isnull=True):
        value = account.value if account.value and account.value > 0 else 0
        data.append(value)
        option_links.append(reverse('account_details', kwargs={'pk': account.id}))
        labels.append(account.name)
    for portfolio in Portfolio.objects.filter(user=request.user):
        value = portfolio.value if portfolio.value and portfolio.value > 0 else 0
        data.append(value)
        option_links.append(reverse('portfolio_details', kwargs={'pk': portfolio.id}))
        labels.append(portfolio.name)
    return JsonResponse({'data': data, 'labels': labels, 'options_links': option_links, 'colors': COLORS})
