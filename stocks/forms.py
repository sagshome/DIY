from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import DataSource, Equity, EquityValue, Account, Transaction, Portfolio, CURRENCIES
from django.forms import formset_factory, inlineformset_factory, modelformset_factory
from django.core.validators import MinValueValidator

from base.utils import ReadonlyFieldsMixin, append_styles
from decimal import Decimal
from django.forms.widgets import HiddenInput


def popover_html(label, content):
    return label + ' <a tabindex="0" role="button" data-toggle="popover" data-html="true" \
                            data-trigger="hover" data-placement="auto" data-content="' + content + '"> \
                            <span class="glyphicon glyphicon-info-sign"></span></a>'


class EquityForm(forms.Form):
    choices = [(None, '--------')]
    #for equity in Equity.objects.all().order_by('symbol'):
    #  choices.append((equity.id, f'{equity.symbol} - {equity.region} ({equity.name})'))
    equity = forms.ChoiceField(choices=choices)


class AccountAddForm(ReadonlyFieldsMixin, forms.ModelForm):
    class Meta:
        model = Account
        fields = ('account_name', 'name', 'account_type', 'currency', 'managed', 'user')
        widgets = {
            'user': forms.HiddenInput(),
        }

    readonly_fields = ['user', ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "Display Name"
        append_styles(self.fields["account_type"].widget, width='200px', height='28.5px')
        append_styles(self.fields["name"].widget, width='200px', height='28.5px')
        append_styles(self.fields["account_name"].widget, width='200px', height='28.5px')
        append_styles(self.fields["currency"].widget, width='200px', height='28.5px')
        append_styles(self.fields["managed"].widget, width='200px', height='28.5px')


class AccountForm(AccountAddForm):
    class Meta:
        model = Account
        fields = ('account_name', 'name', 'account_type', 'portfolio', 'currency', 'managed', 'user')
        widgets = {
            'user': forms.HiddenInput(),
        }

    readonly_fields = ['user',  'account_name', 'account_type']
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.initial['user']:
            self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.filter(user=self.initial['user']))
        else:
            self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.none())

        current_value = self.instance.account_type
        label = dict(self.fields['account_type'].choices).get(current_value, current_value)
        self.fields['account_type'].choices = [(current_value, label)]

        self.fields['portfolio'].required = False
        append_styles(self.fields["portfolio"].widget, width='200px', height='28.5px')

class AccountCloseForm(forms.ModelForm):

    accounts = forms.ModelChoiceField(queryset=Account.objects.none(), label='Account to transfer into')

    class Meta:
        model = Account
        fields = ('account_name', 'name', 'accounts', '_end', 'user')
        widgets = {
            '_end': forms.TextInput(attrs={'type': 'date'}),
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
        self.fields["_end"].queryset = self.initial['_end']

    def clean(self):
        cleaned_data = super().clean()
        if 'accounts' in cleaned_data and cleaned_data['accounts']:
            account = cleaned_data['accounts']
        else:
            account = None

        result = self.instance.can_close(cleaned_data['_end'], transfer_to=account)
        if not result:
            raise forms.ValidationError(str(result))

        return cleaned_data


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'user')
        widgets = {
            'user': forms.HiddenInput(),
        }


class AccountCopyForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ('name', 'currency', 'managed', 'user')
        widgets = {
            'user': forms.HiddenInput(),
            'currency': forms.HiddenInput(),
            'managed': forms.HiddenInput(),
        }


class TransactionForm(forms.ModelForm):

    repeat = forms.ChoiceField(choices=[('no', 'No'), ('yes', 'Yes'),])
    number = forms.IntegerField(label='Num. of Repeats', max_value=11, min_value=1, required=False)
    to_account = forms.ModelChoiceField(Account.objects.all(), required=False)

    class Meta:
        model = Transaction
        fields = ("user", "xa_action", "account", "equity", "real_date", "price", "quantity", "value", "to_account", "repeat", "number")
        widgets = {
            'equity': forms.Select(attrs={'class': 'select2-field'}),  # Enable Select2)
            'user': forms.HiddenInput(),
            'xa_action': forms.Select(),
            'account': forms.HiddenInput(),
            'real_date': forms.TextInput(
                attrs={'type': 'date',
                       'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['xa_action'].choices = Transaction.TRANSACTION_TYPE
        self.fields['price'].required = False
        self.fields['value'].required = False
        self.fields['quantity'].required = False
        self.fields['equity'].queryset = Equity.objects.filter(equity_type='Equity')

        account = user = None
        try:
            account =  self.instance.account
        except Account.DoesNotExist:
            if 'initial' in kwargs and 'account' in kwargs['initial']:
                account = kwargs['initial']['account']
            if 'initial' in kwargs and 'user' in kwargs['initial']:
                user = kwargs['initial']['user']

        if account:
            self.fields['to_account'].queryset = Account.objects.filter(user=user).exclude(id=account.id)
        else:
            self.fields['to_account'].queryset = Account.objects.none()

    def clean_equity(self):
        account = self.cleaned_data['account']
        if account.account_type == 'Investment':
            if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and not self.cleaned_data['equity']:
                raise ValidationError("Buy, Sell, and ReInvest Dividend actions require an equity value", code="Empty Field")
            elif self.cleaned_data['xa_action'] not in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and self.cleaned_data['equity']:
                raise ValidationError("Fund and Redeem actions DO NOT require an equity value", code="Extra Field")
        return self.cleaned_data['equity']

    def clean_price(self):
        account = self.cleaned_data['account']
        if account.account_type == 'Investment':
            if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL] and not self.cleaned_data['price']:
                raise ValidationError("Buy and Sell actions require an price", code="Empty Field")
        return self.cleaned_data['price']

    def clean_quantity(self):
        account = self.cleaned_data['account']
        if account.account_type == 'Investment':
            if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and not self.cleaned_data['quantity']:
                raise ValidationError("This action requires an quantity", code="Empty Field")
        return self.cleaned_data['quantity']

    def clean_value(self):
        if self.cleaned_data['value'] is not None:
            if self.cleaned_data['value'] <= 0 and self.cleaned_data['xa_action'] != Transaction.SELL:
                raise ValidationError("Value must be non-zero and positive", code="Incorrect Field")
        elif self.cleaned_data['xa_action'] not in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES, Transaction.VALUE, Transaction.BALANCE] and not self.cleaned_data['value']:
            raise ValidationError("This action require an value", code="Empty Field")
        return self.cleaned_data['value']


class TransactionSetValueForm(TransactionForm):

    class Meta:
        model = Transaction
        fields = ("user", "account", "xa_action", "equity", "real_date", "price", "quantity", "value", "repeat", "number")

        widgets = {
            'user': forms.HiddenInput(),
            'xa_action': forms.Select(),
            'account': forms.HiddenInput(),
            'equity': forms.HiddenInput(),
            'real_date': forms.TextInput(
                attrs={'type': 'date',
                       'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['xa_action'].choices = [(self.initial['xa_action'], Transaction.TRANSACTION_MAP[self.initial['xa_action']])]
        self.fields['xa_action'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["xa_action"].widget.attrs['readonly'] = True


class TransactionEditForm(TransactionForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['real_date'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["real_date"].widget.attrs['readonly'] = True
        self.fields['xa_action'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["xa_action"].widget.attrs['readonly'] = True
        self.fields['equity'].widget.attrs['style'] = 'background-color:Wheat'
        self.fields["equity"].widget.attrs['readonly'] = True
        self.fields['equity'].queryset = Equity.objects.filter(id=self.initial['equity'])

        action_choices = Transaction.edit_choices(self.initial['xa_action'])
        self.fields['xa_action'].choices = action_choices
        if len(action_choices) == 1:
            self.fields['xa_action'].widget.attrs['style'] = 'background-color:Wheat'


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
                equity = Equity.objects.get(id=kwargs['initial']['equity'])
                if equity.searchable:
                    self.fields['price'].widget.attrs['style'] = 'background-color:Wheat'
                    self.fields["price"].widget.attrs['readonly'] = True
                else:
                    value_obj = EquityValue.objects.get(equity=equity, date=kwargs['initial']['report_date'])
                    if value_obj.source < DataSource.UPLOAD.value:
                        self.fields['price'].widget.attrs['style'] = 'background-color:Wheat'
                        self.fields["price"].widget.attrs['readonly'] = True
            except Equity.DoesNotExist:
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
    region = forms.ChoiceField(choices=Equity.REGIONS)
    equity_type = forms.ChoiceField(choices=Equity.EQUITY_TYPES)

    def clean(self):
        cleaned_data = super().clean()
        if Equity.objects.filter(symbol=cleaned_data['symbol'], region=cleaned_data['region']).exists():
            self.add_error('symbol', f"symbol {cleaned_data['symbol']} has already been defined for {cleaned_data['region']}")


class UploadFileForm(forms.Form):
    csv_type = forms.ChoiceField(label='Upload Type',
                                 choices=[('', '----',),
                                          ('Default', 'Default'),
                                          ('QuestTrade', 'QuestTrade'),
                                          ('Manulife', 'Manulife Original'),
                                          ('Wealth', 'Manulife Wealth')])
    new_account_currency = forms.ChoiceField(label='New Account Currency',
                                             choices=CURRENCIES)
    csv_file = forms.FileField()

    def clean(self):
        cleaned_data = super().clean()
        csv_type = cleaned_data.get("csv_type")

        if csv_type not in ('QuestTrade', 'Manulife', 'Wealth', 'Default'):
            self.add_error('csv_type', f"CSV Type {csv_type} is not currently valid")


class ReconciliationForm(forms.Form):
    equity_id = forms.IntegerField(widget=forms.HiddenInput(), required=True)
    Equity = forms.CharField(required=False, widget=forms.TextInput())

    Cost = forms.FloatField(required=False)
    Value = forms.FloatField(required=False)
    Shares = forms.FloatField(required=False, validators=[MinValueValidator(0)])
    Price = forms.FloatField(required=False, validators=[MinValueValidator(0)])
    Dividends = forms.FloatField(required=False, validators=[MinValueValidator(0)])
    TotalDividends = forms.FloatField(required=False, validators=[MinValueValidator(0)])

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
        if 'initial' in kwargs and 'Equity' in kwargs['initial']:
            if kwargs['initial']['Equity'].searchable:
                self.fields["Price"].widget.attrs['readonly'] = True
                self.fields["Price"].widget.attrs['style'] = 'width:95px;text-align: right;background-color:Wheat;'
                self.fields["Dividends"].widget.attrs['readonly'] = True
                self.fields["Dividends"].widget.attrs['style'] = 'width:95px;text-align: right;background-color:Wheat;'
            else:
                self.fields["Price"].widget.attrs['style'] = 'width:95px;text-align: right;'
                self.fields["Dividends"].widget.attrs['style'] = 'width:95px;text-align: right;'

        for field in ['Cost', 'Value', 'TotalDividends']:
            self.fields[field].widget.attrs['readonly'] = True
            self.fields[field].widget.attrs['style'] = 'width:95px;text-align: right;background-color:Wheat;'

        self.fields['Shares'].widget.attrs['style'] = 'width:95px;text-align: right;'
        self.fields["Equity"].widget.attrs['readonly'] = True
        self.fields["Equity"].widget.attrs['style'] = 'text-align: left;background-color:Wheat;'
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
    '''
    date = forms.DateField()
    reported_date = forms.DateField(required=True)
    value = forms.FloatField(required=True)
    source = forms.ChoiceField(choices=[(tag.value, tag.name) for tag in DataSource], required=False)
    deposited = forms.FloatField(required=True)
    withdrawn = forms.FloatField(required=True)

    def __init__(self, source=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'initial' in kwargs and 'super_user' in kwargs['initial'] and kwargs['initial']['super_user']:
            #choices = [(tag.value, tag.name) for tag in DataSource]
            #self.fields['source'] = forms.ChoiceField(
            #    choices=choices,
            #    required=False
            #)
            self.fields["source"].widget.attrs['style'] = 'width:100px;'
            #self.fields["source"] = kwargs['initial']['source']
        else:
            self.fields['source'] = forms.CharField(
                required=False,
                widget=forms.TextInput(attrs={'readonly': 'readonly'})
            )
            self.fields["source"].widget.attrs['style'] = 'width:100px;background-color:Wheat'


        self.fields["date"].widget.attrs['style'] = 'width:80px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True
        self.fields["reported_date"].widget.attrs['style'] = 'width:80px;'
        self.fields["value"].widget.attrs['style'] = 'width:80px;'
        self.fields["deposited"].widget.attrs['style'] = 'width:80px;'
        self.fields["withdrawn"].widget.attrs['style'] = 'width:80px;'
        #self.fields["source"].widget.attrs['style'] = 'width:150px;background-color:Wheat'
        #self.fields["source"].widget.attrs['readonly'] = True

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

    def clean_deposited(self):
        if self.cleaned_data['deposited'] < 0:
            raise ValidationError('Deposit must be a positive value')
        return self.cleaned_data['deposited']

    def clean_withdrawn(self):
        if self.cleaned_data['withdrawn'] > 0:
            raise ValidationError('Withdrawn must be a negative value')
        return self.cleaned_data['withdrawn']


SimpleReconcileFormSet = formset_factory(SimpleReconcileForm, extra=0)
