from django import forms
from django.core.exceptions import ValidationError
from .models import Equity, Portfolio, Transaction
from django.forms import formset_factory, inlineformset_factory, modelformset_factory

def popover_html(label, content):
    return label + ' <a tabindex="0" role="button" data-toggle="popover" data-html="true" \
                            data-trigger="hover" data-placement="auto" data-content="' + content + '"> \
                            <span class="glyphicon glyphicon-info-sign"></span></a>'
class AddEquityForm(forms.Form):

    search = forms.CharField(max_length=30,
                             widget=forms.TextInput(
                                                    attrs={'onkeyup':'fillOtherWindow()'}))
    region = forms.ChoiceField(choices=Equity.REGIONS)


class UploadForm(forms.Form):
    """
    Multi entry form
    """
    pass


class PortfolioForm(forms.ModelForm):
    class Meta:
        model = Portfolio
        fields = ('name', 'currency', 'managed', 'end')
        widgets = {
            'end': forms.TextInput(attrs={'type': 'date'})
        }


class TransactionForm(forms.Form):
    """
    Multi entry form
    """

    equity = forms.ModelChoiceField(label='Equity', queryset=Equity.objects.all().order_by('symbol'))
    date = forms.DateField(widget=forms.TextInput(attrs={'type': 'date',
                                                         'title': 'Select the Date for this transaction,  the date will be normalized to the first of the next month'}),
                           label='Date')
    price = forms.DecimalField(label='Price')
    quantity = forms.DecimalField(label='Quantity')
    action = forms.ChoiceField(label='Transaction Type',
                                 choices=[(Transaction.FUND, 'Fund'),
                                          (Transaction.BUY, 'Buy'),
                                          (Transaction.SELL, 'Sell'),
                                          (Transaction.REDEEM, 'Redeem')])
