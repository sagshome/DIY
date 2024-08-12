from datetime import datetime
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
    items = Item.objects.filter(user=request.user)
    today = datetime.now()
    from_date = today.replace(year=today.year-2)

    return render(request, "base/diy_main.html",
                  {'expense_total': items.count(),
                          'expenses_ignored': items.filter(ignore=True).count(),
                          'expenses_uncategorized': items.filter(ignore=False, category__isnull=True),
                          'from_date': from_date.strftime('%Y-%m-%d')})


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

