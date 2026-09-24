from datetime import datetime, date

from pandas import Timestamp
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import DataSource, Investment, Value, Account, Transaction, Portfolio, CURRENCIES, DividendAmount
from django.forms import formset_factory, inlineformset_factory, modelformset_factory, BaseFormSet
from django.core.validators import MinValueValidator
from django.db import models

from base.utils import ReadonlyFieldsMixin, append_styles
from decimal import Decimal
from django.forms.widgets import HiddenInput



def popover_html(label, content):
    return label + ' <a tabindex="0" role="button" data-toggle="popover" data-html="true" \
                            data-trigger="hover" data-placement="auto" data-content="' + content + '"> \
                            <span class="glyphicon glyphicon-info-sign"></span></a>'


class ModalBase:
    success_url = forms.URLField(required=False, widget=forms.HiddenInput())
    is_modal = forms.BooleanField(required=False, widget=forms.HiddenInput())


class ModalBaseForm(ModalBase, forms.Form):
    pass

class TransactionChoices(models.IntegerChoices):
    NONE = 0, "----------"
    FUND = 1, "Deposit"
    BUY = 2, "Buy"
    REDIV = 3, "Reinvested Dividend"
    SELL = 4, "Sell"
    INTEREST = 5, "Interest"
    REDEEM = 6, "Withdraw"
    FEES = 7,  "Fees"
    TRANS_IN = 8, "Cash Transferred IN"
    TRANS_OUT = 9, "Cash Transferred OUT"
    VALUE = 10, "Current Value"
    BALANCE = 11, "Current Balance"


class EquityForm(forms.Form):
    choices = [(None, '--------')]
    #for equity in Equity.objects.all().order_by('symbol'):
    #  choices.append((equity.id, f'{equity.symbol} - {equity.region} ({equity.name})'))
    equity = forms.ChoiceField(choices=choices)


class AccountForm(ReadonlyFieldsMixin, forms.ModelForm):
    success_url = forms.URLField(required=False, widget=forms.HiddenInput())
    is_modal = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Account
        fields = ('account_name', 'name', 'acct_type', 'currency', 'managed', 'user', 'success_url', 'is_modal')
        widgets = {
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["name"].label = "Display Name"
        append_styles(self.fields["acct_type"].widget, width='200px', height='28.5px')
        append_styles(self.fields["name"].widget, width='200px', height='28.5px')
        append_styles(self.fields["account_name"].widget, width='200px', height='28.5px')
        append_styles(self.fields["currency"].widget, width='200px', height='28.5px')
        append_styles(self.fields["managed"].widget, width='200px', height='28.5px')



class AccountEditForm(AccountForm):

    class Meta:
        model = Account
        fields = ('account_name', 'name', 'acct_type', 'portfolio', 'currency', 'managed', 'user', 'success_url', 'is_modal')
        widgets = {
            'user': forms.HiddenInput(),
        }

    readonly_fields = ['user',  'account_name', 'acct_type']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.filter(user=self.instance.user))
        self.fields['portfolio'].required = False
        append_styles(self.fields["portfolio"].widget, width='200px', height='28.5px')

        acct_type_choices = dict(self.fields['acct_type'].choices).get(self.instance.acct_type, self.instance.acct_type)
        self.fields['acct_type'].choices = [(self.instance.acct_type, acct_type_choices)]


class AccountCloseForm(forms.ModelForm):

    success_url = forms.URLField(required=False, widget=forms.HiddenInput())
    is_modal = forms.BooleanField(required=False, widget=forms.HiddenInput())

    accounts = forms.ModelChoiceField(queryset=Account.objects.none(), label='Account to transfer into')

    class Meta:
        model = Account
        fields = ('account_name', 'name', 'accounts', 'user', 'closed', 'success_url', 'is_modal')
        widgets = {
            'closed': forms.TextInput(attrs={'type': 'date'}),
            'user': forms.HiddenInput(),

        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account_name"].widget.attrs['readonly'] = True
        self.fields["account_name"].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["name"].widget.attrs['readonly'] = True
        self.fields["name"].widget.attrs['style'] = 'background-color:Wheat'
        self.fields['accounts'].required = False
        self.fields["accounts"].queryset = self.initial['accounts']
        self.fields["closed"].queryset = self.initial['closed']


    def clean(self):
        cleaned_data = super().clean()
        if 'accounts' in cleaned_data and cleaned_data['accounts']:
            account = cleaned_data['accounts']
        else:
            account = None

        result = self.instance.can_close(cleaned_data['closed'])
        if result:
            raise forms.ValidationError(str(result))

        return cleaned_data


class DividendAmountForm(forms.Form):
    success_url = forms.URLField(required=False, widget=forms.HiddenInput())
    is_modal = forms.BooleanField(required=False, widget=forms.HiddenInput())
    altered = forms.BooleanField(required=False, widget=forms.HiddenInput())
    ex_date = forms.DateField(required=True, help_text='This is the date when the Dividend was issued')
    paid_date = forms.DateField(required=True, help_text='This is the date when the Dividend appears in your account')
    value = forms.DecimalField(required=True, validators=[MinValueValidator(Decimal('0.00'))], help_text='How much was transferred into your account')
    note = forms.CharField(required=False, max_length=128, help_text='An optional short description of the event')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ex_date"].widget.attrs["readonly"] = True
        self.fields['ex_date'].widget.attrs['style'] = 'background-color:Wheat;'
        self.fields["ex_date"].widget.attrs['style'] = 'width:120px;height:28.5px;'
        self.fields["paid_date"].widget.attrs['style'] = 'width:120px;height:28.5px;'
        self.fields["value"].widget.attrs['style'] = 'width:100px;height:28.5px;'
        self.fields["note"].widget.attrs['style'] = 'width:700px;height:28.5px;'


class PortfolioForm(forms.ModelForm):

    success_url = forms.URLField(required=False, widget=forms.HiddenInput())
    is_modal = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'user', 'success_url', 'is_modal')
        widgets = {
            'user': forms.HiddenInput(),
        }


class TransactionForm(forms.Form):

    TRANSACTION_TYPE = ((None, '---------'),
                        ('FUND', 'Deposit'),  # Value only and always positive
                        ('BUY', 'Buy'),  # Price and Quantity
                        ('REDIV', 'Reinvested Dividend'),  # Price and Quantity but Price is set to 0
                        ('SELL', 'Sell'),
                        ('INTEREST', 'Dividends/Interest'),
                        ('REDEEM', 'Withdraw'),
                        ('FEES', 'Fees Paid'),
                        ('TRANS_IN', 'Transfer In'),
                        ('TRANS_OUT', 'Transfer Out'),
                        ('VALUE', 'Set Value'),
                        ('BALANCE', 'Set Balance'),
                        ('ADJDIV', 'Adjust Dividend')
                        )

    TRANSACTION_DICT = dict(TRANSACTION_TYPE) # Used in views for form rendering


    user = forms.CharField(required=True, widget=forms.HiddenInput())
    account = forms.ModelChoiceField(Account.objects.all(), widget=forms.HiddenInput())
    to_account = forms.ModelChoiceField(Account.objects.all(), required=False, widget=forms.HiddenInput())
    success_url = forms.URLField(widget=forms.HiddenInput())

    repeat = forms.ChoiceField(choices=[('no', 'No'), ('yes', 'Yes'),])
    number = forms.IntegerField(label='Num. of Repeats', max_value=11, min_value=1, required=False)
    investment = forms.ModelChoiceField(required=False, queryset=Investment.objects.filter(inv_type='trading'), widget=forms.Select(attrs={'class': 'select2-field'}))
    date: date = forms.DateField(required=True, widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    price = forms.DecimalField(required=False, validators=[MinValueValidator(Decimal('0.01'))])
    quantity = forms.DecimalField(required=False, validators=[MinValueValidator(Decimal('0.01'))])
    value = forms.DecimalField(required=False, validators=[MinValueValidator(Decimal('0'))])
    action = forms.ChoiceField(choices=TRANSACTION_TYPE)
    action2 = models.IntegerField(choices=TransactionChoices.choices, default=TransactionChoices.NONE)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['investment'].queryset = Investment.objects.filter(inv_type='Trading')

        account = user = None
        if 'initial' in kwargs:
            if 'account' in kwargs['initial']:
                account = kwargs['initial']['account']
            if 'user' in kwargs['initial']:
                user = kwargs['initial']['user']
            if 'success_url' in kwargs:
                success_url = kwargs['initial']['success_url']

        if account:
            self.fields['to_account'].queryset = Account.objects.filter(user=user).exclude(id=account.id)
        else:
            self.fields['to_account'].queryset = Account.objects.none()


class TransactionSetValueForm(TransactionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'action' in self.initial:
            for key, text in TransactionForm.TRANSACTION_TYPE:
                if key == self.initial['action']:
                    self.fields['action'].choices = [(key, text)]
                    break

        self.fields["action"].widget.attrs['readonly'] = True
        self.fields['action'].widget.attrs['style'] = 'background-color:Wheat'


class TransactionEditForm(TransactionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True
        self.fields['action'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["action"].widget.attrs['readonly'] = True
        self.fields['action'].choices = [(self.initial['action'], dict(self.TRANSACTION_TYPE)[self.initial['action']])]


class ManualUpdateEquityForm(forms.Form):

    account = forms.IntegerField(widget=forms.HiddenInput(), required=True)
    equity = forms.IntegerField(widget=forms.HiddenInput(), required=True)
    report_date = forms.DateField()
    shares = forms.FloatField(required=False)
    value = forms.FloatField(required=False)
    price = forms.FloatField(required=False)

    class Meta:
        widgets = {
            'real_date': forms.TextInput(
                attrs={'type': 'date',
                       'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'initial' in kwargs and 'equity' in kwargs['initial']:
            try:
                equity = Investment.objects.get(id=kwargs['initial']['investment'])
                if equity.searchable:
                    self.fields['price'].widget.attrs['style'] = 'background-color:Wheat'
                    self.fields["price"].widget.attrs['readonly'] = True
                else:
                    value_obj = Value.objects.get(equity=equity, date=kwargs['initial']['report_date'])
                    if value_obj.source < DataSource.UPLOAD.value:
                        self.fields['price'].widget.attrs['style'] = 'background-color:Wheat'
                        self.fields["price"].widget.attrs['readonly'] = True
            except Investment.DoesNotExist:
                pass

        self.fields['value'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["value"].widget.attrs['readonly'] = True

        self.fields['report_date'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["report_date"].widget.attrs['readonly'] = True

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data


class AddEquityForm(forms.Form):

    symbol = forms.CharField(required=True, max_length=36)
    description = forms.CharField(required=False, max_length=128)
    # region = forms.ChoiceField(choices=Equity.REGIONS)
    # equity_type = forms.ChoiceField(choices=Equity.EQUITY_TYPES)

    def clean(self):
        cleaned_data = super().clean()
        if Investment.objects.filter(symbol=cleaned_data['symbol'], region=cleaned_data['region']).exists():
            self.add_error('symbol', f"symbol {cleaned_data['symbol']} has already been defined for {cleaned_data['region']}")


class UploadFileForm(forms.Form):
    user = forms.CharField(required=True, widget=forms.HiddenInput())
    success_url = forms.URLField(widget=forms.HiddenInput())
    transaction_file = forms.FileField()


class ReconciliationForm(forms.Form):
    AccountID = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    InvTtype = forms.CharField(widget=forms.HiddenInput(), required=False)
    Estimated = forms.BooleanField(widget=forms.HiddenInput(), required=False)

    Symbol = forms.CharField(required=True)
    Quantity = forms.DecimalField(required=True, validators=[MinValueValidator(0)])
    Price = forms.DecimalField(required=True, validators=[MinValueValidator(0)])
    DivValue = forms.DecimalField(required=False, validators=[MinValueValidator(0)])

    def data_changed(self, initial, key1,  key2=None):
        new_key1 = 0 if key1 not in self.cleaned_data or not self.cleaned_data[key1] else self.cleaned_data[key1]
        old_key1 = 0 if not initial[key1] else initial[key1]
        if not (float(new_key1) == old_key1):
            return True
        if key2:
            new_key2 = 0 if key2 not in self.cleaned_data or not self.cleaned_data[key2] else self.cleaned_data[key2]
            old_key2 = 0 if not initial[key2] else initial[key2]
            if not (float(new_key2) == old_key2):
                return True
        return False

    class Meta:
        widgets = {
            'Date': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        investment = Investment.objects.get(symbol=self.initial['Symbol'])
        if not investment.searchable:
            self.fields["Price"].widget.attrs['style'] = 'width:95px;text-align: right;'
            self.fields["DivValue"].widget.attrs['style'] = 'width:95px;text-align: right;'
        else:
            self.fields["Price"].widget.attrs['style'] = 'background-color:Wheat;width:95px;text-align: right;'
            self.fields["Price"].widget.attrs['readonly'] = True

            self.fields["DivValue"].widget.attrs['style'] = 'background-color:Wheat;width:95px;text-align: right;'
            self.fields["DivValue"].widget.attrs['readonly'] = True

        self.fields['Quantity'].widget.attrs['style'] = 'width:95px;text-align: right;'
        self.fields["Symbol"].widget.attrs['readonly'] = True
        self.fields["Symbol"].widget.attrs['style'] = 'text-align: left;width:95;background-color:Wheat;'

        for field in ['Price', 'Quantity', 'DivAmount']:
            if not self.initial[field]:
                self.initial[field] = Decimal(0)
            else:
                self.initial[field] = Decimal(str(self.initial[field])).quantize(Decimal('0.01'))


ReconciliationFormSet = formset_factory(ReconciliationForm, extra=0)


class SimpleCashReconcileForm(forms.Form):
    '''
    Simple form to update funding, redeeming and values for non-investment accounts.
    '''
    date = forms.DateField()
    reported_date = forms.DateField(required=True)
    value = forms.FloatField(required=True)
    source = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].widget.attrs['style'] = 'width:80px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True
        self.fields["reported_date"].widget.attrs['style'] = 'width:80px;'
        self.fields["value"].widget.attrs['style'] = 'width:80px;'
        self.fields["source"].widget.attrs['style'] = 'width:150px;background-color:Wheat'
        self.fields["source"].widget.attrs['readonly'] = True

    def clean_reported_date(self):
        reported_date = self.cleaned_data['reported_date']
        normalized_date = self.cleaned_data['date']
        if reported_date.month != normalized_date.month or reported_date.year != normalized_date.year:
            raise ValidationError(f"Record {normalized_date} - Reported Date {reported_date}must be in the same month", code="Incorrect Field")
        if reported_date.year < 2000:
            raise ValidationError(f"Reported Date {reported_date} must be in this century (2000+)", code="Incorrect Field")
        return self.cleaned_data['reported_date']

    def clean_value(self):
        if self.cleaned_data['value'] < 0:
            raise ValidationError('Value must be a positive value')
        return self.cleaned_data['value']


SimpleCashReconcileFormSet = formset_factory(SimpleCashReconcileForm, extra=0)


class SimpleReconcileForm(forms.Form):
    '''
    Simple form to update funding, redeeming and values for non-investment accounts.
    limiting number to 9 for 9,999,999.99  - if you got 10m,  just call me and we can work something out.
    '''
    Date = forms.DateField()
    Total = forms.DecimalField(required=False, max_digits=9, decimal_places=2, )# validators=[MinValueValidator(Decimal('0.00'))])
    Funding = forms.DecimalField(required=False, max_digits=9, decimal_places=2, )# validators=[MinValueValidator(Decimal('0.00'))])
    Cash = forms.DecimalField(required=False, max_digits=9, decimal_places=2, )#  validators=[MinValueValidator(Decimal('0.00'))])

    Total_est = forms.BooleanField(required=False)

    def __init__(self, *args, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account

        if 'Date' in self.initial:
            if isinstance(self.initial['Date'], Timestamp):
                self.initial['Date'] = self.initial['Date'].date()

        for field in ['Total', 'Funding', 'Cash']:
            if field not in self.initial or not self.initial[field]:
                self.initial[field] = Decimal(0)
            else:
                self.initial[field] = Decimal(str(self.initial[field])).quantize(Decimal('0.01'))

        self.fields["Date"].widget.attrs['style'] = 'width:110px;background-color:Wheat'
        self.fields["Date"].widget.attrs['readonly'] = True

        if self.account.acct_type == 'Trading':
            self.fields["Total"].widget.attrs['style'] = 'width:100px;background-color:Wheat'
            self.fields["Total"].widget.attrs['readonly'] = True
        elif self.account.acct_type == 'Value':
            self.fields["Total"].widget.attrs['style'] = 'width:110px'

        self.fields["Funding"].widget.attrs['style'] = 'width:110px'
        self.fields["Cash"].widget.attrs['style'] = 'width:110px'

        self.fields["Total_est"].widget.attrs['style'] = 'width:110px;background-color:Wheat'
        self.fields["Total_est"].widget.attrs['readonly'] = True


class BaseSimpleReconcileFormSet(BaseFormSet):

    def __init__(self, *args, account=None, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)

        kwargs["account"] = self.account
        return kwargs


SimpleReconcileFormSet = formset_factory(SimpleReconcileForm,
                                         formset=BaseSimpleReconcileFormSet,
                                         extra=0)

class BaseDividendAmountFormSet(BaseFormSet):

    def __init__(self, *args, account=None, equity=None, **kwargs):
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)

        return kwargs

DividendAmountFormSet = formset_factory(DividendAmountForm,
                                        formset=BaseDividendAmountFormSet,
                                        extra=0)