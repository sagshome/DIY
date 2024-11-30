from django import forms
from django.core.exceptions import ValidationError
from .models import DataSource, Equity, EquityValue, Account, Transaction, Portfolio, CURRENCIES
from django.forms import formset_factory, inlineformset_factory, modelformset_factory


def popover_html(label, content):
    return label + ' <a tabindex="0" role="button" data-toggle="popover" data-html="true" \
                            data-trigger="hover" data-placement="auto" data-content="' + content + '"> \
                            <span class="glyphicon glyphicon-info-sign"></span></a>'


class EquityForm(forms.Form):
    choices = [(None, '--------')]
    #for equity in Equity.objects.all().order_by('symbol'):
    #  choices.append((equity.id, f'{equity.symbol} - {equity.region} ({equity.name})'))
    equity = forms.ChoiceField(choices=choices)


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ('account_name', 'name', 'portfolio', 'currency', 'managed', 'account_type', 'user')
        widgets = {
            'end': forms.TextInput(attrs={'type': 'date'}),
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.initial['user']:
            self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.filter(user=self.initial['user']))
        else:
            self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.none())
        self.fields['portfolio'].required = False
        self.fields["account_name"].widget.attrs['readonly'] = True
        self.fields["account_name"].widget.attrs['style'] = 'background-color:Wheat'


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

    def clean__end(self):
        this = self.cleaned_data["_end"]
        if self.instance.transactions.latest('real_date').real_date > this:
            raise forms.ValidationError(f"Close date is before all transaction are completed {self.instance.transactions.latest('real_date').real_date}")
        return this


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


class AccountAddForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ('account_name', 'name', 'currency', 'managed', 'user')
        widgets = {
            'user': forms.HiddenInput(),
        }


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ("user", "account", "xa_action", "equity", "real_date", "price", "quantity", "value")
        widgets = {
            'user': forms.HiddenInput(),
            'xa_action': forms.Select(),
            'real_date': forms.TextInput(
                attrs={'type': 'date',
                       'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        valid_actions = [(None, '------'),
                         (Transaction.FUND, 'Fund'),
                         (Transaction.BUY, 'Buy'),
                         (Transaction.REDIV, 'ReInvested Dividends'),
                         (Transaction.SELL, 'Sell'),
                         (Transaction.REDEEM, 'Redeem'),
                         (Transaction.INTEREST, 'Cash/Deposit'),
                         (Transaction.FEES, 'Sell for FEES')]
        self.fields['account'] = forms.ModelChoiceField(queryset=Account.objects.filter(user=self.initial['user']))
        self.fields['xa_action'].choices = Transaction.TRANSACTION_TYPE
        self.fields['price'].required = False
        self.fields['value'].required = False
        self.fields['quantity'].required = False
        self.fields['equity'].queryset = Equity.objects.all().order_by('symbol')

    def clean_equity(self):
        if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and not self.cleaned_data['equity']:
            raise ValidationError("Buy, Sell, and ReInvest Dividend actions require an equity value", code="Empty Field")
        elif self.cleaned_data['xa_action'] not in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and self.cleaned_data['equity']:
            raise ValidationError("Fund and Redeem actions DO NOT require an equity value", code="Extra Field")
        return self.cleaned_data['equity']

    def clean_price(self):
        if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL] and not self.cleaned_data['price']:
            raise ValidationError("Buy and Sell actions require an price", code="Empty Field")
        else:
            return self.cleaned_data['price']

    def clean_quantity(self):
        if self.cleaned_data['xa_action'] in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and not self.cleaned_data['quantity']:
            raise ValidationError("This action require an quantity", code="Empty Field")
        else:
            return self.cleaned_data['quantity']

    def clean_value(self):
        if self.cleaned_data['xa_action'] not in [Transaction.BUY, Transaction.SELL, Transaction.REDIV, Transaction.FEES] and not self.cleaned_data['value']:
            raise ValidationError("Fund and Redeem actions require an value", code="Empty Field")
        else:
            return self.cleaned_data['value']


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
