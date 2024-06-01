import copy
import csv
import logging
import pandas as pd
import plotly.io as pio
import plotly.graph_objects as go

from datetime import datetime
from dateutil import relativedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

from django.forms import modelformset_factory
from django.db.models import Q, Sum
from django.shortcuts import render, HttpResponseRedirect, reverse, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView, FormView
from django.http import JsonResponse
from django.db.models.functions import TruncMonth

from base.models import COLORS
from base.utils import DIYImportException
from expenses.importers import Generic, CIBC_VISA, CIBC_Bank, PersonalCSV
from expenses.forms import *
from expenses.models import Item, Category, SubCategory, Template, DEFAULT_CATEGORIES


logger = logging.getLogger(__name__)



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
    form_class = ItemEditForm
    success_url = reverse_lazy('expense_main')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        if self.object.parent:
            context['children'] = self.object.parent.all()

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


class ItemFormSet(modelformset_factory(Item, form=ItemListForm, extra=0)):
    def save(self, commit=True):
        # Call the original save method to save the forms in the formset
        super(ItemFormSet, self).save(commit=commit)

        # Custom action (e.g., send an email notification)
        if commit:
            # Perform your custom action here
            pass


@login_required
def expense_main(request):
    """
    This view support both a search to refresh the data and pagination.   If I change the critera,   I need to
    reset the pagintor to page 1.
    """

    warnings = {}
    default_end = datetime.now().date()
    default_start = datetime.now().replace(year=datetime.now().year-7).date().replace(day=1)

    max_size = 50
    search_form = SearchForm(initial={'search_ignore': 'No',
                                      'search_start_date': default_start,
                                      'search_end_date': default_end,
                                      'show_list': 'Hide'})

    if request.method == "POST":
        search_form = SearchForm(request.POST)
        formset = ItemFormSet(request.POST)
        if search_form.is_valid() and formset.is_valid():
            super_set = Item.filter_search(Item.objects.filter(user=request.user), search_form.cleaned_data)
            total = super_set.aggregate(Sum('amount'))['amount__sum']
            formset.save()
            formset = ItemFormSet(queryset=Item.objects.filter(
                id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])))

    else:
        super_set = Item.objects.filter(
            ignore=False, user=request.user, date__gte=default_start, date__lte=default_end).order_by('-date')
        total = super_set.aggregate(Sum('amount'))['amount__sum']
        formset = ItemFormSet(queryset=Item.objects.filter(
            id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])))

    unassigned = Item.unassigned()
    if unassigned.count() != 0:
        warnings = f'{unassigned.count()} Expense Items have not been processed.'

    return render(request, "expenses/main.html", {
        'warnings': warnings,
        'formset': formset,
        'search_form': search_form,
        'total': total,
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

    basic_filter = Item.objects.filter(Q(category__isnull=True) | Q(subcategory__isnull=True)).exclude(ignore=True)
    count = basic_filter.count()
    if request.method == "POST":
        search_form = SearchForm(request.POST)
        formset = AssignFormSet(request.POST)
        if search_form.is_valid() and formset.is_valid():
            formset.save()
            Item.apply_templates()
            filtered_set = Item.filter_search(basic_filter, search_form.cleaned_data)
            count = filtered_set.count()
            queryset = Item.objects.filter(id__in=list(filtered_set.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date')
            formset = AssignFormSet(queryset=queryset)
    else:
        queryset = Item.objects.filter(id__in=list(basic_filter.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date')
        formset = AssignFormSet(queryset=queryset)

    return render(request, "expenses/assign_category.html", {"formset": formset,
                                                             "search_form": search_form,
                                                             "count": count})


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
                    importer = Generic(reader,  request.user, "Generic")
                elif form.cleaned_data["csv_type"] == 'CIBC_VISA':
                    importer = CIBC_VISA(reader, request.user, form.cleaned_data["csv_type"])
                elif form.cleaned_data["csv_type"] == 'CIBC_Bank':
                    importer = CIBC_Bank(reader, request.user, form.cleaned_data["csv_type"])
                elif form.cleaned_data["csv_type"] == 'Personal':
                    importer = PersonalCSV(reader, request.user, form.cleaned_data["csv_type"])
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


@login_required
def expense_pie(request):
    data = []
    labels = []
    super_set = Item.filter_search(Item.objects.filter(user=request.user), request.GET)
    category_list = super_set.order_by('category__name').values_list('category__name', flat=True).distinct()
    for category in category_list:
        item = super_set.filter(category__name=category).aggregate(sum=Sum('amount'))
        labels.append(category)
        value = int(item['sum'])
        data.append(value)
    return JsonResponse({'data': data, 'labels': labels, 'colors': COLORS})


@login_required
def expense_bar(request):
    """
    Build the chart.js data for a bar chart based on the standard search_filter
    """

    super_set = Item.filter_search(Item.objects.filter(user=request.user), request.GET)
    show_sub = False if request.GET['search_category'] == '- ALL -' else True

    if super_set.count() == 0:
        return JsonResponse({'datasets': [], 'labels': []})

    first_date = super_set.earliest('date').date.replace(day=1)
    last_date = super_set.latest('date').date.replace(day=1)

    months = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta.relativedelta(months=1)

    if show_sub:
        raw_data = super_set.annotate(month=TruncMonth('date')).values('month').annotate(sum=Sum('amount')).values('month',
                                                                                                             'sum',
                                                                                                             'subcategory__name')
    else:
        raw_data = super_set.annotate(month=TruncMonth('date')).values('month').annotate(sum=Sum('amount')).values('month',
                                                                                                             'sum',
                                                                                                             'category__name')

    colors = COLORS.copy()
    colors.reverse()

    initial_data = [0 for i in range(len(months))]
    datasets = []

    data_dict = {}
    for element in raw_data:
        name = element['subcategory__name'] if show_sub else element['category__name']
        this_date = element['month']
        if name not in data_dict:
            datasets.append({'label': name,
                             'data': initial_data.copy(),
                             'backgroundColor': colors.pop()})
            data_dict[name] = len(datasets) - 1
        try:
            datasets[data_dict[name]]['data'][month_dict[element['month']]] += element['sum']
        except KeyError:
            print(f'Failed on:{element}')

    return JsonResponse({'datasets': datasets, 'labels': months, 'colors': COLORS})
