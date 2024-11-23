from datetime import datetime
from json import dumps
from dateutil import relativedelta

from django.shortcuts import render
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required

from django.views.generic.edit import FormView
from django.contrib.auth.forms import PasswordResetForm
from base.forms import UserRequestForm, UserForm, ProfileForm
from base.models import Profile, PALETTE
from django.contrib.auth.views import PasswordContextMixin, INTERNAL_RESET_SESSION_TOKEN
from django.contrib.auth.tokens import default_token_generator
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear

from django.db.models import Q, Sum
from django.http import JsonResponse

from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView, PasswordResetCompleteView
from django.contrib.auth import login as auth_login
from django.views.generic.base import TemplateView

from expenses.models import Item


@login_required
def diy_main(request):
    today = datetime.now()
    from_date = today.replace(year=today.year-3, day=1)
    income = Item.objects.filter(user=request.user, ignore=False, date__gte=from_date, category__name='Income')
    expense = Item.objects.filter(user=request.user, ignore=False, date__gte=from_date).exclude(category__name='Income')

    expense_total = expense.aggregate(Sum('amount'))['amount__sum']
    income_total = income.aggregate(Sum('amount'))['amount__sum']

    income_set = income.annotate(qtr=TruncQuarter('date')).values('qtr').annotate(total=Sum('amount')).order_by('qtr')
    expense_set = expense.annotate(qtr=TruncQuarter('date')).values('qtr').annotate(total=Sum('amount')).order_by('qtr')

    # Data is in a list of [{'qtr': date, 'total': Decimal()}...] - A bit messy so lets make it a real dictionary
    income_dict = {}
    expense_dict = {}
    dates = []
    for element in income_set:
        dates.append(element['qtr'])
        income_dict[element['qtr']] = element['total']
    for element in expense_set:
        dates.append(element['qtr'])
        expense_dict[element['qtr']] = element['total']

    dates = sorted(list(set(dates)))   # A lot of work to ensure a unique sorted list!

    income_data = [0 for i in range(len(dates))]
    expense_data = [0 for i in range(len(dates))]
    labels = []
    datasets = []
    index = 0
    for next_date in dates:
        if next_date.month == 1:
            labels.append('Q1-' + str(next_date.year))
        elif next_date.month == 4:
            labels.append('Q2-' + str(next_date.year))
        elif next_date.month == 7:
            labels.append('Q3-' + str(next_date.year))
        elif next_date.month == 10:
            labels.append('Q4-' + str(next_date.year))
        else:
            labels.append(str(next_date.month) + '-' + str(next_date.year))

        if next_date in income_dict:
            income_data[index] = float(income_dict[next_date])
        if next_date in expense_dict:
            expense_data[index] = float(expense_dict[next_date])
        index += 1

        datasets = [{'label': 'Income',
                     'borderColor': PALETTE['olive'], #2ECC71',
                     'data': income_data,
                    },
                    {'label': 'Expenses',
                     'borderColor': PALETTE['coral'], #FF6F61',
                     'data': expense_data,
                    }]
    cash_data = {'datasets': datasets, 'labels': labels}  #, 'colors': ['#2ECC71', '#FF6F61']}

    return render(request, "base/diy_main.html",{
        'expense_total': expense_total,
        'income_total': income_total,
        'cash_data': cash_data
    })

def sites_up(request):
    return JsonResponse({'up': True})

class NewAccountView(PasswordResetView):
    """
    This is cloned from django.contrib.auth.views.PasswordResetView.

    """
    email_template_name = "base/new_account_email.html"
    form_class = UserRequestForm  # Most of the work is done here
    success_url = reverse_lazy("new_account_done")
    template_name = "base/new_account_form.html"


class NewAccountConfirmView(PasswordResetConfirmView):
    """
    This is cloned from django.contrib.auth.views.PasswordResetConfirmView.
    """

    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_active = True
        return super().form_valid(form)


class NewAccountDoneView(PasswordContextMixin, TemplateView):
    template_name = "base/new_account_done.html"
    title = "New Account Sent"


class NewAccountComplete(PasswordResetCompleteView):
    class PasswordResetCompleteView(PasswordContextMixin, TemplateView):
        template_name = "registration/password_reset_complete.html"


def diy_help(request, fakepath):
    return render(request, "diy/help.html", {})

