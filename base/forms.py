from django import forms
from django.contrib.auth.models import User
from phonenumber_field.formfields import PhoneNumberField
from base.models import CURRENCIES, COUNTRIES
from localflavor.ca.ca_provinces import PROVINCE_CHOICES
from localflavor.us.us_states import STATE_CHOICES


class MainForm(forms.Form):
    PERIODS = (
        ('MONTH', 'Months'),
        ('QTR', 'Quarters'),
        ('YEAR', 'Years'),
    )
    period = forms.ChoiceField(choices=PERIODS)
    years = forms.IntegerField(required=False, max_value=10)
    show_trends = forms.ChoiceField(required=False, choices=[('Show', 'Yes'), ('Hide', 'No')])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Adjusted to make W3C.CSS look nicer
        self.fields["period"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["years"].widget.attrs['style'] = 'width:50px;height:28.5px;'
        self.fields["show_trends"].widget.attrs['style'] = 'height:28.5px;'


class BaseProfileForm(forms.Form):
    """
    Update Profile (and some user attributes
    """

    email = forms.CharField(required=True, label='Email', help_text='Required')
    phone = PhoneNumberField(required=False, label='Phone Num.')
    birth_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    country = forms.ChoiceField(required=False, choices=COUNTRIES)
    full_name = forms.CharField(required=False)
    address_1 = forms.CharField(required=False)
    address_2 = forms.CharField(required=False)
    city = forms.CharField(required=False)
    state = forms.ChoiceField(required=False, choices=PROVINCE_CHOICES+STATE_CHOICES, label='State/Prov.')
    postal_code = forms.CharField(required=False)
    currency = forms.ChoiceField(choices=CURRENCIES)
    av_api_key = forms.CharField(required=False, max_length=24)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["email"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["phone"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["birth_date"].widget.attrs['style'] = 'width:120px;height:28.5px;'
        self.fields["full_name"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["address_1"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["address_2"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["city"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["state"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["country"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["currency"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["av_api_key"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["postal_code"].widget.attrs['style'] = 'width:275px;height:28.5px;'
        self.fields["country"].widget.attrs['class'] = 'diy-country'  # Used in the search javascript
        self.fields["state"].widget.attrs['class'] = 'diy-state'

    def clean_email(self):
        if User.objects.filter(username=self.cleaned_data['email']).exists():
            raise forms.ValidationError(f"This email is already in use {self.cleaned_data['email']}, maybe you could "
                                        f"reset your password.")
        return self.cleaned_data['email']

class ProfileForm(BaseProfileForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs['readonly'] = True
        self.fields["email"].widget.attrs['style'] = 'background-color:Wheat'
