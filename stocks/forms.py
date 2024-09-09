from django import forms
from django.core.exceptions import ValidationError
from .models import Equity, Portfolio, Transaction
from django.forms import formset_factory, inlineformset_factory, modelformset_factory


def popover_html(label, content):
    return label + ' <a tabindex="0" role="button" data-toggle="popover" data-html="true" \
                            data-trigger="hover" data-placement="auto" data-content="' + content + '"> \
                            <span class="glyphicon glyphicon-info-sign"></span></a>'

class EquityForm(forms.Form):
    choices = [(None, '--------')]
    for equity in Equity.objects.all().order_by('symbol'):
       choices.append((equity.id, f'{equity.symbol} - {equity.region} ({equity.name})'))
    equity = forms.ChoiceField(choices=choices)


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'managed', 'user', 'end')
        widgets = {
            'end': forms.TextInput(attrs={'type': 'date'}),
            'user': forms.HiddenInput(),
        }


class PortfolioCopyForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'managed', 'user', 'end')
        widgets = {
            'end': forms.HiddenInput(),
            'user': forms.HiddenInput(),
            'currency': forms.HiddenInput(),
            'managed': forms.HiddenInput(),
        }


class PortfolioAddForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'managed', 'user')
        widgets = {
            'user': forms.HiddenInput(),
        }


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ("user", "portfolio", "xa_action", "equity", "real_date", "price", "quantity", "value")
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
                         (Transaction.FEES, 'Sell for FEES')]
        self.fields['portfolio'] = forms.ModelChoiceField(queryset=Portfolio.objects.filter(user=self.initial['user']))
        self.fields['xa_action'].choices = valid_actions
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

    portfolio = forms.IntegerField(widget=forms.HiddenInput(), required=True)
    equity = forms.IntegerField(widget=forms.HiddenInput(), required=True)
    report_date = forms.DateField()
    shares = forms.FloatField()
    value = forms.FloatField()

    class Meta:
        widgets = {
            'real_date': forms.TextInput(
                attrs={'type': 'date',
                       'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
    stub = forms.CharField(label="Portfolio Prefix", required=False, max_length=16,
                           help_text='Optional field that is used to decorate any portfolio in the uploaded csv file')
    #csv_type = forms.CharField(choices=choices, default='QuestTrade')
    csv_type = forms.ChoiceField(label='Upload Type',
                                 choices=[('', '----',),
                                          ('Default', 'Default'),
                                          ('QuestTrade', 'QuestTrade'),
                                          ('Manulife', 'Manulife')])
    #csv_type3 = forms.ChoiceField(choices=choices)
    csv_file = forms.FileField()

    def clean(self):
        cleaned_data = super().clean()
        csv_type = cleaned_data.get("csv_type")

        if csv_type not in ('QuestTrade', 'Manulife'):
            self.add_error('csv_type', f"CSV Type {csv_type} is not currently valid")
        csv_type = cleaned_data.get("csv_type")

        if csv_type not in ('QuestTrade', 'Manulife'):
            self.add_error('csv_type', f"CSV Type {csv_type} is not currently valid")
