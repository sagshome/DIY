import re
from django import forms
from expenses.models import Item, SubCategory, Template, Category


class ItemSearchForm(forms.ModelForm):
    """
    A form to support searching of expenses
    - Need to build a subcategory choice list so I can remove non-unique values
    """
    start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    amount_qualifier = forms.ChoiceField(label='', choices=[('equal', '=='), ('lte', '<='), ('gte', '>='),])
    # template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    class Meta:
        model = Item
        fields = ("description", "category", "subcategory", "ignore", "start_date", "end_date", "amount_qualifier", "amount")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['amount'].required = False
        self.fields["amount"].widget.attrs['style'] = 'width:75px;'


        self.fields["category"].widget.attrs['class'] = 'diy-search-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'

        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['class'] = 'diy-search-subcategory'


class TemplateForm(forms.ModelForm):

    # template_type = forms.ChoiceField(label="Type", required=False, choices=Template.CHOICES)

    class Meta:
        model = Template
        fields = ("type", "expression",  "category", "subcategory", "ignore")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["type"].widget.attrs['style'] = 'width:110px;'
        self.fields["expression"].widget.attrs['style'] = 'width:400px;'
        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'


class UploadFileForm(forms.Form):
    csv_type = forms.ChoiceField(label="Expense Source",
                                 choices=[('', "----",),
                                          ("Generic", "Generic File"),
                                          ("VISA", "VISA Statement"),
                                          ("Account", "Bank Account")])
    csv_file = forms.FileField(label="CSV File:")

    def clean(self):
        cleaned_data = super().clean()
        csv_type = cleaned_data.get("csv_type")

        if csv_type not in ("VISA", "Account", "Generic"):
            self.add_error("Expense Source", f"Source Value {csv_type} is not currently supported")


class ItemListForm(forms.ModelForm):
    #template_type = forms.ChoiceField(label="Type", required=False, choices=Template.CHOICES)
    #template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    class Meta:
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["date"].widget.attrs['style'] = 'width:95px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True

        self.fields["description"].widget.attrs['style'] = 'width:400px;background-color:Wheat'
        self.fields["description"].widget.attrs['readonly'] = True

        self.fields["amount"].widget.attrs['style'] = 'width:80px;background-color:Wheat'
        self.fields["amount"].widget.attrs['readonly'] = True


        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'

        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['class'] = 'diy-subcategory'

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Warning: Category {self.cleaned_data["category"]} missing subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subategory {self.cleaned_data["subcategory"]} missing Category.')


class ItemForm(forms.ModelForm):
    template_type = forms.ChoiceField(label="Type", required=False, choices=Template.CHOICES)
    template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    class Meta:
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore", "template_type", "template")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].widget.attrs['style'] = 'width:110px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True

        self.fields["description"].widget.attrs['style'] = 'width:400px;background-color:Wheat'
        self.fields["description"].widget.attrs['readonly'] = True

        self.fields["amount"].widget.attrs['style'] = 'width:100px;background-color:Wheat'
        self.fields["amount"].widget.attrs['readonly'] = True

        self.fields["template"].widget.attrs['style'] = 'width:400px;'
        self.fields["template"].widget.attrs['style'] = 'width:400px;'

        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'

        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'

    def clean_template(self):
        if self.cleaned_data["template"]:
            if self.cleaned_data["template_type"] == "contains":
                found = re.search(self.cleaned_data["template"], self.cleaned_data["description"])
            elif self.cleaned_data["template_type"] == "starts":
                found = self.cleaned_data["description"].startswith(self.cleaned_data["template"])
            elif self.cleaned_data["template_type"] == "ends":
                found = self.cleaned_data["description"].endswith(self.cleaned_data["template"])
            else:
                raise forms.ValidationError(f"Template Type not specified for template {self.cleaned_data['template']}")

            if not found:
                raise forms.ValidationError(
                    f'Template {self.cleaned_data["template"]} not found in description {self.cleaned_data["description"]}')

            if self.cleaned_data["ignore"]:
                template = Template.objects.create(expression=self.cleaned_data["template"],
                                                 type=self.cleaned_data["template_type"],
                                                 ignore=True)
            else:
                template = Template.objects.create(expression=self.cleaned_data["template"],
                                                   type=self.cleaned_data["template_type"],
                                                   category=self.cleaned_data["category"],
                                                   subcategory=self.cleaned_data["subcategory"])
            return template

    def xclean_category(self):
        if self.cleaned_data["category"] and "subcategory" not in self.cleaned_data:
            # self.cleaned_data["category"] = None
            raise forms.ValidationError('Subcategory required.')
        return self.cleaned_data["category"]

    def xclean_subcategory(self):
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(
                f'Subcategory {self.cleaned_data["subcategory"]} was selected without a Category')
        pass
        return self.cleaned_data["subcategory"]

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Warning: Category {self.cleaned_data["category"]} missing subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subategory {self.cleaned_data["subcategory"]} missing Category.')


class ClassifyItemForm(forms.Form):
    item = forms.CharField(label="Item Description", disabled=True)
    category = forms.ChoiceField()
