import copy
import os
import re
from django import forms
from django.forms import formset_factory
from django.db.models import Q
from django.db.utils import ProgrammingError, OperationalError

from expenses.models import Item, SubCategory, Template, Category, DEFAULT_CATEGORIES
from expenses.importers import DEFAULT, EXTRA


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


class SubCategoryForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ("category", "name", "user")
        widgets = {
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        # Adjusted to make W3C.CSS look nicer
        self.fields["category"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["name"].widget.attrs['style'] = 'height:28.5px;'

    def clean_name(self):
        category = self.cleaned_data['category']
        name = self.cleaned_data['name'].capitalize()
        if SubCategory.objects.filter(category=category, name=name).filter(Q(user__isnull=True) | Q(user_id=self.initial['user'])).exists():
            raise forms.ValidationError('This subcategory already exists')
        return name


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

    def __init__(self, *args, **kwargs):  # pragma: no cover
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

    class Meta:  # pragma: no cover
        model = Template
        fields = ("user", "type", "expression",  "category", "subcategory", "ignore")

        widgets = {
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.fields["type"].widget.attrs['style'] = 'width:110px;'
        self.fields["expression"].widget.attrs['style'] = 'width:400px;'
        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['class'] = 'diy-subcategory'  # Used in the search javascript

    def clean_expression(self):
        if self.cleaned_data['expression'].find('$') != -1:
            raise forms.ValidationError('Expression can not contain a "$" character')

        if not Template.test_expression(self.cleaned_data['type'], self.initial['expression'],  self.cleaned_data['expression']):
            raise forms.ValidationError(
                f"Expression {self.cleaned_data['expression']} is not valid with \"{Template.choice(self.cleaned_data['type'])}\"  {self.initial['expression']}")

        return self.cleaned_data['expression']

    def clean_subcategory(self):
        if not self.cleaned_data['subcategory']:
            if self.cleaned_data['category']:
                raise forms.ValidationError('A subcategory is required if you enter a category')
        return self.cleaned_data['subcategory']

    def clean_category(self):
        if not self.cleaned_data['category']:
            if "subcategory" in self.cleaned_data:
                raise forms.ValidationError('A category is required if you enter a subcategory')
        return self.cleaned_data['category']

    def clean_ignore(self):
        if self.cleaned_data['ignore']:
            if self.cleaned_data['category']:
                raise forms.ValidationError('You can not Ignore a record if you have supplied a category')
        return self.cleaned_data['ignore']

    def clean(self):
        ignore = self.cleaned_data['ignore'] if 'ignore' in self.cleaned_data else False
        if not ignore and not self.cleaned_data['category']:
            raise forms.ValidationError('A template must specify "Ignore" or a Category/Subcategory pair')

        return self.cleaned_data


class UploadColumnForm(forms.Form):

    heading = forms.ChoiceField(choices=tuple(list({'ignore': '-----'}.items()) + list(DEFAULT.items()) + list(EXTRA.items())))

    example0 = forms.CharField(required=False, max_length=64)
    example1 = forms.CharField(required=False, max_length=64)
    example2 = forms.CharField(required=False, max_length=64)
    example3 = forms.CharField(required=False, max_length=64)
    example4 = forms.CharField(required=False, max_length=64)

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.fields["heading"].widget.attrs['style'] = 'width:200px;height:27px'

        self.fields["example0"].widget.attrs['style'] = 'width:200px;background-color:Wheat'
        self.fields["example0"].widget.attrs['readonly'] = True
        self.fields["example1"].widget.attrs['style'] = 'width:200px;background-color:Wheat'
        self.fields["example1"].widget.attrs['readonly'] = True
        self.fields["example2"].widget.attrs['style'] = 'width:200px;background-color:Wheat'
        self.fields["example2"].widget.attrs['readonly'] = True
        self.fields["example3"].widget.attrs['style'] = 'width:200px;background-color:Wheat'
        self.fields["example3"].widget.attrs['readonly'] = True
        self.fields["example4"].widget.attrs['style'] = 'width:200px;background-color:Wheat'
        self.fields["example4"].widget.attrs['readonly'] = True


class UploadFileForm(forms.Form):
    has_headings = forms.TypedChoiceField(coerce=lambda x: x == 'True', choices=((False, 'No'), (True, 'Yes')))
    upload_file = forms.FileField(label="Expenses File:")

    def clean_upload_file(self):
        cleaned_file = self.cleaned_data["upload_file"]
        file_ext = os.path.splitext(cleaned_file.name)[1]
        if file_ext not in ('.csv', '.ods', '.xls', '.xlsx'):
            raise forms.ValidationError(f'Warning: file type {file_ext} is not supported.')
        return cleaned_file


class BaseItemForm(forms.ModelForm):
    """
    All Item Forms have these fields so let treat them consistantly
    """

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.fields["date"].widget.attrs['style'] = 'width:95px;background-color:Wheat'
        self.fields["date"].widget.attrs['readonly'] = True

        self.fields["description"].widget.attrs['style'] = 'width:500px;background-color:LightBlue'
        self.fields["description"].widget.attrs['readonly'] = True

        self.fields["amount"].widget.attrs['style'] = 'width:80px;background-color:Wheat'
        self.fields["amount"].widget.attrs['readonly'] = True
        self.fields["amount"].widget.attrs['class'] = 'w3-right-align'

        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search javascript
        self.fields["subcategory"].widget.attrs['class'] = 'diy-subcategory'  # Used in the search javascript

        if "ignore" in self.fields:
            self.fields["ignore"].label = 'Hidden'


class ItemListEditForm(BaseItemForm):
    is_split = forms.BooleanField(required=False, label='Split')
    is_amortized = forms.BooleanField(required=False, label='Leveled')
    # amortized_expense = forms.BooleanField()

    class Meta:  # pragma: no cover
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore", "is_split", "is_amortized",
                  "notes")
        widgets = {
          'notes': forms.Textarea(attrs={'rows':1, 'cols':15}),
        }

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        if self.instance.is_split:
            self.fields['is_split'].initial = True
        else:
            self.fields['is_split'].initial = False
        self.fields["is_split"].widget.attrs['disabled'] = 'disabled'

        if self.instance.is_amortized:
            self.fields['is_amortized'].initial = True
        else:
            self.fields['is_amortized'].initial = False
        self.fields["is_amortized"].widget.attrs['disabled'] = 'disabled'

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Error: Category {self.cleaned_data["category"]} missing Subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Error: Subcategory {self.cleaned_data["subcategory"]} missing Category.')


class ItemAddForm(BaseItemForm):
    class Meta:
        model = Item
        fields = ("user", "date", "description", "amount", "category", "subcategory", "ignore")
        widgets = {
            'user': forms.HiddenInput(),
            'date': forms.TextInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.fields["date"].widget.attrs['style'] = 'width:95px;'
        self.fields["date"].widget.attrs['readonly'] = False

        self.fields["description"].widget.attrs['style'] = 'width:500px;'
        self.fields["description"].widget.attrs['readonly'] = False

        self.fields["amount"].widget.attrs['style'] = 'width:80px;'
        self.fields["amount"].widget.attrs['readonly'] = False
        self.fields["amount"].widget.attrs['class'] = 'w3-right-align'


class ItemEditForm(BaseItemForm):
    amortize_type = forms.ChoiceField(required=False, choices=(('backward', 'Past - Historic Savings'),
                                                                             ('forward', 'Future budget item'),
                                                                             ('around', 'Split expense around the date')))
    amortize_months = forms.IntegerField(required=False)
    s_amount = forms.DecimalField(required=False)
    s_description = forms.CharField(required=False)


    class Meta:  # pragma: no cover
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore",
                  "amortize_months", "amortize_type", "s_amount", "s_description", "notes")

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.fields["amortize_months"].widget.attrs['style'] = 'width:100px;'
        self.fields["s_amount"].widget.attrs['style'] = 'width:100px;'
        self.fields["s_description"].widget.attrs['style'] = 'width:400px;'

    def clean(self):
        super().clean()
        if self.cleaned_data["category"] and not self.cleaned_data["subcategory"]:
            raise forms.ValidationError(f'Warning: Category {self.cleaned_data["category"]} missing subcategory.')
        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subategory {self.cleaned_data["subcategory"]} missing Category.')

        if self.cleaned_data["amortize_months"] and self.cleaned_data["amortize_months"] != 0:
            if self.instance.amortized:
                raise forms.ValidationError(
                    f'Error: this item is already amortized')
            self.instance.amortize(self.cleaned_data["amortize_months"], direction=self.cleaned_data["amortize_type"])
            self.cleaned_data["ignore"] = True
        else:
            if self.instance.parent and self.cleaned_data["amortize_months"] == 0:
                self.instance.deamortize()
                self.cleaned_data["ignore"] = False

        if self.cleaned_data["s_amount"]:
            if self.instance.was_split:
                raise forms.ValidationError(
                    f'Error: this item is already split')

            result = self.instance.split_item(self.cleaned_data["s_amount"], self.cleaned_data["s_description"])
            if result:
                raise forms.ValidationError(result)
            self.cleaned_data["ignore"] = True


class ItemForm(BaseItemForm):

    #template_type = forms.ChoiceField(label="Type", required=False, choices=Template.CHOICES)
    #template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    class Meta:  # pragma: no cover
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore")  # "template_type", "template")

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
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
