
from django.db.models import CharField
from django.db.models import Value as ORMValue

from django.http import JsonResponse

from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import View

from base.ioom_dates import IOOMDates, IOOM_RANGES
from .dataframes import WealthDF
from .forms import TransactionForm
from .models import Account, Investment, Transaction, Funding, DataSource, ValueBalance


class ContextMixinBase:
    """
    Ensure the starting point of context,  should be last class on now context views
    """
    def get_context_data(self, **kwargs):
        return {}


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


class WealthRangeMixin:
    """
    Look for a 'range' option in the GET data,  if found set session variable 'wealth_range'
    - adds 'range' and 'range_string' to the context
    """

    def setup(self, request, *args, **kwargs):
        """
        Set self.wealth_range based on current or previous url range= option
        Default to a range = 'year'
        """
        super().setup(request, *args, **kwargs)
        if 'range' in self.request.GET:
            wealth_range = self.request.GET.get('range')
            if wealth_range in IOOM_RANGES:
                self.request.session['wealth_range'] = wealth_range
        self.wealth_range = self.request.session.get('wealth_range', 'year')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['range'] = self.wealth_range
        context['range_string'] = IOOMDates.range_to_string(self.wealth_range)
        return context


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


class WealthSummaryMixin(WealthRangeMixin):
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
            context['last_updated'] = Investment.objects.filter(account__in=Account.objects.filter(user=self.request.user)).latest('last_updated').last_updated
        except Investment.DoesNotExist:
            context['last_updated'] = None
        return context
