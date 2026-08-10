# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)
# todo: I need to get the users timezone and use that for certain display purposes and maybe even day calculations,  after 8PM seems to be tomorrow since I am UTC

import csv
import logging
import os
import json
import time

import numpy as np
import pandas as pd

from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pandas import DataFrame, Timestamp
from typing import List, Dict

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMessage
from django.db.models import Sum, Avg, CharField
from django.db.models import Value as ORMValue
from django.db.models.functions import TruncMonth
from django.forms import formset_factory
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404, Http404, redirect
from django.urls import reverse
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView, View, FormView, TemplateView
from django.views.generic.dates import DateMixin


from base.utils import adjust_date
from base.ioom_dates import IOOMDates, IOOM_RANGES
from base.models import Profile
from base.views import BaseDeleteView

from .mixins import ContextMixinBase, ModalBaseMixin, TransactionMixin, WealthRangeMixin, WealthSummaryMixin
from .dataframes import WealthDF
from .models import Account, Dividend, Portfolio, Position, Investment, Value, Transaction, BaseContainer, Funding, CashFlow, DataSource, ValueBalance, clear_caches

#from .tasks import equity_new_estimates
from .forms import ModalBase, TransactionForm, ModalBaseForm, SimpleReconcileFormSet, PortfolioForm, AccountCloseForm, TransactionEditForm, AccountEditForm, UploadFileForm, AccountForm, TransactionSetValueForm, ManualUpdateEquityForm, AddEquityForm, ReconciliationFormSet
from .importers import BaseImporter
logger = logging.getLogger(__name__)

def debug_import(request):
    from wealth.importers import import_from_diy
    try:
        user=User.objects.get(username='fadmin')
    except User.DoesNotExist:
        user=User.objects.create(username='fadmin')
        user.set_password('kkk')
        user.is_staff=True
        user.is_superuser=True
        user.save()

    #Investment.objects.all().delete()
    #Account.objects.all().delete()
    #time.sleep(5)
    import_from_diy()
    user = User.objects.get(username='sparky')
    user.set_password('kkk')
    user.is_staff = True
    user.is_superuser = True
    user.save()

    return HttpResponse(status=404)

def debug(request):
    #from wealth.models import clear_caches
    #clear_caches()
    #Dividend.update_cash()
    #account=Account.objects.all()[0]
    #user = AppUser.objects.get(username='sparky')
    #dfo = WealthDF(user=user, scope='month')
    #df = dfo.df
    #pass
    #Position.objects.all().delete()
    #CashFlow.objects.all().delete()
    #Funding.objects.all().delete()
    #Funding.deposit(this_date=datetime.today(), account=account, amount=17)
    #Funding.deposit(this_date=datetime.today(), account=account, amount=18)
    #Funding.withdraw(this_date=datetime.today(), account=account, amount=19)
    #f = Funding.objects.get(value=17)
    #f.delete()
    #dfo = WealthDF(AppUser.objects.get(username='sparky'), 'month')
    #new_df = dfo.calc_inflation(dfo.df, column='Funding')
    #pass
    #dfo.build_positions_df()
    #dfo.build_positions_df_v2()
    #df = dfo.df
    # df = Portfolio.objects.all()[2].as_dataframe(scope='minute')
    # Investment.objects.get(symbol='TSLA').limited_update()
    # Investment.in_day_update()

    from wealth.importers import BaseImporter
    #BaseImporter.set_importer('/home/scott/Downloads/NewML.FullFromApr2023.csv', AppUser.objects.get(username='sparky')).process()
    #BaseImporter.set_importer('/home/scott/Downloads/QT_gail.xlsx', AppUser.objects.get(username='sparky')).process()
    #
    # hisBaseImporter.set_importer('/home/scott/Downloads/QT_scott.xlsx', AppUser.objects.get(username='sparky')).process()
    account = Account.objects.get(id=16)
    vb = ValueBalance.objects.filter(account=account, investment=account.value_investment)[6]
    vb.save(rebuild=True)
    return HttpResponse(status=404)


def get_stale_investments(df) -> list[str]:
    """
    Based on a data frame,  set a well formatted error message that will be displayed on the view page.
    - This is not the fastest, but it should be the exception that it is not updated.

    """
    if df.empty:
        return []

    stale = set(df['Symbol'].unique()) & set(list(Investment.stale().values_list('symbol', flat=True)))
    result = []
    if stale:
        for symbol in stale:
            last_updated = Investment.objects.get(symbol=symbol).last_updated
            last_updated = str(last_updated) if last_updated else 'Never'
            result.append(f'Stale investment detected: {symbol} last updated: {last_updated}')
    return result


class AccountAddView(ModalBaseMixin, LoginRequiredMixin, CreateView):
    model = Account
    template_name = 'base/basic_modal_form_table.html'
    form_class = AccountForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Create'
        context['view_noun'] = 'Account'
        context['help_file'] = 'stocks/help/account.html'
        return context

    def get_initial(self):
        initial = self.get_modal_data(super().get_initial())
        initial['user'] = self.request.user.id
        return initial

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


class AccountCloseView(LoginRequiredMixin, ModalBaseMixin, UpdateView):
    model = Account
    template_name = 'base/basic_modal_form_table.html'
    form_class = AccountCloseForm

    def valid_accounts(self):
        accounts = Account.objects.filter(user=self.request.user, acct_type=self.object.acct_type, closed__isnull=True).exclude(id=self.object.id)
        if self.object.portfolio:
            accounts = accounts.filter(portfolio=self.object.portfolio)
        return accounts

    def get_queryset(self):
        return Account.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['hide_new_xa'] = True
        context['table_title'] = f'{self.object.account_name} (Last 5)'
        context['help_file'] = 'stocks/help/account_close.html'

        return context

    def get_initial(self):
        initial = super().get_initial()
        initial['accounts'] = self.valid_accounts()
        initial['user'] = self.request.user.id
        initial['closed'] = self.object.last_date
        return initial

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)  # This will close the account, so we need to specify re_close=True
        if request.method == 'POST':  # Post is completed
            close_to = None
            if 'accounts' in request.POST and request.POST['accounts']:
                close_to = Account.objects.get(id=request.POST['accounts'])
            self.object.close(self.object.closed, re_close=True)
        return response


class AccountDateReconcileView(ModalBaseMixin, LoginRequiredMixin, WealthRangeMixin, ContextMixinBase, View):
    template_name = "wealth/reconciliation.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.account = get_object_or_404(Account, pk=kwargs['pk'])
        try:
            self.view_date = datetime.strptime(self.kwargs['date_str'], '%Y-%m-%d').date()
        except ValueError:
            raise Http404('Invalid request')

        self.dfo = WealthDF(user=request.user, date_range=self.wealth_range)
        self.formset_errors = 'Reconciliation for this date requires a range of less then 1 Year' if self.dfo.scope == 'month' and self.view_date > IOOMDates.max_day_scope() else None


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['account'] = self.account
        context['form'] = ModalBaseForm(initial=self.get_modal_data())
        context['help_file'] = 'stocks/help/account_close.html'
        return context



    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        context["formset"] = self.get_formset()
        return render(request, self.template_name, context)

    def get_formset(self, data=None):
        df = self.dfo.on_datetime(self.dfo.df, self.view_date)[['Symbol', 'Quantity', 'Price', 'DivValue', 'InvType', 'AccountID', 'Estimated']]
        df = df.loc[(df['InvType'] == 'Trading') & (df['AccountID'] == self.account.pk) & (df['Quantity'] != 0)].sort_values('Symbol')
        initial = df.to_dict(orient='records')

        if data:
            return ReconciliationFormSet(data, initial=initial)
        return ReconciliationFormSet(initial=initial)


    def post(self, request, *args, **kwargs):
        context = self.get_context_data()
        formset = self.get_formset(data=request.POST)
        baseform = ModalBase(request.POST)
        if formset.is_valid() and baseform.is_valid():
            source = DataSource.RECONCILED.value
            updated_quantity = updated_price = False
            for form in formset.forms:
                if form.has_changed():
                    for field in form.changed_data:
                        if field in ['Quantity', 'Price', 'DivValue']:  # fix up None vs 0
                            form.cleaned_data[field] = 0 if not form.cleaned_data[field] else form.cleaned_data[field]
                            form.initial[field] = 0 if not form.initial[field] else form.initial[field]

                    investment = Investment.objects.get(symbol=form.initial['Symbol'])
                    price = form.initial['Price'] if not investment.searchable else form.cleaned_data['Price']
                    if price != form.initial['Price']:
                        updated_price = True
                        Value.objects.update_or_create(date=self.view_date, investment=investment, scope=self.dfo.scope, defaults={'source': source, 'value': price})

                    if 'Quantity' in form.changed_data and form.cleaned_data['Quantity'] != form.initial['Quantity']:
                        updated_quantity = True
                        diff = form.cleaned_data['Quantity'] - form.initial['Quantity']
                        if diff < 0:
                            Transaction.sell(self.account, Investment.objects.get(symbol=form.initial['Symbol']), abs(diff), price, self.view_date,
                                             note=f'Reconciled on {datetime.now().date()}', source=source, rebuild=False)
                        elif diff > 0:
                            Transaction.buy(self.account, Investment.objects.get(symbol=form.initial['Symbol']), abs(diff), price, self.view_date,
                                            note=f'Reconciled on {datetime.now().date()}', source=source, rebuild=False)

                    if 'DivValue' in form.changed_data and form.cleaned_data['DivValue'] != form.initial['DivValue']:
                        Dividend.objects.update_or_create(date=self.view_date, investment=investment, day_scope=(self.dfo.scope == 'day'),
                                                          defaults={'source': source, 'value': form.cleaned_data['DivValue']})

            if updated_price or updated_quantity:
                self.account.rebuild(values=updated_price, positions=updated_quantity)
                clear_caches(user=request.user)

            if 'success_url' in baseform.cleaned_data:
                return JsonResponse({"ok": True, "redirect": baseform.cleaned_data['success_url']})
            else:
                return JsonResponse({"ok": True, "redirect": reverse('wealth_main', kwargs={})})
        else:
            formset_errors = formset.errors
        return render(request, self.template_name, context)


class AccountDeleteView(LoginRequiredMixin, DeleteView):
    model = Account
    template_name = 'base/basic_confirm_delete.html'
    success_url = 'wealth_home'

    def get_queryset(self):
        return Account.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = self.model.__name__
        context['success_url'] = self.request.build_absolute_uri(reverse('wealth_home'))
        context['extra_text'] = 'Deleting an account is permanent - All actions (Funding/Trading/Cash) will be removed.'
        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if request.method == 'POST': # Post is completed
            clear_caches(request.user)
            return JsonResponse({
                "ok": True,
                "redirect": self.get_success_url()
            })

        return response

    def get_success_url(self):
        return self.request.build_absolute_uri(reverse(self.success_url))


class AccountDetailView(LoginRequiredMixin, TransactionMixin, WealthSummaryMixin, DetailView):
    model = Account
    template_name = 'wealth/detail_view.html'

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_type'] = 'Chart'
        context['help_file'] = 'stocks/help/container_detail.html'

        dfo = WealthDF(self.request.user, date_range=context['range'])
        df = dfo.by_range(context['range'])
        if not df.empty:
            df = df.loc[df['AccountID'] == self.object.id]
            df = dfo.set_names(df)  # Add in the Account/Portfolio

        context['filter_summary'] = dfo.container_summary_by_date(df)

        context['container'] = self.object
        context['can_update'] = True  # Used in rules

        summary = dfo.investment_summary_by_date_df(df)
        context['investment_summary_data'] = json.loads(summary.to_json(orient='records'))
        context['object_type'] = self.object.__class__.__name__
        # context['xa_list'] = self.object.transactions.filter(date__gte=IOOMDates(build=False).range_start(context['range'])).order_by('-date', '-quantity', 'investment', 'quantity')
        context['stale_warning'] = get_stale_investments(df)

        return context


class AccountEdit(LoginRequiredMixin, ModalBaseMixin, UpdateView, DateMixin):
    model = Account
    template_name = 'base/basic_modal_form_table.html'
    form_class = AccountEditForm

    def get_initial(self):
        initial = self.get_modal_data(super().get_initial())
        initial['user'] = self.request.user.id
        return initial

    def get_queryset(self):
        return Account.objects.filter(user=self.request.user)

    def form_valid(self, form):
        form.save()
        clear_caches(self.request.user)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        context['view_noun'] = 'Account'
        context['help_file'] = 'stocks/help/add_account.html'
        return context


class AccountReconcileView(LoginRequiredMixin, WealthSummaryMixin, ContextMixinBase, View):
    template_name = "wealth/reconciliation_table.html"

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self):

        context = super().get_context_data(**self.kwargs)
        self.dfo = WealthDF(self.request.user, date_range=context['range'])  # Build and cache the proper scoped dataframe based on range
        context['full_summary'] = self.dfo.container_summary_by_date(self.dfo.df)
        try:
            context['last_updated'] = Investment.objects.filter(account__in=Account.objects.filter(user=self.request.user)).latest('last_updated').last_updated
        except Investment.DoesNotExist:
            context['last_updated'] = None
        context['view_type'] = 'Data'
        context['container'] = self.object
        return context

    def get(self, request, *args, **kwargs):
        self.object = Account.objects.get(pk=self.kwargs['pk'], user=self.request.user)
        context = self.get_context_data()
        context['account'] = self.object
        context["formset"] = self.get_formset()
        return render(request, self.template_name, context)

    def get_formset(self, data=None):
        initial = self.get_initial_data()
        if data:
            return SimpleReconcileFormSet(data, account=self.object, initial=initial)

        return SimpleReconcileFormSet(account=self.object, initial=initial)

    def get_initial_data(self):
        wealth_range = self.request.session['wealth_range'] if 'wealth_range' in self.request.session else 'year'
        dfo = WealthDF(self.request.user, date_range=wealth_range)
        df = dfo.df
        if not df.empty:
            df = df.loc[df.AccountID == self.object.pk]
        summary = dfo.container_values_by_date_df(df)
        return summary.to_dict(orient='records')

    def post(self, request, *args, **kwargs):
        self.object = Account.objects.get(pk=self.kwargs['pk'], user=self.request.user)
        context = self.get_context_data()
        context['account'] = self.object
        formset = self.get_formset(data=request.POST)

        if formset.is_valid():
            updated = False
            for form in formset.forms:
                if form.has_changed():
                    for field in form.changed_data:
                        if field in ['Cash', 'Total', 'Funding']:  # fix up None vs 0
                            form.cleaned_data[field] = 0 if not form.cleaned_data[field] else form.cleaned_data[field]
                            form.initial[field] = 0 if not form.initial[field] else form.initial[field]

                    if 'Cash' in form.changed_data and form.cleaned_data['Cash'] != form.initial['Cash']:
                        CashFlow.set_balance(form.initial['Date'], amount=form.cleaned_data['Cash'], account=self.object)
                        updated = True
                    if 'Funding' in form.changed_data and form.cleaned_data['Funding'] != form.initial['Funding']:
                        Funding.set_balance(form.initial['Date'], amount=form.cleaned_data['Funding'], account=self.object)
                        updated = True
                    if 'Value' in form.changed_data and self.object.acct_type == 'Value' and form.cleaned_data['Value'] != form.initial['Value']:
                        ValueBalance.set_balance(form.initial['Date'], amount=form.cleaned_data['Value'], account=self.object)
                        updated = True
            if updated:
                self.object.rebuild()
                clear_caches(request.user)
            formset = self.get_formset()  # Build a new formset with the updated data as initial,  else the original with post, data including errors is used

        context["formset"] = formset
        return render(request, self.template_name, context)


class PortfolioAdd(LoginRequiredMixin, ModalBaseMixin, CreateView):

    model = Portfolio
    template_name = 'base/basic_modal_form_table.html'
    form_class = PortfolioForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Create'
        context['view_noun'] = 'Portfolio'
        context['help_file'] = 'stocks/help/portfolio.html'
        return context

    def get_initial(self):
        initial = self.get_modal_data(super().get_initial())
        initial['user'] = self.request.user.id
        return initial

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


class PortfolioDeleteView(LoginRequiredMixin, DeleteView):
    model = Portfolio
    template_name = 'base/basic_confirm_delete.html'
    success_url = 'wealth_home'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if request.method == 'POST':  # Post is completed
            clear_caches(request.user)
            return JsonResponse({
                "ok": True,
                "redirect": self.get_success_url()
            })

        return response

    def get_success_url(self):
        return self.request.build_absolute_uri(reverse(self.success_url))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = self.model.__name__
        context['success_url'] = self.request.build_absolute_uri(reverse('wealth_home'))
        context['extra_text'] = 'Deleting a Portfolio is permanent, however the underlying data is not altered.'
        return context


class PortfolioDetailView(LoginRequiredMixin, WealthSummaryMixin, DetailView):
    model = Portfolio
    template_name = 'wealth/detail_view.html'

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        """
        context = super().get_context_data(**kwargs)

        context['view_type'] = 'Chart'
        context['help_file'] = './help/container_detail.html'

        dfo = WealthDF(self.request.user, date_range=context['range'])
        df = dfo.by_range(context['range'])
        df = df.loc[df['PortfolioID'] == self.object.id]
        df = dfo.set_names(df)  # Add in the Account/Portfolio

        context['filter_summary'] = dfo.container_summary_by_date(df)
        context['container'] = self.object
        context['can_update'] = False  # Used in rules

        summary = dfo.summary_list_by_date(df)
        context['container_list_data'] = sorted(summary, key=lambda x: x['Value'], reverse=True)
        context['object_type'] = self.object.__class__.__name__
        context['stale_warning'] = get_stale_investments(df)

        return context


class PortfolioEdit(LoginRequiredMixin, ModalBaseMixin, UpdateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['view_verb'] = 'Edit'
        context['cancel_url'] = self.request.META.get('HTTP_REFERER', '/')
        return context

    model = Account
    template_name = 'base/basic_modal_form_table.html'
    form_class = PortfolioForm

    def get_queryset(self):
        return Portfolio.objects.filter(user=self.request.user)

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        context['view_noun'] = 'Portfolio'
        context['help_file'] = 'stocks/help/add_account.html'
        return context


class PortfolioTableView(LoginRequiredMixin, WealthSummaryMixin, DetailView):
    model = Portfolio
    template_name = 'wealth/data_view.html'

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_type'] = 'Data'
        context['container'] = self.object

        dfo = WealthDF(self.request.user, date_range=context['range'])
        df = dfo.by_range(context['range'])
        df = df.loc[df['PortfolioID'] == self.object.id]

        context['filter_summary'] = dfo.container_summary_by_date(df)

        detail = dfo.container_values_by_date_df(df)
        fmt_str = "%b-%Y" if dfo.scope == 'month' else "%d-%b"
        detail['DateStr'] = detail['Date'].dt.strftime(fmt_str)
        context['container_list_data'] = json.loads(detail.to_json(orient='records'))

        return context

    def get_context_data_v1(self, **kwargs):
        """
        Add a list of all the equities in this account
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        """
        context['equities'] = context['account'].equities.order_by('symbol')

        summary_data = self.container_data(context['account'])
        if summary_data.empty:
            context['summary_data'] = None
            context['account_list'] = None
            context['view_type'] = 'Data'
            context['equity_count'] = 0
            context['can_reconcile'] = False
            context['object_type'] = 'Portfolio'
            context['xas'] = None
        else:
            summary_data['Date'] = summary_data['Date'].dt.strftime('%b-%Y')
            context['summary_data'] = json.loads(summary_data.to_json(orient='records'))
            context['account_list'] = context['account'].account_set.all().order_by('-_start')
            context['view_type'] = 'Data'
            context['equity_count'] = context['equities'].count()
            context['can_reconcile'] = False
            context['object_type'] = 'Portfolio'
            context['xas'] = context['account'].transactions.all().order_by('-real_date')
        """
        return context


class TransactionDeleteView(LoginRequiredMixin, ModalBaseMixin, DeleteView):
    model = Transaction
    template_name = 'base/basic_confirm_delete.html'
    form_class = ModalBase

    def get_object(self, queryset=None):
        return super().get_object(queryset=self.model.objects.filter(account__user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['extra_text'] = 'Deleting a Transaction is permanent'
        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if request.method == 'POST':  # Post is completed
            clear_caches(request.user)
        return response


class WealthDetailMain(LoginRequiredMixin, WealthSummaryMixin, ListView):
    model = Portfolio
    template_name = 'wealth/detail_view.html'

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['help_file'] = 'wealth/help/wealth_chart.html'
        context['view_type'] = 'Chart'

        dfo = WealthDF(self.request.user, date_range=context['range'])
        df = dfo.by_range(context['range'])
        summary = dfo.summary_list_by_date(df)
        context['container_list_data'] = sorted(summary, key=lambda x: x['Value'], reverse=True)
        # Add in new accounts - they will have no DF data, so they are missed.
        all_accounts = Account.objects.filter(user=self.request.user)
        if not df.empty:
            all_accounts = all_accounts.exclude(id__in=df['AccountID'].unique())
        for a in all_accounts:
            context['container_list_data'].append({'Value': 0, 'Cash': 0, 'EffectiveCost': 0, 'TotalDividends': 0, 'Id': a.pk, 'Name': a.name})
        context['stale_warning'] = get_stale_investments(df)
        return context


class WealthDataMain(LoginRequiredMixin, WealthSummaryMixin, ListView):
    model = Portfolio
    template_name = 'wealth/data_view.html'

    def get_object(self):
        return super().get_object(queryset=Account.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_type'] = 'Data'

        dfo = WealthDF(self.request.user, date_range=context['range'])
        df = dfo.by_range(context['range'])

        detail = dfo.container_values_by_date_df(df)
        if not detail.empty:
            fmt_str = "%b-%Y" if dfo.scope == 'month' else "%d-%b"
            detail['DateStr'] = detail['Date'].dt.strftime(fmt_str)
            context['container_list_data'] = json.loads(detail.to_json(orient='records'))
            context['stale_warning'] = get_stale_investments(df)

        return context



@login_required
def upload_file(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                my_importer = BaseImporter.set_importer(form.cleaned_data['transaction_file'], request.user)
            except ValueError as e:
                return JsonResponse({"ok": True, "errors": [(None, str(e))]})
            my_importer.process()
            clear_caches(request.user)
            if 'success_url' in form.cleaned_data:
                return JsonResponse({"ok": True, "redirect": form.cleaned_data['success_url']})
            else:
                return JsonResponse({"ok": True, "redirect": reverse('stocks_main', kwargs={})})
        else:
            return JsonResponse({"ok": True, "errors": form.errors})

    form = UploadFileForm(initial={'success_url': request.META.get('HTTP_REFERER', '/'), 'user': request.user})
    return render(request, "wealth/uploadfile.html", {"form": form})


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
                             t.account.name, t.account.account_name, symbol, region, description, t.action_str, currency, t.quantity, t.price, t.close_value])

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



def wealth_help(request):
    return render(request, 'stocks/includes/help.html', {'success_url': request.META.get('HTTP_REFERER', '/')})

@login_required
def add_transaction(request, account_id):
    """
    This is a bootstrap modal form.   POST must return JSON,  with redirect key for redirection
    """
    account = get_object_or_404(Account, id=account_id, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user, 'account': account})
        if form.is_valid():
            investment = form.cleaned_data['investment'] if 'investment' in form.cleaned_data else None
            action = form.cleaned_data['action']
            if action == 'FUND':
                Funding.deposit(this_date=form.cleaned_data['date'], account=form.cleaned_data['account'], amount=form.cleaned_data['value'])
            elif action == 'REDEEM':
                Funding.withdraw(this_date=form.cleaned_data['date'], account=form.cleaned_data['account'], amount=form.cleaned_data['value'])
            elif action == 'BUY':
                Transaction.buy(this_date=form.cleaned_data['date'], account=form.cleaned_data['account'],
                                price=form.cleaned_data['price'], quantity=form.cleaned_data['quantity'], investment=form.cleaned_data['investment'])
            elif action == 'SELL':
                Transaction.sell(this_date=form.cleaned_data['date'], account=form.cleaned_data['account'],
                                price=form.cleaned_data['price'], quantity=form.cleaned_data['quantity'], investment=form.cleaned_data['investment'])
            elif action == 'BALANCE' or action == 'VALUE':
                ValueBalance.set(account, value=form.cleaned_data['value'], this_date=form.cleaned_data['date'])

            elif action == 'TRANS_OUT':
                if investment:
                    account.transfer_equity(investment, form.cleaned_data['to_account'], form.cleaned_data['date'])
                else:
                    account.transfer_funding(form.cleaned_data['to_account'], form.cleaned_data['real_date'], amount=form.cleaned_data['value'])
            else:
                assert True, 'Action not support'

            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                return JsonResponse({"ok": True})
            else:
                account.rebuild()
                clear_caches(request.user)
                if 'success_url' in form.cleaned_data:
                    return JsonResponse({"ok": True, "redirect": form.cleaned_data['success_url']})
                else:
                    return JsonResponse({"ok": True, "redirect": reverse('stocks_main', kwargs={})})
        else:
            return JsonResponse({"ok": True, "errors": form.errors})


    form = TransactionForm(initial={'user': request.user,
                                    'account': account,
                                    'date': datetime.now().date(),
                                    'success_url': request.META.get('HTTP_REFERER', '/'),
                                    })

    return render(request, 'wealth/transaction.html', {
        'form': form,
        'account': account,
        'view_verb': 'Add',

    })


@login_required
def edit_transaction2(request, pk, rec_type):
    """
    This is a bootstrap modal form.   POST must return JSON,  with redirect key for redirection
    """

    quantity = price = value = None
    if rec_type == 'XA':
        transaction = get_object_or_404(Transaction, pk=pk, account__user=request.user)
        action = 'BUY' if transaction.quantity > 0 else 'SELL'
        investment = transaction.investment
        quantity=transaction.quantity
        price=transaction.price
    elif rec_type == 'FUND':
        transaction = get_object_or_404(Funding, pk=pk, account__user=request.user)
        action = 'FUND' if transaction.value > 0 else 'REDEEM'
        investment = None
        value = transaction.value

    elif rec_type == 'CASH':
        transaction = get_object_or_404(CashFlow, pk=pk, account__user=request.user)
        action = 'BALANCE'
        investment = None
        value = transaction.value

    elif rec_type == 'VALUE':
        transaction = get_object_or_404(ValueBalance, pk=pk, account__user=request.user)
        action = 'BALANCE'
        investment = None
        value = transaction.value

    initial = {'user': request.user, 'account': transaction.account, 'date': datetime.now().date(), 'investment': investment, 'action': action, 'quantity': quantity, 'price': price, 'value': value}
    if request.method == 'POST':
        form = TransactionEditForm(request.POST, initial=initial)
        if form.is_valid():
            clear_caches(request.user)
            if 'success_url' in form.cleaned_data:
                return JsonResponse({"ok": True, "redirect": form.cleaned_data['success_url']})
            else:
                return JsonResponse({"ok": True, "redirect": reverse('stocks_main', kwargs={})})
        else:
            return JsonResponse({"ok": True, "errors": form.errors})
    else:
        form = TransactionEditForm(initial=initial)
    return render(request, 'wealth/transaction.html', {
        'success_url': request.META.get('HTTP_REFERER', '/'),
        'transaction': transaction,
        'form': form,
        'view_verb': 'Edit',
        'account': transaction.account,
        'action_locked': True})  # True means you can change the action just the values


def set_transaction(request, account_id, action):
    """
    This is a bootstrap modal form.   POST must return JSON,  with redirect key for redirection
    """
    """

    """
    account = get_object_or_404(Account, id=account_id, user=request.user)
    if ((action == 'BALANCE' and account.acct_type != 'Cash') or
            (action == 'VALUE' and account.acct_type != 'Value') or
            (action in ['REDEEM', 'FUND'] and account.acct_type not in ['Value', 'Trading'])):

        raise Http404('Action %s is not supported' % action)

    if request.method == 'POST':
        form = TransactionSetValueForm(request.POST)
        if form.is_valid():
            valid = True
            this_date = form.cleaned_data['date']
            value = form.cleaned_data['value'] if form.cleaned_data['value'] else 0
            number = form.cleaned_data['number'] if form.cleaned_data['number'] else 0
            if action == 'FUND':
                Funding.deposit(amount=abs(value), account=account, this_date=this_date)
                if form.cleaned_data['repeat'] == 'yes':
                    repmonth = this_date + relativedelta(months=1)
                    for _ in range(abs(number)):
                        Funding.deposit(amount=abs(value), account=account, this_date=repmonth)
                        repmonth = repmonth + relativedelta(months=1)

            elif action == 'REDEEM':
                Funding.withdraw(amount=abs(value), account=account, this_date=this_date)
                repmonth = this_date + relativedelta(months=1)
                for _ in range(abs(number)):
                    Funding.withdraw(amount=abs(value), account=account, this_date=repmonth)
                    repmonth = repmonth + relativedelta(months=1)

            elif action == 'BALANCE' or action == 'VALUE':
                ValueBalance.set(account, value, this_date)
            else:
                raise Http404('Action %s is not supported' % action)
            if valid:
                clear_caches(request.user)
                if 'success_url' in form.cleaned_data:
                    return JsonResponse({"ok": True, "redirect": form.cleaned_data['success_url']})
                else:
                    return JsonResponse({"ok": True, "redirect": reverse('stocks_main', kwargs={})})
            else:
                return JsonResponse({"ok": True, "errors": form.errors})
    else:
        initial = {'user': request.user, 'account': account, 'date': datetime.now().date(), 'action': action, 'success_url': request.META.get('HTTP_REFERER', '/')}
        form = TransactionSetValueForm(initial=initial)
    return render(request, 'wealth/transaction.html', {
        'form': form,
        'view_verb': 'Quick',
        'account': account,
        'action_locked': True})


@login_required
def portfolio_update(request, pk):
    """
    This is only called from the main wealth page,  so we may as well update the page too
    """
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)

    profile = Profile.objects.get(user=request.user)
    key = profile.av_api_key if profile.av_api_key else None

    for equity in Investment.objects.filter(
            searchable=True,
            id__in=Transaction.objects.filter(account__portfolio=portfolio, account___end__isnull=True, xa_action__in=Transaction.SHARE_TRANSACTIONS)):
        equity.update(key=key, daily=False)

    for account in portfolio.account_set.filter(_end__isnull=True):
        account.update_static_values()

    return HttpResponseRedirect(reverse('stocks_main'))


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

            Investment.objects.create(symbol=form.cleaned_data['symbol'], region=form.cleaned_data['region'],
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

