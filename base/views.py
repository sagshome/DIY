import logging
from django.core.mail import EmailMultiAlternatives
from django.template import loader
from django.http import HttpResponseRedirect

from django.shortcuts import render
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordContextMixin

from django.http import JsonResponse

from localflavor.ca.ca_provinces import PROVINCE_CHOICES
from localflavor.us.us_states import STATE_CHOICES
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetCompleteView
from django.views.generic.base import TemplateView
from django.contrib.sites.shortcuts import get_current_site
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator


from base.forms import MainForm, ProfileForm, BaseProfileForm
from base.models import Profile
from stocks.tasks import add_to_cache

logger = logging.getLogger(__name__)


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
    return render(request, "base/diy_main.html", {
        'form': form, 'span': span, 'period': period, 'trends': trends, "help_file": "base/help/diy_main.html"})


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


def profile_create(request):
    if request.method == 'POST':
        form = BaseProfileForm(request.POST)
        if form.is_valid():
            pieces = form.cleaned_data['full_name'].split()
            if len(pieces) >= 2:
                last_name = pieces[-1]
                first_name = ' '.join(pieces[0:-1])
            elif len(pieces) == 1:
                last_name = pieces[0]
                first_name = ''
            else:
                last_name = ''
                first_name = ''

            user = User.objects.create(username=form.cleaned_data['email'],
                                       is_active=False,
                                       first_name=first_name,
                                       last_name=last_name)

            Profile.objects.create(user=user,
                                   country=form.cleaned_data['country'],
                                   phone_number=form.cleaned_data['phone'],
                                   address1=form.cleaned_data['address_1'],
                                   address2=form.cleaned_data['address_2'],
                                   city=form.cleaned_data['city'],
                                   state=form.cleaned_data['state'],
                                   postal_code=form.cleaned_data['postal_code'],
                                   currency=form.cleaned_data['currency'],
                                   av_api_key=form.cleaned_data['av_api_key'],
                                   )

            current_site = get_current_site(request)
            site_name = current_site.name
            domain = current_site.domain
            context = {
                "email": form.cleaned_data['email'],
                "domain": domain,
                "site_name": site_name,
                "uid": urlsafe_base64_encode(force_bytes(user.pk)),
                "user": form.cleaned_data['email'],
                "token": default_token_generator.make_token(user),
                "protocol": "http"}
            subject = f'Account Created for {form.cleaned_data["email"]} at site {site_name}'
            body = loader.render_to_string("registration/password_reset_email.html", context)
            email_message = EmailMultiAlternatives(subject, body, None, [form.cleaned_data['email']])

            try:
                email_message.send()
                return HttpResponseRedirect(reverse('new_account_done'))
            except Exception:
                logger.exception("Failed to send password reset email to %s", context["user"])

    else:
        form = BaseProfileForm()

    return render(request, "base/profile.html", {"form": form, 'verb': 'Create'})


@login_required
def profile_edit(request):
    profile = Profile.objects.get(user=request.user)
    if request.method == "GET":
        initial = {'email': request.user.username,
                   'phone': request.user.profile.phone_number,
                   'birth_date': request.user.profile.birth_date,
                   'full_name': f'{request.user.first_name} {request.user.last_name}',
                   'address_1': request.user.profile.address1,
                   'address_2': request.user.profile.address2,
                   'city': request.user.profile.city,
                   'state': request.user.profile.state,
                   'postal_code': request.user.profile.postal_code,
                   'country': request.user.profile.country,
                   'currency': profile.currency,
                   'api_key': profile.av_api_key
                   }
        form = ProfileForm(initial=initial)
    else:
        form = ProfileForm(request.POST)
        if form.is_valid():
            pieces = form.cleaned_data['full_name'].split()
            if len(pieces) >= 2:
                request.user.last_name = pieces[-1]
                request.user.first_name = ' '.join(pieces[0:-1])
            elif len(pieces) == 1:
                request.user.last_name = pieces[0]
                request.user.first_name = ''
            else:
                request.user.last_name = ''
                request.user.first_name = ''
            profile.country = form.cleaned_data['country']
            profile.birth_date = form.cleaned_data['birth_date']
            profile.phone_number = form.cleaned_data['phone']
            profile.address1 = form.cleaned_data['address_1']
            profile.address2 = form.cleaned_data['address_2']
            profile.city = form.cleaned_data['city']
            profile.state = form.cleaned_data['state']
            profile.postal_code = form.cleaned_data['postal_code']
            profile.currency = form.cleaned_data['currency']
            profile.av_api_key = form.cleaned_data['av_api_key']
            request.user.save()
            profile.save()
            return render(request, "base/diy_main.html")
    return render(request, "base/profile.html", {"form": form, 'verb': 'Edit'})


def get_state(request):
    country = request.GET.get("country")
    if country and country == 'US':
        choices = STATE_CHOICES
    elif country and country == 'CA':
        choices = PROVINCE_CHOICES
    else:
        choices = []
    return render(request, "base/state_list_options.html", {"subcat": choices})
