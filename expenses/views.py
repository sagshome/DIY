import copy
import csv
import logging
import pandas as pd
import plotly.io as pio
import plotly.graph_objects as go

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

from django.forms import modelformset_factory
from django.db.models import Q
from django.shortcuts import render, HttpResponseRedirect, reverse, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView

from expenses.forms import UploadFileForm, SearchForm
from base.utils import DIYImportException
from expenses.importers import Generic, CIBC_VISA, CIBC_Bank
from expenses.forms import CategoryForm, TemplateForm, ItemForm, ItemListForm, ItemAddForm
from expenses.models import Item, Category, SubCategory, Template, DEFAULT_CATEGORIES


logger = logging.getLogger(__name__)


def build_chart(items, filters):

    with_category = items.filter(category__isnull=False)
    without_category = items.filter(category__isnull=True)

    chart_type = 'Category'
    if filters and 'subcategory' in filters and filters['subcategory'] != '- ALL -':
        chart_type = 'Subcategory'

    df = pd.DataFrame.from_records(list(with_category.values(
        'date', 'category__name', 'subcategory__name', 'amount')))
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df['year_month'] = df['date'].dt.strftime('%Y-%m')

    blank_df = pd.DataFrame.from_records(list(without_category.values('date', 'amount')))
    if not blank_df.empty:
        blank_df['date'] = pd.to_datetime(blank_df['date'])
        blank_df['year_month'] = blank_df['date'].dt.strftime('%Y-%m')

    fig = go.Figure()
    if not blank_df.empty:
        fig.add_trace(go.Bar(
            x=blank_df['year_month'],
            y=blank_df['amount'],
            name='None',
            # text=subset_df['date'].dt.day,
            textposition='auto',
            orientation='v'
        ))

    if not df.empty:
        if chart_type == 'Category':
            for category in df['category__name'].unique():
                subset_df = df[df['category__name'] == category]
                fig.add_trace(go.Bar(
                    x=subset_df['year_month'],
                    y=subset_df['amount'],
                    name=category,
                    # text=subset_df['date'].dt.day,
                    textposition='auto',
                    orientation='v'
                ))
        else:
            for subcategory in df['subcategory__name'].unique():
                subset_df = df[df['category__name'] == subcategory]
                fig.add_trace(go.Bar(
                    x=subset_df['year_month'],
                    y=subset_df['amount'],
                    name=subcategory,
                    textposition='auto',
                    orientation='v'
                ))

    fig.update_layout(barmode='stack')
    fig.update_layout(title=chart_type, xaxis_title='Date', yaxis_title='Expenses')
    chart_html = pio.to_html(fig, full_html=False)
    return chart_html


class ItemAdd(LoginRequiredMixin, CreateView):
    model = Item
    form_class = ItemAddForm
    success_url = reverse_lazy('expense_main')

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        return context


class ItemDelete(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = 'expenses/item_confirm_delete.html'
    success_url = reverse_lazy('expense_main')


class ItemEdit(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    success_url = reverse_lazy('expense_main')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        return context


class AssignCategory(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    success_url = reverse_lazy("expense_upload")


class DeleteTemplateView(LoginRequiredMixin, DeleteView):
    model = Template
    template_name = 'expenses/template_confirm_delete.html'
    success_url = reverse_lazy("expenses_templates")


@login_required
def edit_template(request, pk: int):
    obj = get_object_or_404(Template, pk=pk)

    ItemFormSet = modelformset_factory(Item, form=ItemListForm, extra=0)
    template_form = TemplateForm(instance=obj)

    if request.method == "POST":
        formset = ItemFormSet(request.POST)
        if formset.is_valid():
            formset.save()
        if template_form.is_valid():
            template_form.save()
        return HttpResponseRedirect(reverse('expenses_templates'))

    formset = ItemFormSet(queryset=Item.objects.filter(template=obj))

    return render(request, "expenses/template.html", {
        'template_form': template_form,
        'formset': formset,
        'view_verb': 'Update',
        'me': obj,
    })


@login_required
def expense_main(request):
    """
    This view support both a search to refresh the data and pagination.   If I change the critera,   I need to
    reset the pagintor to page 1.
    """

    warnings = {}
    chart = None
    max_size = 50
    default = datetime.now().replace(year=datetime.now().year-7).date().replace(day=1)
    upload_error = None

    ItemFormSet = modelformset_factory(Item, form=ItemListForm, extra=0)
    search_form = SearchForm(initial={'search_ignore': 'No',
                                      'search_start_date': default,
                                      'show_list': 'Hide'})
    super_set = Item.objects.filter(ignore=False, date__gte=default).order_by('-date')

    if request.method == "POST":
        upload_form = UploadFileForm(request.POST)
        search_form = SearchForm(request.POST)
        formset = ItemFormSet(request.POST)
        if formset.is_valid():
            formset.save()
        if search_form.is_valid():
            super_set = Item.filter_search(Item.objects.all(), search_form.cleaned_data)
            chart = build_chart(super_set, search_form.cleaned_data)
    else:
        chart = build_chart(super_set, None)

    formset = ItemFormSet(queryset=Item.objects.filter(id__in=list(super_set.values_list('id', flat=True).order_by('-date')[:max_size])))
    upload_form = UploadFileForm()

    unassigned = Item.unassigned()
    if unassigned.count() != 0:
        warnings['Unassigned Expenses'] = f'{unassigned.count()} Expense Items have not been processed.'

    return render(request, "expenses/main.html", {
        'warnings': warnings,
        'formset': formset,
        'search_form': search_form,
        'upload_form': upload_form,
        'upload_error': upload_error,
        'chart': chart,
    })


@login_required
def templates(request):
    templates = Template.objects.all().order_by("expression")
    return render(request, 'expenses/templates.html',
                  {'templates': templates})


class AssignFormSet(modelformset_factory(Item, form=ItemForm, extra=0)):
    def save(self, commit=True):
        # Call the original save method to save the forms in the formset
        super(AssignFormSet, self).save(commit=commit)

        # Custom action (e.g., send an email notification)
        if commit:
            # Perform your custom action here
            pass


@login_required
def assign_expenses(request):

    max_size = 50
    search_form = SearchForm(initial={'search_ignore': 'No',
                                      'search_category': '- NONE -',
                                      'search_subcategory': '- NONE -'})

    super_set = Item.objects.filter(Q(category__isnull=True) | Q(subcategory__isnull=True)).exclude(
        ignore=True).order_by('-date').values_list('id', flat=True)

    if request.method == "POST":
        search_form = SearchForm(request.POST)
        formset = AssignFormSet(request.POST)
        if search_form.is_valid() and formset.is_valid():
            super_set = Item.filter_search(Item.objects.all(), search_form.cleaned_data)
            formset.save()
            Item.apply_templates()
            formset = AssignFormSet(queryset=Item.objects.filter(
                id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])))
    else:
        formset = AssignFormSet(queryset=Item.objects.filter(
            id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])))

    return render(request, "expenses/assign_category.html", {"formset": formset,
                                                             "search_form": search_form,
                                                             "count": super_set.count()})


@login_required
def upload_expenses(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            bin_file = form.cleaned_data["csv_file"].read()
            text_file = bin_file.decode("utf-8")
            reader = csv.reader(text_file.splitlines())
            try:
                if form.cleaned_data["csv_type"] == "Generic":
                    importer = Generic(reader, "Generic")
                elif form.cleaned_data["csv_type"] == 'CIBC_VISA':
                    importer = CIBC_VISA(reader, form.cleaned_data["csv_type"])
                elif form.cleaned_data["csv_type"] == 'CIBC_Bank':
                    importer = CIBC_Bank(reader, form.cleaned_data["csv_type"])
            except DIYImportException as e:
                return render(request, "expenses/uploadfile.html", {"form": form, "custom_error": str(e)})
            if Item.unassigned().count() > 0:
                return HttpResponseRedirect(reverse('expenses_assign'))
            return HttpResponseRedirect(reverse('expense_main'))

    form = UploadFileForm()
    return render(request, "expenses/uploadfile.html", {"form": form})


def load_subcategories(request):
    category = request.GET.get("category")
    if category:
        choices = SubCategory.objects.filter(category=category).order_by('name')
    else:
        choices = SubCategory.objects.none()
    return render(request, "expenses/subcategory_list_options.html", {"subcat": choices})


def load_subcategories_search(request):
    """
    This is complicated because sometimes the subcategory will come in as
    an ID,
    sometimes as a string and
    sometimes not at all
    """
    default = copy.copy(DEFAULT_CATEGORIES)
    search = SubCategory.objects.all()

    category = request.GET.get("category")
    if category and category not in ['- ALL -', '- NONE -']:
        search = search.filter(category__name=category)
    if category == '- NONE -':
        search = SubCategory.objects.none()

    for category in search.order_by('name').distinct().values_list('name', flat=True):
        default.append((category, category))

    return render(request, "expenses/search_options.html", {"options": default})


def load_categories_search(request):
    default = copy.copy(DEFAULT_CATEGORIES)
    for category in Category.objects.all().order_by("name").values_list('name', flat=True):
        default.append((category, category))
    return render(request, "expenses/search_options.html", {"options": default})


