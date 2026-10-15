import pandas as pd

from dataclasses import dataclass
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from typing import List, Union

from django.db.models import CharField, QuerySet, Q
from django.db.models import Value as ORMValue

from django.http import JsonResponse
from django.http import Http404

from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import View

from base.ioom_dates import IOOMDates, IOOM_RANGES
from .dataframes import WealthDF
from .forms import TransactionForm
from .models import Account, CashFlow, DividendAmount, Investment, Transaction, Funding, DataSource, ValueBalance


class ContextMixinBase:
    """
    This must be the last Mixin on the views
    Ensure the starting point of context
    Ensure required test variables are defined
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.explicit_date = None
        self.reconcile_view = False

        if 'explicit_date' in self.request.GET:
            date_parm = self.request.GET.get('explicit_date')
            formats = ['%Y-%b', '%b-%Y','%b-%y', '%b-%y']
            for this_format in formats:
                try:
                    self.explicit_date = datetime.strptime(date_parm, this_format)
                    break
                except ValueError:
                    pass
                
        if 'range' in self.request.GET:
            wealth_range = self.request.GET.get('range')
            if wealth_range in IOOM_RANGES:
                self.request.session['wealth_range'] = wealth_range
        self.wealth_range = self.request.session.get('wealth_range', 'year')


    def get_context_data(self, **kwargs):
        context = {}
        context["range"] = self.wealth_range
        context["range_string"] = IOOMDates.range_to_string(self.wealth_range)
        context['explicit_date'] = self.explicit_date
        return context


class ModalBaseMixin:
    """
    Process Modal Fields,   works with ModalBaseForm.
    """

    def get_initial(self):
        initial = super().get_initial()
        return self.get_modal_data(initial)

    def get_modal_data(self, initial: dict = None):
        """
        Set the initial success_url and is_modal values
        """
        if not initial:
            initial = {}

        initial.update({
            'success_url': self.request.META.get('HTTP_REFERER', self.request.build_absolute_uri(reverse('wealth_home', kwargs={}))),
            'is_modal': True,
        })
        return initial

    def form_valid(self, form):

        url = form.cleaned_data['success_url'] if 'success_url' in form.cleaned_data and form.cleaned_data['success_url'] else reverse('wealth_home')
        return JsonResponse({
            "ok": True,
            "redirect": url
        })

    def form_invalid(self, form):
        return JsonResponse({
            "ok": False,
            "errors": form.errors
        })


class TransactionMixin:
    """
    Combine various transaction like things into a xa_list
    - Consumed by wealth/includes/wealth_transaction_list.html
    """
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = {
            'date__gte': IOOMDates(build=False).range_start(context['range']),
            'account': self.object,
        }

        xas = list(Transaction.objects.annotate(rec_type=ORMValue('XA', CharField())).filter(**filters).values())
        funding = list(Funding.objects.annotate(rec_type=ORMValue('FUND', CharField())).filter(**filters).values())
        values = list(ValueBalance.objects.annotate(rec_type=ORMValue('VALUE', CharField())).filter(**filters).values())

        tr_dict = TransactionForm.TRANSACTION_DICT
        merged_list = []
        for rec in xas + funding + values:  # + cash:
            if 'source' in rec:
                rec['source'] = DataSource(rec['source']).label
            if 'rec_type' in rec:
                if rec['rec_type'] == 'XA':
                    if rec['quantity'] > 0:
                        rec['action_str'] = tr_dict['REDIV'] if rec['price'] == 0 else tr_dict['BUY']
                    else:
                        rec['action_str'] = tr_dict['SELL']
                    rec['value'] = rec['quantity'] * rec['price']
                else:
                    rec['investment_id'] = rec['investment_id'].split('~')[1]
                    if rec['rec_type'] == 'FUND':
                        rec['action_str'] = tr_dict['FUND'] if rec['value'] > 0 else tr_dict['REDEEM']
                    elif rec['rec_type'] in ['CASH', 'VALUE']:
                        rec['action_str'] = tr_dict['VALUE']
                    else:
                        rec['action_str'] = tr_dict[None]

            merged_list.append(rec)

        context['xa_list'] = sorted(merged_list, key=lambda x: x['date'], reverse=True)
        return context

@dataclass
class ReconciliationRow:
    """
    What to show on Reconcilation Detail Rows
    """
    date: date
    container_id: Union[int, None]
    container_name: Union[str, None]
    row_type: str
    value: Decimal
    investment: Union[str, None]
    note: Union[str, None]
    id: Union[str, None]
    class_type: object
    cash: Decimal

    def __init__(self, *args, **kwargs):
        self.date = kwargs['date'] if 'date' in kwargs else datetime.today().date()
        self.container_id = kwargs["container_id"] if "container_id" in kwargs else None
        self.container_name = kwargs["container_name"] if "container_name" in kwargs else None
        self.row_type = kwargs["row_type"] if "row_type" in kwargs else 'Other'
        self.value = kwargs["value"] if "value" in kwargs else Decimal(0)
        investment: str = kwargs["investment"] if "investment" in kwargs else ''
        self.investment = str(investment).split('~')[-1]  # Need to force this to be a string.
        self.note = kwargs["note"] if "note" in kwargs else None
        self.id = kwargs["id"] if "id" in kwargs else None
        self.class_type = kwargs["class_type"] if "class_type" in kwargs else None
        self.cash = Decimal(0)

    @classmethod
    def sort(cls, sort_input: List) -> List:
        TYPE_ORDER = {
            "Balance": 1,
            "Deposit": 5,
            "Dividend": 10,
            "Sell": 15,
            "Buy": 20,
            "Withdraw": 25,
            "Other": 100,
        }

        sort_input.sort(
            key=lambda item: (-item.date.toordinal(), item.container_name, TYPE_ORDER[item.row_type])
        )

        return sort_input

    @classmethod
    def update_cash(cls, sorted_input: List, initial_value: Decimal = 0):
        """
        Call sort first or this make little sense
        """
        value: Decimal = Decimal(initial_value)
        for item in reversed(sorted_input):
            item.cash = item.value + value
            value = item.cash
        return sorted_input


class Transaction2Mixin:
    """
        Sets explicit_date
        transaction_data - Provide a list of Transactions to be used with Transaction2.html via transaction_data
    """

    def transaction_data(self,
                         base_accounts_query: QuerySet,   # Must resolve to a QuerySet of Accounts
                         reconcile_date: Union[date, None] = None,
                         initial_cash: Decimal = 0) -> List[ReconciliationRow]:
        """
        Return a list of ReconciliationRow records
        - If explicit_date is set,  the dfo scope is used to filter the XA between +/- 2 scope periods
        - elif reconcile_date is set,  the list will be all the records for that month
        - elif return all the records - can be a large table
        """

        if not hasattr(self, 'dfo'):  # it SHOULD be set!
            self.dfo = WealthDF(user=self.request.user, scope='month')

        if self.explicit_date:
            if self.dfo.scope == 'month':
                base_filter = Q(date__lt=self.explicit_date + relativedelta(months=2),
                                date__gte=self.explicit_date + relativedelta(months=2),
                                account__in=base_accounts_query)
            else:
                base_filter = Q(date__lt=IOOMDates.align_day(self.explicit_date + relativedelta(days=2)),
                                date__gte=IOOMDates.align_day(self.explicit_date + relativedelta(months=2)),
                                account__in=base_accounts_query),

        elif reconcile_date:
                reconcile_date = reconcile_date.replace(day=1)
                base_filter = Q(date__gte=reconcile_date,
                                date__lt=reconcile_date + relativedelta(months=1),
                                account__in=base_accounts_query)
        else:
            try:
                df = self.dfo.df
            except AttributeError:
                return []
            if df.empty:
                return []

            base_filter = Q(date__gte=df['Date'].min(),
                            date__lte=df['Date'].max(),
                            account__in=base_accounts_query)

        data = []
        for transaction in Transaction.objects.filter(base_filter).select_related("cash_record"):
            data.append(
                ReconciliationRow(
                    container_name = str(transaction.account),
                    date=transaction.date,
                    row_type=transaction.action_str,
                    value=transaction.cash_record.value,
                    investment=transaction.investment,
                    note=transaction.note,
                    id=transaction.pk,
                )
            )

        for funding in Funding.objects.filter(base_filter).select_related("cash_record"):
            if not funding.cash_record:
                value = funding.value
                account = 'Not Found'
            else:
                value = funding.cash_record.value
                account = str(funding.cash_record.account)
            data.append(
                ReconciliationRow(
                    container_name=account,
                    date=funding.date,
                    row_type=funding.funding_str,
                    value=value,
                    investment=None,
                    note=funding.note,
                    id=funding.pk,
                )
            )

        for cf in CashFlow.objects.filter(balance=True).filter(base_filter):
            name = str(cf.account) if cf.account else None
            data.append(
                ReconciliationRow(
                    container_name=name,
                    date=cf.date,
                    row_type='Balance',
                    value=cf.value,
                    investment=None,
                    note=cf.note,
                    id=cf.pk,
                )
            )

        for values in ValueBalance.objects.filter(base_filter):
            data.append(
                ReconciliationRow(
                    container_name=str(values.account),
                    date=values.date,
                    row_type='Balance',
                    value=values.value,
                    investment=None,
                    note=values.note,
                    id=values.pk,
                )
            )


        for divamount in (DividendAmount.objects.filter(
                cash_record__in=CashFlow.objects.filter(dividendamount__isnull=False).filter(base_filter)).
                select_related("cash_record")):
            data.append(
                ReconciliationRow(
                    container_name = str(divamount.cash_record.account),
                    date=divamount.cash_record.date,
                    row_type="Dividend",
                    value=divamount.cash_record.value,
                    investment=divamount.cash_record.investment,
                    note=divamount.cash_record.note,
                    id=divamount.pk
                )
            )

        ReconciliationRow.sort(data)
        return ReconciliationRow.update_cash(data, initial_value=initial_cash)


class WealthSummaryMixin(ContextMixinBase):
    """
    set self.dfo,  based on request user and range from WealthRangeMixin
    Update context with
    - full_summary
    - last_updated
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.dfo = WealthDF(self.request.user, date_range=self.wealth_range)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['full_summary'] = self.dfo.container_summary_by_date(self.dfo.df)
        try:
            context['last_updated'] = Investment.objects.filter(
                account__in=Account.objects.filter(user=self.request.user)).latest('last_updated').last_updated
        except Investment.DoesNotExist:
            context['last_updated'] = None
        return context

class ReconcileMonthMixin(WealthSummaryMixin):
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        try:
            self.view_date = datetime.strptime(self.kwargs['date_str'], '%Y-%m-%d').date()
        except ValueError:
            raise Http404('Invalid Date')

        self.view_date = self.view_date.replace(day=1)  # used to queryDB
        self.dfo = WealthDF(user=request.user, scope='month')
        self.df = self.dfo.df
        self.columns = ["Date", "Cash", "Funding", "Total"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['run_date'] = self.view_date
        context['run_date_str'] = self.view_date.strftime('%Y-%m-%d')
        context['next_date'] = self.view_date + relativedelta(months=1)
        if context['next_date'] > self.df['Date'].max().date():
            context['next_date'] = None

        context['previous_date'] = self.view_date - relativedelta(months=1)
        if context['previous_date'] < self.df['Date'].min().date():
            context['previous_date'] = None

        context['end_data'] = self.df.loc[self.df['Date'] == pd.to_datetime(self.view_date)].iloc[0].to_dict()
        previous_date_df = self.df.loc[self.df['Date'] == pd.to_datetime(self.view_date) - relativedelta(months=1)]

        if len(previous_date_df) == 0:
            context['start_data'] = None
        else:
            context["start_data"] = previous_date_df[self.columns].iloc[0].to_dict()

        return context