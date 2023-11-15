from django import forms
from django.core.exceptions import ValidationError
from .models import Equity, Portfolio, Transaction
from django.forms import formset_factory, inlineformset_factory, modelformset_factory


class AddEquityForm(forms.Form):

    search = forms.CharField(max_length=30,
                             widget=forms.TextInput(
                                                    attrs={'onkeyup':'fillOtherWindow()'}))
    region = forms.ChoiceField(choices=Equity.REGIONS)


class AddPortfolioForm(forms.Form):

    name = forms.CharField()

    def clean_name(self):
        print('here')
        data = self.cleaned_data['name']
        data = data.lstrip(' ').rstrip(' ')
        if Portfolio.objects.filter(name=data).exists():
            raise ValidationError('Invalid portfolio name,  it already exists')
        return data


class TransactionForm(forms.Form):
    """
    Multi entry form
    """

    equity = forms.ChoiceField(choices=Equity.choice_list())
    date = forms.DateField(widget=forms.TextInput(attrs={'type': 'date'}))
    price = forms.DecimalField()
    quantity = forms.DecimalField()

    # class Meta:
    #     model = Transaction
    #     fields = ['equity', 'date', 'quantity', 'price']
    #     widgets = {
    #         'equity': forms.ChoiceField(choices=Equity.choice_list()),
    #         'date': forms.DateField(widget=forms.TextInput(attrs={'type': 'date'})),
    #         'quantity': forms.FloatField(),
    #         'price': forms.FloatField()
    #     }



#TransactionFormSet = formset_factory(TransactionForm, extra=1)
#TransactionFormSet = modelformset_factory(Transaction, fields=['equity', 'date', 'quantity', 'price'], extra=1 )

#TransactionFormset = formset_factory()
#    Transaction,
#    extra=1,
#    fields=['equity', 'date', 'quantity', 'price']
#)