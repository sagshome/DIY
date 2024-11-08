from datetime import datetime
from json import dumps

from django.contrib.auth.models import User
from django.shortcuts import render, HttpResponseRedirect
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm

from django.db import transaction

from django.views.generic.edit import FormView
from django.contrib.auth.forms import PasswordResetForm
from base.forms import UserRequestForm, UserForm, ProfileForm
from base.models import Profile
from django.contrib.auth.views import PasswordContextMixin, INTERNAL_RESET_SESSION_TOKEN
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q, Sum

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
    from_date = today.replace(year=today.year-1).strftime('%Y-%m-%d')
    item_search_criteria = {'search_ignore': 'No',
                            'search_start_date': from_date}
    items = Item.filter_search(Item.objects.filter(user=request.user, income=False), item_search_criteria)
    income = Item.filter_search(Item.objects.filter(user=request.user, income=True), item_search_criteria)

    expense_total = items.aggregate(Sum('amount'))['amount__sum']
    income_total = income.aggregate(Sum('amount'))['amount__sum']

    return render(request, "base/diy_main.html",{
        'expense_total': expense_total,
        'income_total': income_total,
        'item_search_criteria': dumps(item_search_criteria)})


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

