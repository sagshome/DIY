# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)

import csv
import logging
import os
import json

from datetime import datetime, date
from dateutil import relativedelta

import plotly.io as pio
import plotly.graph_objects as go

import pandas as pd
from pandas import DataFrame

from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet, Sum, Avg, Q
from django.core.mail import EmailMultiAlternatives, EmailMessage
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin
from django.http import JsonResponse


from .models import Equity, Account, Transaction, EquityEvent, EquityValue, Portfolio
from .forms import AccountAddForm, AccountForm, TransactionForm, AccountCopyForm, UploadFileForm, ManualUpdateEquityForm, EquityForm, AddEquityForm, PortfolioForm, AccountCloseForm
from .importers import QuestTrade, Manulife, ManulifeWealth, StockImporter, HEADERS
from base.utils import DIYImportException, normalize_today, normalize_date
from .tasks import daily_update
from base.models import Profile, COLORS

logger = logging.getLogger(__name__)


class AccountView(LoginRequiredMixin, ListView):
    model = Account
    template_name = 'stocks/portfolio_list.html'

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)

        try:
            profile = Profile.objects.get(user=self.request.user)
            context['can_update'] = True if profile.av_api_key else False
        except Profile.DoesNotExist:
            context['can_update'] = False
        context['portfolio_list'] = Portfolio.objects.filter(user=self.request.user)
        context['account_list'] = Account.objects.filter(user=self.request.user, portfolio__isnull=True)
        return context


class AccountDeleteView(LoginRequiredMixin, DeleteView):
    model = Account
    template_name = 'stocks/basic_confirm_delete.html'
    success_url = '/stocks/account/'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Account'
        context['extra_text'] = 'Deleting an account is permanent - All transaction will be removed..'
        context['cancel_url'] = reverse('portfolio_list', kwargs={})
        return context


class TransactionDeleteView(LoginRequiredMixin, DeleteView):
    model = Transaction
    template_name = 'stocks/basic_confirm_delete.html'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse_lazy('account_details', kwargs = {'pk': self.object.account.id})

    def get_context_data(self, **kwargs):
        this = self.get_object()
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Transaction'
        context['extra_text'] = 'Deleting a Transaction is permanent'
        context['cancel_url'] = reverse_lazy('account_details', kwargs = {'pk': this.account.id})
        return context


class AccountTableView(LoginRequiredMixin, DetailView):
    model = Account
    template_name = 'stocks/account_table.html'

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

        # Build the table data as [date, (shares, value), (shares, value)... total_value
        for this_date in a.e_pd.Date.unique():
            total_value = 0
            this_record = [this_date, 0]
            for equity in elist:
                try:
                    df = a.e_pd[(a.e_pd['Date'] == this_date) & (a.e_pd['Equity'] == equity.symbol)][['Shares', 'Value']]
                    if df.empty:
                        this_record.append((None, None, None))
                    else:
                        shares = df['Shares'].tolist()[0]
                        value = df['Value'].tolist()[0]
                        if shares == 0 or value == 0:
                            this_record.append((None, None, None))
                        else:
                            this_record.append((equity.id, shares, value))
                            total_value += value
                except KeyError:
                    this_record.append((None, None))
            if not total_value == 0:
                this_record[1] = total_value
                data.append(this_record)
        data.sort(reverse=True)
        return {'account': a,
                'data': data,
                'equities': elist,
                'equity_count': elist.count()
                }


class PortfolioTableView(LoginRequiredMixin, DetailView):
    model = Account
    template_name = 'stocks/account_table.html'

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
        data = list()
        elist = p.equities.order_by('symbol')

        # Build the table data as [date, (shares, value), (shares, value)... total_value
        for this_date in p.e_pd.Date.unique():
            total_value = 0
            this_record = [this_date, 0]
            for equity in elist:
                try:
                    df = p.e_pd[(p.e_pd['Date'] == this_date) & (p.e_pd['Equity'] == equity.symbol)][['Shares', 'Value']]
                    if df.empty:
                        this_record.append((None, None, None))
                    else:
                        shares = df['Shares'].tolist()[0]
                        value = df['Value'].tolist()[0]
                        if shares == 0 or value == 0:
                            this_record.append((None, None, None))
                        else:
                            this_record.append((equity.id, shares, value))
                            total_value += value
                except KeyError:
                    this_record.append((None, None))
            if not total_value == 0:
                this_record[1] = total_value
                data.append(this_record)
        data.sort(reverse=True)
        return {'account': p,
                'data': data,
                'equities': elist,
                'equity_count': elist.count()
                }


class PortfolioDetailView(LoginRequiredMixin, DetailView):
    model = Portfolio
    template_name = 'stocks/account_detail.html'

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
        return {'object': p,
                'object_type': 'Portfolio',
                'account_list': p.account_set.all(),
                'xas': p.transactions.order_by('-real_date', 'xa_action'),
                'funded': funded,
                'redeemed': redeemed,
                }


class AccountDetailView(LoginRequiredMixin, DetailView):
    model = Account
    template_name = 'stocks/account_detail.html'

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
        p: Account = context['account']

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
        return {'object': p,
                'object_type': 'Account',
                'children': None,
                'xas': p.transactions.order_by('-real_date', 'xa_action'),
                'can_update': can_update,
                'funded': funded,
                'redeemed': redeemed,
                }


def account_update(request, pk):
    """
    :param request:
    :param pk:
    :param key:
    :return:
    """
    profile = Profile.objects.get(user=request.user)
    if not profile.av_api_key:
        return HttpResponse(status=404)

    account = get_object_or_404(Account, pk=pk, user=request.user)
    account.update()
    return HttpResponse(status=200)


def diy_update(request):
    """
    :param request:
    :return:
    :return:
    """
    daily_update()
    return HttpResponseRedirect(reverse('portfolio_list'))


class PortfolioView(LoginRequiredMixin):
    model = Portfolio
    template_name = 'stocks/portfolio.html'
    form_class = PortfolioForm

    def get_success_url(self):
        return reverse('portfolio_list', kwargs={})

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
        return reverse('portfolio_list', kwargs={})

    def get_initial(self):
        super().get_initial()
        accounts = Account.objects.filter(user=self.request.user, end__isnull=True).exclude(id=self.object.id)
        if self.object.portfolio:
            accounts = accounts.filter(portfolio=self.portfolio)
        self.initial['accounts'] = accounts
        self.initial['user'] = self.request.user.id
        self.initial['_end'] = datetime.today().date()
        return self.initial

    def form_valid(self, form):
        # Access the updated form instance
        updated_data = form.cleaned_data
        funded = self.object.get_attr('Funds', self.object.end)
        value = self.objects.get_attr('Value', self.object.end)
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


class PortfolioDeleteView(LoginRequiredMixin, DeleteView):
    model = Portfolio
    template_name = 'stocks/basic_confirm_delete.html'
    success_url = '/stocks/account/'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'Portfolio'
        context['extra_text'] = 'Deleting a portfolio will NOT delete the accounts it contains,  you will need to delete them separately.'
        context['cancel_url'] = reverse('portfolio_list', kwargs={})
        return context


class AccountAdd(LoginRequiredMixin, CreateView):
    model = Account
    template_name = 'stocks/add_account.html'
    form_class = AccountAddForm

    def get_success_url(self):
        return reverse('account_details', kwargs={'pk': self.object.id})

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial


class TransactionEdit(LoginRequiredMixin, UpdateView):
    model = Transaction
    #fields = ['real_date', 'xa_action', 'price', 'quantity', 'value']
    template_name = 'stocks/add_transaction.html'
    form_class = TransactionForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse('account_details', kwargs={'pk': self.object.account.id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


class AccountEdit(LoginRequiredMixin, UpdateView, DateMixin):
    model = Account
    # fields = ['name', 'currency', 'managed', 'end']
    template_name = 'stocks/add_account.html'
    date_filed = 'end'
    form_class = AccountForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse('portfolio_list')

    def get_initial(self):
        original = Account.objects.get(pk=self.kwargs['pk'])
        return {'name': original.name,
                'currency': original.currency,
                'managed': original.managed,
                'user': original.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


class AccountCopy(CreateView):
    model = Account
    template_name = 'stocks/add_account.html'
    form_class = AccountCopyForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))


    def get_initial(self):
        original = Account.objects.get(pk=self.kwargs['pk'])
        return {'name': f'{original.name}_copy',
                'user': original.user,
                'managed': original.managed,
                'currency': original.currency,
                'end': original.end}

    def form_valid(self, form):
        """

        :param form:
        :return:
        """
        result = super().form_valid(form)
        original = Account.objects.get(pk=self.kwargs['pk'])
        for t in Transaction.objects.filter(account=original):
            Transaction.objects.create(account=self.object, equity=t.equity, date=t.date,
                                       price=t.price, value=t.value,
                                       quantity=t.quantity, xa_action=t.xa_action)


        return result

    def get_success_url(self):
        return reverse('account_details', kwargs={'pk': self.object.id})


@login_required
def upload_file(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            bin_file = form.cleaned_data['csv_file'].read()
            text_file = bin_file.decode('utf-8')
            reader = csv.reader(text_file.splitlines())
            try:
                if form.cleaned_data["csv_type"] == 'QuestTrade':
                    importer = QuestTrade(reader, request.user)
                elif form.cleaned_data["csv_type"] == 'Manulife':
                    importer = Manulife(reader, request.user)
                elif form.cleaned_data["csv_type"] == 'Wealth':
                    importer = ManulifeWealth(reader, request.user)
                else:
                    importer = StockImporter(reader, request.user, HEADERS, managed=False)
                importer.process()
                if len(importer.warnings) != 0:
                    return render(request, "stocks/uploadfile.html",
                                  {"form": form, 'custom_warnings': importer.warnings})
            except DIYImportException as e:
                return render(request, "stocks/uploadfile.html", {"form": form, 'custom_error': str(e)})
            return HttpResponseRedirect(reverse('portfolio_list'))

    else:
        form = UploadFileForm()
    return render(request, "stocks/uploadfile.html", {"form": form})


@login_required
def edit_transaction(request, pk):
    xa: Transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user})
        if form.is_valid():
            action = form.cleaned_data['xa_action']
            if action == Transaction.FUND or Transaction.REDEEM:
                xa.date = form.cleaned_data['date']
                xa.price = 0
                xa.quantity = 0
                xa.value = form.cleaned_data['value']
                xa.xa_action = form.cleaned_data['xa_action']
                xa.account = form.cleaned_data['account']
            else:
                xa.date = form.cleaned_data['date']
                xa.price = form.cleaned_data['price']
                xa.quantity = form.cleaned_data['quantity']
                xa.value = 0
                xa.xa_action = form.cleaned_data['xa_action']
                xa.account = form.cleaned_data['account']
            xa.save()


@login_required
def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user})
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
                                                 account=form.cleaned_data['account'])

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
                                                 account=form.cleaned_data['account'])
            elif (action == Transaction.REDIV):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 account=form.cleaned_data['account'])
            elif (action == Transaction.FEES):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=Transaction.SELL,
                                                 account=form.cleaned_data['account'])

            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                equity = new.equity.id if new.equity else None
                form = TransactionForm(initial={'user': request.user,
                                                'account': new.account,
                                                'equity': equity,
                                                'real_date': new.real_date,
                                                'xa_action': new.xa_action})
            else:
                return HttpResponseRedirect(reverse('account_details', kwargs={'pk': new.account.id}))
    else:  # Initial get
        form = TransactionForm(initial={'user': request.user})

    context = {
        'form': form,
    }
    return render(request, 'stocks/add_transaction.html', context)


@login_required
def account_equity_date_update(request, p_pk, e_pk, date_str):
    """

    """
    account = get_object_or_404(Account, pk=p_pk, user=request.user)
    equity = get_object_or_404(Equity, pk=e_pk)
    this_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    if request.method == 'POST':
        form = ManualUpdateEquityForm(request.POST)
        if form.is_valid():
            price = form.cleaned_data['shares'] / form.cleaned_data['value'] if form.cleaned_data['value'] else 0
            if settings.ALPHAVANTAGEAPI_KEY:
                equity.update(key=settings.ALPHAVANTAGEAPI_KEY)
            return HttpResponseRedirect(reverse('account_table', kwargs={'pk': account.id}))
        else:
            pass
    else:
        shares = 0
        value = 0
        df = account.e_pd[(account.e_pd['Date'] == this_date) & (account.e_pd['Equity'] == equity.symbol)][['Shares', 'Value']]
        if not df.empty:
            shares = df['Shares'].tolist()[0]
            value = df['Value'].tolist()[0]
        form = ManualUpdateEquityForm(initial={'account': account.id, 'equity': equity.id, 'report_date': this_date, 'shares': shares, 'value': value})
    return render(request, 'stocks/portfolio_update_equity.html', context={'form': form, 'account': account, 'equity': equity})


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
        next_date = next_date + relativedelta.relativedelta(months=1)

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
def account_equity_details(request, container_type, pk, symbol):
    """

    :param request:
    :param container_type:
    :param pk:
    :param symbol:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    if container_type == 'Account':
        account = get_object_or_404(Account, pk=pk, user=request.user)
    else:
        account = get_object_or_404(Portfolio, pk=pk, user=request.user)

    equity = get_object_or_404(Equity, symbol=symbol)
    compare_to = None
    if request.method == 'POST':
        form = EquityForm(request.POST)
        if form.is_valid():
            compare_to = form.cleaned_data['equity']

    form = EquityForm()
    data = []
    new_df = account.e_pd.sort_values(by='Date').loc[account.e_pd['Equity'] == equity.symbol]
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
                   'form': form,
                   'xas': account.transactions.filter(equity=equity).order_by('-date'),
                   'compare_to': compare_to
                   })


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

            return HttpResponseRedirect(reverse('portfolio_list'))

    else:  # Initial get
        form = AddEquityForm()

    context = {
        'form': form,
    }
    return render(request, 'stocks/add_equity.html', context)


def overlay_dates(dataframe: DataFrame, key: str, symbol: str, list_of_dates):
    result = []
    for this_date in list_of_dates:
        value = dataframe.loc[(dataframe['Equity'] == symbol) & (dataframe['Date'] == this_date)][key]
        if len(value) != 1:
            result.append(0)
        else:
            result.append(value.item())
    return result


@login_required
def get_equity_list(request):
    """
    API to get the proper set of equities base on the action, profile and date.
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

    values = Equity.objects.exclude(deactived_date__gt=this_date)

    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES]:
        try:
            account = Account.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
            this_date = normalize_date(this_date)
            subset = account.e_pd.loc[account.e_pd['Date'] == this_date]['Equity']
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
        next_date = next_date + relativedelta.relativedelta(months=1)

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
            JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    else:
        try:
            my_object = Account.objects.get(id=object_id, user=request.user)
        except Account.DoesNotExist:
            JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if equity_id:
        try:
            equity = Equity.objects.get(id=equity_id)
        except Equity.DoesNotExist:
            JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        if not my_object:
            JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        df = my_object.e_pd.loc[(my_object.e_pd['Equity'] == equity.symbol) & (my_object.e_pd['Shares'] != 0)]

    else:
        df = my_object.p_pd
        de = my_object.e_pd.groupby('Date', as_index=False).sum('Value')
        df = df.merge(de, on='Date', how='outer')
        df['Cost'] = df['Funds']
        if my_object.end:
            df = df.loc[df['Date'] <= my_object.end]
        df.fillna(0, inplace=True)

    df['Date'] = df['Date'].dt.date
    # pd.Timestamp(df['Date'])
    chart_data['labels'] = sorted(df['Date'].unique())
    chart_data['datasets'].append({'label': 'Funding', 'fill': False, 'data': df['Cost'].tolist(), 'borderColor': colors[2], 'backgroundColor': colors[2], 'tension': 0.1})
    chart_data['datasets'].append({'label': 'Value', 'fill': False,'data': df['Value'].tolist(),'borderColor': colors[1], 'backgroundColor': colors[1]})
    #if not equity_id:
    #    chart_data['datasets'].append({'label': 'Cash', 'fill': False, 'data': df['Cash'].tolist(), 'borderColor': colors[2], 'backgroundColor': colors[2]})

    return JsonResponse(chart_data)
