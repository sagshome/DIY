from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.template import loader
from django.core.mail import EmailMultiAlternatives
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes


from base.models import Profile, CURRENCIES


class UserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name')


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('currency', 'av_api_key')


class UserRequestForm(PasswordResetForm):
    """
    Build both the base user and the base profile objects.
    """
    currency = forms.ChoiceField(choices=CURRENCIES)
    first_name = forms.CharField(required=False, max_length=150)
    last_name = forms.CharField(required=False, max_length=150)
    av_api_key = forms.CharField(required=False, max_length=24)

    def save(
        self,
        domain_override=None,
        subject_template_name="registration/new_account_subject.txt",
        email_template_name="registration/password_reset_email.html",
        use_https=False,
        token_generator=default_token_generator,
        from_email=None,
        request=None,
        html_email_template_name=None,
        extra_email_context=None,
    ):
        """
        Generate a one-use only link for resetting password and send it to the
        user.
        """
        email = self.cleaned_data["email"]
        user = User.objects.create(username=email,  email=email, is_active=False,
                                   first_name=self.cleaned_data["first_name"],
                                   last_name=self.cleaned_data["last_name"])

        Profile.objects.create(user=user,  currency=self.cleaned_data["currency"],
                                         av_api_key=self.cleaned_data["av_api_key"])
        if not domain_override:
            current_site = get_current_site(request)
            site_name = current_site.name
            domain = current_site.domain
        else:
            site_name = domain = domain_override

        context = {
            "email": email,
            "domain": domain,
            "site_name": site_name,
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "user": email,
            "token": token_generator.make_token(user),
            "protocol": "https" if use_https else "http",
            **(extra_email_context or {}),
        }

        self.send_mail(
            "registration/new_account_subject.txt",  # Seems like a bug,  that save did not save it
            email_template_name,
            context,
            from_email,
            email,
            html_email_template_name=html_email_template_name,
        )

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(username=email).exists():
            raise ValidationError('This email is already in use,  perhaps you need to reset your password')
        return email
