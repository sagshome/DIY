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
from base.forms import MainForm
from stocks.tasks import add_to_cache


@login_required
def diy_main(request):

    span = 3
    period = 'QTR'
    trends = 'Hide'

    if request.method == 'POST':
        form = MainForm(request.POST)
        if form.is_valid():
            span = form.cleaned_data['years'] if form.cleaned_data['years'] else 3
            period = form.cleaned_data['period']
            trends = 'Show' if form.cleaned_data['show_trends'] == 'Show' else 'Hide'
    else:
        form = MainForm(initial={'years': span, 'period': period, 'show_trends': 'Hide'})
        if request.user:
            add_to_cache.delay(request.user.id)  # Update the redis cache for the accounts owned by this user.
    return render(request, "base/diy_main.html",{'form': form, 'span': span, 'period': period, 'trends': trends})


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

