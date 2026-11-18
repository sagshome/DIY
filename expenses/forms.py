import copy
import os
import re

from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from django.db.models import Q
from django.db.utils import ProgrammingError, OperationalError

from base.mixins import BootstrapFormMixin
from expenses.models import Item, SubCategory, ItemTag, Template, Category, DEFAULT_CATEGORIES
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
    default.append(('- ANY -', '- ANY -'))
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
        widgets = {'user': forms.HiddenInput()}

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.user = user

        # Adjusted to make W3C.CSS look nicer
        self.fields["category"].widget.attrs['style'] = 'height:28.5px;'
        self.fields["name"].widget.attrs['style'] = 'height:28.5px;'

    def clean_name(self):
        category = self.cleaned_data['category']
        name = self.cleaned_data['name'].capitalize()
        if (
            SubCategory.objects.exclude(pk=self.instance.pk)
            .filter(category=category, name=name)
            .filter(Q(user__isnull=True) | Q(user=self.user))
            .exists()
        ):
            raise forms.ValidationError('This subcategory already exists')
        return name


class BaseSubCategoryFormSet(BaseModelFormSet):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["user"] = self.user
        return kwargs

    def save_new(self, form, commit=True):
        form.instance.user = self.user
        return super().save_new(form, commit=commit)


SubCategoryFormSet = modelformset_factory(
    SubCategory,
    form=SubCategoryForm,
    formset=BaseSubCategoryFormSet,
    extra=1,
    can_delete=True,
)


class TagForm(forms.ModelForm):
    class Meta:
        model = ItemTag
        fields = ("value", "user")
        widgets = {
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.user = user

        # Adjusted to make W3C.CSS look nicer
        self.fields["value"].widget.attrs['style'] = 'height:28.5px;'

    def clean_value(self):
        value = self.cleaned_data['value']
        if ItemTag.objects.exclude(pk=self.instance.pk).filter(value=value, user=self.user).exists():
            raise forms.ValidationError('This Tag already exists')
        return value


class BaseTagFormSet(BaseModelFormSet):
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["user"] = self.user
        return kwargs

    def save_new(self, form, commit=True):
        form.instance.user = self.user
        return super().save_new(form, commit=commit)


TagFormSet = modelformset_factory(
    ItemTag,
    form=TagForm,
    formset=BaseTagFormSet,
    extra=1,
    can_delete=True,
)


class SearchForm(forms.Form):
    """
    A form to support searching of expenses
    - Need to build a subcategory choice list so I can remove non-unique values
    """

    search_category = forms.ChoiceField(required=False, choices=get_categories())
    search_subcategory = forms.ChoiceField(required=False, choices=get_subcategories())
    """
    search_category = forms.ChoiceField(choices=DEFAULT_CATEGORIES)
    search_subcategory = forms.ChoiceField(choices=DEFAULT_CATEGORIES)
    """
    search_ignore = forms.ChoiceField(required=False, choices=[(None, '---'), ('Yes', 'Yes'), ('No', 'No')])
    search_start_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    search_end_date = forms.DateField(required=False, widget=forms.TextInput(attrs={'type': 'date'}))
    search_amount_qualifier = forms.ChoiceField(required=False, label='', choices=[('gte', '>='), ('equal', '=='), ('lte', '<=')])
    search_amount = forms.DecimalField(required=False)
    search_description = forms.CharField(required=False, max_length=80)
    range = forms.CharField(required=False, max_length=16)
    month = forms.CharField(required=False, max_length=16)

    # view = forms.ChoiceField(choices=[('chart', 'Chart'), ('list', 'List'), ('both', 'Both')])
    # template = forms.CharField(max_length=50, required=False)  # Change to a real template in clean

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.fields["search_category"].widget.attrs['class'] = 'diy-search-category'  # Used in the search JavaScript
        self.fields["search_subcategory"].widget.attrs['class'] = 'diy-search-subcategory'


class TemplateForm(BootstrapFormMixin, forms.ModelForm):

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
        self.fields["category"].widget.attrs['class'] = 'diy-category'  # Used in the search JavaScript
        self.fields["category"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['style'] = 'width:125px;'
        self.fields["subcategory"].widget.attrs['class'] = 'diy-subcategory'  # Used in the search JavaScript

    def clean_expression(self):
        if self.cleaned_data['expression'].find('$') != -1:
            raise forms.ValidationError('Expression can not contain the "$" character')

        if 'type' not in self.cleaned_data:
            raise forms.ValidationError('An expression type must be selected')

        if not Template.test_expression(self.cleaned_data['type'], self.initial['expression'],  self.cleaned_data['expression']):
            raise forms.ValidationError(
                f"Expression {self.cleaned_data['expression']} is not valid with \"{Template.choice(self.cleaned_data['type'])}\"  {self.initial['expression']}")

        return self.cleaned_data['expression']

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


class UploadColumnForm(BootstrapFormMixin, forms.Form):

    heading = forms.ChoiceField(choices=tuple(list({'ignore': '-----'}.items()) + list(DEFAULT.items()) + list(EXTRA.items())))

    example0 = forms.CharField(required=False, max_length=128)
    example1 = forms.CharField(required=False, max_length=128)
    example2 = forms.CharField(required=False, max_length=128)
    example3 = forms.CharField(required=False, max_length=128)
    example4 = forms.CharField(required=False, max_length=128)
    example5 = forms.CharField(required=False, max_length=128)
    example6 = forms.CharField(required=False, max_length=128)
    example7 = forms.CharField(required=False, max_length=128)
    example8 = forms.CharField(required=False, max_length=128)
    example9 = forms.CharField(required=False, max_length=128)

    def __init__(self, *args, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        ch_size = 22
        try:
            longest_value = max(self.initial.values(), key=len)
            if isinstance(longest_value, str):
                longest_value = len(longest_value)
                ch_size = longest_value if longest_value > 22 else 22
        except TypeError:
            pass  # Non string,  use default of ch_size
        except ValueError:
            pass

        self.fields["heading"].widget.attrs['style'] = f'width:{ch_size}ch'  # To fit -> Debit (Out of account)
        for index in range(10):
            self.fields[f"example{index}"].widget.attrs['style'] = f'width:{ch_size}ch;background-color:Wheat'
            self.fields[f"example{index}"].widget.attrs['readonly'] = True


class UploadFileForm(BootstrapFormMixin, forms.Form):
    has_headings = forms.TypedChoiceField(coerce=lambda x: x == 'True', choices=((False, 'No'), (True, 'Yes')))
    upload_file = forms.FileField(label="Expenses File:")

    def clean_upload_file(self):
        cleaned_file = self.cleaned_data["upload_file"]
        file_ext = os.path.splitext(cleaned_file.name)[1]
        if file_ext not in ('.csv', '.ods', '.xls', '.xlsx'):
            raise forms.ValidationError(f'Warning: file type {file_ext} is not supported.')
        return cleaned_file


class BaseItemForm(BootstrapFormMixin, forms.ModelForm):
    """
    All Item Forms have these fields so let treat them consistently
    """
    pass


class ItemListEditForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ("category", "subcategory", "ignore", "notes")
        widgets = {
            "notes": forms.TextInput(),
        }

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.user = user
        self.fields["category"].widget.attrs['class'] += ' diy-category'  # Used in the search JavaScript
        self.fields["subcategory"].widget.attrs['class'] += ' diy-subcategory'  # Used in the search JavaScript

        if self.is_bound:
            category_id = self.data.get("category")
        else:
            category_id = self.instance.category_id if self.instance.pk else None

        self.fields["subcategory"].queryset = (
            SubCategory.objects.filter(category_id=category_id).filter(Q(user__isnull=True) | Q(user=self.user))
            if category_id
            else SubCategory.objects.none()
        )


class ItemAddForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ("user", "date", "description", "amount", "category", "subcategory", "ignore", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2, "style": "resize: none; overflow-y: auto;"}),
            "date": forms.TextInput(attrs={"type": "date"}),
            'user': forms.HiddenInput(),
        }

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.user = user

        if self.is_bound:
            category_id = self.data.get("category")
        else:
            category_id = self.instance.category_id if self.instance.pk else None

        self.fields["subcategory"].queryset = (
            SubCategory.objects.filter(category_id=category_id).filter(Q(user__isnull=True) | Q(user=self.user))
            if category_id
            else SubCategory.objects.none()
        )

        self.fields["category"].widget.attrs['class'] += ' diy-category'  # Used in the search JavaScript
        self.fields["subcategory"].widget.attrs['class'] += ' diy-subcategory'  # Used in the search JavaScript

class ItemAmortizeForm(BootstrapFormMixin, forms.Form):

    choices = (
        ('backward', 'Backward'),
        ('forward', 'Forward'),
        ('around', 'Around'),
    )
    direction = forms.ChoiceField(choices=choices, label='How to amortize', help_text="Backward, over previous months,  Forward for later months,  Around both before and after")
    periods = forms.IntegerField(label='Num. of Periods', min_value=2, required=False, help_text="Choose how many months this should be amortized over")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

class ItemSplitForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ("date", "description", "amount", "category", "subcategory", "ignore", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2, "style": "resize: none; overflow-y: auto;"}),
            "date": forms.TextInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)
        self.user = user
        if self.is_bound:
            category_id = self.data.get("category")
        else:
            category_id = self.instance.category_id if self.instance.pk else None

        self.fields["subcategory"].queryset = (
            SubCategory.objects.filter(category_id=category_id).filter(Q(user__isnull=True) | Q(user=self.user))
            if category_id
            else SubCategory.objects.none()
        )


    def clean_amount(self):
        """
        You can split 100% of a record,   which would leave the other record at 0,  that gives you the opportunity
        to rename description and change date.   I added this in as a feature not a bug
        """
        if self.cleaned_data['amount'] < 0 or self.cleaned_data['amount'] > self.instance.amount:
            raise forms.ValidationError("Amount must be greater then 0 and not more then the original amount")
        return self.cleaned_data['amount']

    def clean_date(self):
        if self.cleaned_data['date'] > self.instance.date:
            raise forms.ValidationError("Date can not be later then the original value")
        return self.cleaned_data['date']


class ItemEditForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Item
        fields = ("category", "subcategory", "ignore", "notes")
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2, "style": "resize: none; overflow-y: auto;"}),
        }

    def __init__(self, *args, user=None, **kwargs):  # pragma: no cover
        super().__init__(*args, **kwargs)

        self.user = user
        self.fields["category"].widget.attrs['class'] += ' diy-category'  # Used in the search JavaScript
        self.fields["subcategory"].widget.attrs['class'] += ' diy-subcategory'  # Used in the search JavaScript

        if self.is_bound:
            category_id = self.data.get("category")
        else:
            category_id = self.instance.category_id if self.instance.pk else None

        self.fields["subcategory"].queryset = (
            SubCategory.objects.filter(category_id=category_id).filter(Q(user__isnull=True) | Q(user=self.user))
            if category_id
            else SubCategory.objects.filter(Q(user__isnull=True) | Q(user=self.user))
        )


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

        if self.cleaned_data["subcategory"] and not self.cleaned_data["category"]:
            raise forms.ValidationError(f'Warning: Subcategory {self.cleaned_data["subcategory"]} missing Category.')

