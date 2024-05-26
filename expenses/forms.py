import copy
import re
from django import forms
from django.db.utils import ProgrammingError, OperationalError

from expenses.models import Item, SubCategory, Template, Category, DEFAULT_CATEGORIES


def get_categories():
    default = copy.copy(DEFAULT_CATEGORIES)
    try:
        for category in Category.objects.all().order_by("name").values_list('name', flat=True):
            default.append((category, category))
    except ProgrammingError:
        pass  #  Init with mysql
    except OperationalError:
        pass  # Init with mysql-lite
    return default


def get_subcategories():
    default = copy.copy(DEFAULT_CATEGORIES)
    try:
        for subcategory in SubCategory.objects.all().order_by("name").values_list('name', flat=True).distinct():
            default.append((subcategory, subcategory))
    except ProgrammingError:
        pass  # Init with mysql
    except OperationalError:
        pass  # Init with mysql-lite
    return default


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", )


class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ("category", "name", )


class SearchForm(forms.Form):
    """
    A form to support searching of expenses
    - Need to build a subcategory choice list so I can remove non-unique values
    """

    search_category = forms.ChoiceField(choices=get_categories())
    search_subcategory = forms.ChoiceField(choices=get_subcategories())
    """
    search_category = forms.ChoiceField(choices=DEFAULT_CATEGORIES)
    search_subcategory = forms.ChoiceField(choices=DEFAULT_CATEGORIES)
    """
    search_ignore = forms.ChoiceField(required=False, choices=[(None, '---'), ('Yes', 'Yes'), ('No', 'No')])
    search_start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    search_end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    search_amount_qualifier = forms.ChoiceField(label='', choices=[('gte', '>='), ('equal', '=='), ('lte', '<=')])
    search_amount = forms.DecimalField(required=False)
    search_description = forms.CharField(required=False, max_length=80)
    # view = forms.ChoiceField(choices=[('chart', 'Chart'), ('list', 'List'), ('both', 'Both')])
    # template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean



    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Adjusted to make W3C.CSS look nicer
        self.fields["search_amount"].widget.attrs['style'] = 'width:100px;height:28.5px;'
        self.fields["search_amount_qualifier"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["search_start_date"].widget.attrs['style'] = 'width:120px;height:28.5px;'
        self.fields["search_end_date"].widget.attrs['style'] = 'width:120px;height:28.5px;'
        self.fields["search_amount_qualifier"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["search_category"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["search_subcategory"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["search_ignore"].widget.attrs['style'] = 'height:28.5px;'

        self.fields["search_category"].widget.attrs['class'] = 'diy-search-category'  # Used in the search javascript
        self.fields["search_subcategory"].widget.attrs['class'] = 'diy-search-subcategory'


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
                                          ("CIBC_VISA", "CIBC VISA Download"),
                                          ("CIBC_Bank", "CIBC Bank Download")])
    csv_file = forms.FileField(label="CSV File:")

    def clean(self):
        cleaned_data = super().clean()
        csv_type = cleaned_data.get("csv_type")

        if csv_type not in ("CIBC_Bank", "CIBC_VISA", "Generic"):
            self.add_error("csv_type", f"Source Value {csv_type} is not currently supported")


class ItemListForm(forms.ModelForm):
    #template_type = forms.ChoiceField(label="Type", required=False, choices=Template.CHOICES)
    #template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    class Meta:
        model = Item
        fields = ("date", "amount", "description", "category", "subcategory", "ignore")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #self.fields["date"].widget.attrs['style'] = 'width:95px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True

        #self.fields["description"].widget.attrs['style'] = 'width:250px;background-color:Wheat'
        self.fields["description"].widget.attrs['readonly'] = True

        #self.fields["amount"].widget.attrs['style'] = 'width:80px;background-color:Wheat'
        self.fields["amount"].widget.attrs['readonly'] = True


        self.fields["category"].widget.attrs['class'] = 'item-list-category'  # Used in the search javascript
        #self.fields["category"].widget.attrs['style'] = 'width:125px;'

        #self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['class'] = 'item-list-subcategory'

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Warning: Category {self.cleaned_data["category"]} missing subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subategory {self.cleaned_data["subcategory"]} missing Category.')


class ItemAddForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ("user", "date", "description", "amount", "category", "subcategory", "ignore")
        widgets = {
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["date"].widget.attrs['type'] = 'date'  # todo: Fix this a) gives a format hint or b) uses a picker
        self.fields["description"].widget.attrs['style'] = 'width:400px;'
        self.fields["amount"].widget.attrs['style'] = 'width:100px;'
        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'


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

        self.fields['ignore'].label = "Hide"

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

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Warning: Category {self.cleaned_data["category"]} missing subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subategory {self.cleaned_data["subcategory"]} missing Category.')


class SingleItemForm(ItemForm):

    direction_choices = ((None, '----'),
                         ('forward', 'future'),
                         ('backward', 'back'),
                         ('around', 'split'))

    direction = forms.ChoiceField(required=False, choices=direction_choices)
    months = forms.IntegerField(min_value=2, required=False)


class ClassifyItemForm(forms.Form):
    item = forms.CharField(label="Item Description", disabled=True)
    category = forms.ChoiceField()
