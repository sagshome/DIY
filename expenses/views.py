import copy
import csv
import logging
import numpy as np
import os
import pandas as pd
import uuid

from datetime import datetime
from dateutil import relativedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear
from django.forms import modelformset_factory, formset_factory
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, HttpResponseRedirect, reverse, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView, FormView, ListView

from base.models import COLORS, PALETTE
from base.utils import DateUtil, label_to_values, date_to_label, set_simple_cache, load_dataframe
from base.views import BaseDeleteView
from expenses.importers import import_dataframe, find_headers_errors
from expenses.forms import SubCategoryForm, ItemForm, ItemAddForm, ItemEditForm, TemplateForm, ItemListEditForm, SearchForm, UploadFileForm, UploadColumnForm
from expenses.models import Item, Category, SubCategory, Template, DEFAULT_CATEGORIES

logger = logging.getLogger(__name__)


class SubCategoryAdd(LoginRequiredMixin, CreateView):
    model = SubCategory
    form_class = SubCategoryForm
    template_name = 'expenses/subcategory.html'

    def get_success_url(self):
        try:
            url = self.request.POST["success_url"]
        except KeyError:
            url = reverse('expense_main')
        return url

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.user = self.request.user
        self.object.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['success_url'] = self.request.META.get('HTTP_REFERER', '/')
        return context


class SubCategoryDelete(BaseDeleteView):
    model = SubCategory

    def get_object(self, queryset=None):
        return super().get_object(queryset=SubCategory.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object_type'] = 'SubCategory'
        context['extra_text'] = 'Deleting a SubCategory is permanent - All assignments will be removed.'
        return context


class SubCategoryList(LoginRequiredMixin, ListView):
    model = SubCategory

    def get_queryset(self):
        return SubCategory.objects.filter(user=self.request.user).order_by('category__name', 'name')


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
        context['help_file'] = "expenses/help/item.html"

        return context


class ItemDelete(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = 'expenses/item_confirm_delete.html'
    success_url = reverse_lazy('expense_main')

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))


class ItemEdit(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemEditForm
    success_url = reverse_lazy('expense_main')

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Edit'
        if self.object.parent:
            context['children'] = self.object.parent.all()

        if self.object.split_from:
            context['split_from'] = self.object.split_from.all()
        context['help_file'] = "expenses/help/item.html"
        return context


class AssignCategory(LoginRequiredMixin, UpdateView):
    model = Item
    form_class = ItemForm
    success_url = reverse_lazy("expense_upload")


class ListTemplates(LoginRequiredMixin, ListView):
    model = Template
    template_name = 'expenses/templates.html'

    def get_queryset(self):
        return Template.objects.filter(user=self.request.user).order_by('-count')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class AddTemplateView(LoginRequiredMixin, CreateView):
    model = Template
    form_class = TemplateForm
    success_url = reverse_lazy('expenses_assign')
    template_name = 'expenses/template_form.html'

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        item: Item = Item.objects.get(id=self.kwargs['item_pk'])
        self.initial['expression'] = item.description
        self.initial['category'] = item.category
        self.initial['subcategory'] = item.subcategory
        self.initial['ignore'] = item.ignore
        return self.initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Create'
        return context


class DeleteTemplateView(LoginRequiredMixin, DeleteView):
    model = Template
    template_name = 'expenses/template_confirm_delete.html'
    success_url = reverse_lazy("expenses_templates")


class ItemFormSet(modelformset_factory(Item, form=ItemListEditForm, extra=0)):
    def save(self, commit=True):
        # Call the original save method to save the forms in the formset
        super(ItemFormSet, self).save(commit=commit)

        # Custom action (e.g., send an email notification)
        if commit:
            # Perform your custom action here
            pass

@login_required
def edit_template(request, pk: int):
    obj = get_object_or_404(Template, pk=pk)

    # ItemFormSet = modelformset_factory(Item, form=ItemListEditForm, extra=0)
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


def cash_help(request):
    return render(request, 'expenses/includes/help.html', {'success_url': request.META.get('HTTP_REFERER', '/')})


@login_required
def expense_main(request):
    """
    This view support both a search to refresh the data and pagination.   If I change the critera,   I need to
    reset the pagintor to page 1.
    """
    search_for = False
    default_end = datetime.now().date()
    default_start = datetime.now().replace(year=datetime.now().year - 7).date().replace(day=1)

    if request.GET:
        if 'span' in request.GET:
            new_start, new_end = label_to_values(request.GET['span'])
            if new_start:  # Just incase the data was ill formatted ?
                default_start = new_start
                default_end = new_end

        if 'category' in request.GET:
            try:
                search_for = Category.objects.get(name=request.GET['category'])
            except Category.DoesNotExist:
                logger.error('Intial Category does not exist:%s' % request.GET['category'])

    initial = {'search_ignore': 'No',
               'search_start_date': default_start,
               'search_end_date': default_end,
               'show_list': 'Hide'}

    if search_for:
        initial['search_category'] = search_for.name

    warnings = {}
    max_size = 50
    search_form = SearchForm(initial=initial)

    total = 0
    if request.method == "POST":
        search_form = SearchForm(request.POST)
        formset = ItemFormSet(request.POST)
        if search_form.is_valid() and formset.is_valid():
            search_dict = search_form.cleaned_data
            search_dict['income'] = 'true' if search_dict['search_category'] == 'Income' else 'false'
            super_set = Item.filter_search(Item.objects.filter(user=request.user), search_form.cleaned_data).order_by('-date')
            total = super_set.aggregate(Sum('amount'))['amount__sum']
            formset.save()
            formset = ItemFormSet(queryset=Item.objects.filter(
                id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date'))
        else:
            pass

    else:

        super_set = Item.objects.filter(
            ignore=False, user=request.user, date__gte=default_start, date__lte=default_end).order_by('-date')
        if search_for:
            super_set = super_set.filter(category=search_for)
            total = super_set.aggregate(Sum('amount'))['amount__sum']
            formset = ItemFormSet(queryset=Item.objects.filter(
                id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date'))
        else:
            total = super_set.aggregate(Sum('amount'))['amount__sum']
            formset = ItemFormSet(queryset=Item.objects.filter(
                id__in=list(super_set.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date'))

    unassigned = Item.unassigned(user=request.user)
    if unassigned.count() != 0:
        warnings = f'{unassigned.count()} Expense Items have not been processed.'

    return render(request, "expenses/main.html", {
        'warnings': warnings,
        'formset': formset,
        'search_form': search_form,
        'total': total,
        'help_file': 'expenses/help/main.html'
    })


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
    Item.apply_templates(user=request.user)
    max_size = 50

    search_form = SearchForm(initial={'search_ignore': 'No',
                                      'search_category': '- NONE -',
                                      'search_subcategory': '- NONE -'})

    basic_filter = Item.objects.filter(user=request.user).filter(Q(category__isnull=True) | Q(subcategory__isnull=True)).exclude(ignore=True)
    count = basic_filter.count()
    if request.method == "POST":
        search_form = SearchForm(request.POST)
        formset = AssignFormSet(request.POST)
        if search_form.is_valid() and formset.is_valid():
            formset.save()
            if "submit-type" in request.POST and request.POST["submit-type"].startswith('Template-'):
                index = request.POST["submit-type"].split('Template-')
                if index[1]:
                    return HttpResponseRedirect(reverse('add_template', kwargs={'item_pk': index[1]}))

            filtered_set = Item.filter_search(basic_filter, search_form.cleaned_data)
            count = filtered_set.count()
            queryset = Item.objects.filter(id__in=list(filtered_set.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date')
            formset = AssignFormSet(queryset=queryset)
    else:
        queryset = Item.objects.filter(id__in=list(basic_filter.order_by('-date').values_list('id', flat=True)[:max_size])).order_by('-date')
        formset = AssignFormSet(queryset=queryset)

    return render(request, "expenses/assign_category.html", {"formset": formset,
                                                             "search_form": search_form,
                                                             "count": count,
                                                             "help_file": "expenses/help/assign_category.html"})


@login_required
def upload_expenses(request):
    """
    UploadFileForm - Insures that file type matches.
    """
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            upload_file = form.cleaned_data["upload_file"]
            file_ext = os.path.splitext(upload_file.name)[1]
            random_filename = f"{uuid.uuid4()}{file_ext}"
            file_path = os.path.join("uploads", random_filename)
            # Save file
            saved_path = default_storage.save(file_path, ContentFile(upload_file.read()))
            absolute_path = settings.MEDIA_ROOT.joinpath(saved_path)
            # load as dataframe
            df = load_dataframe(absolute_path, form.cleaned_data['has_headings'])
            if not df.empty:
                request.session["uploaded_request"] = random_filename
                set_simple_cache(random_filename, saved_path, 600)  # Cache prevents file from being deleted (for 10 minutes)
                if form.cleaned_data['has_headings']:
                    if not find_headers_errors(df.columns.to_list()):
                        return HttpResponseRedirect(reverse('upload_process', kwargs={'uuid': random_filename}))

                return HttpResponseRedirect(reverse('upload_confirm', kwargs={'uuid': random_filename, 'headings': form.cleaned_data['has_headings']}))

    form = UploadFileForm()
    return render(request, "expenses/uploadfile.html", {"form": form})


class ColumnConfirmFormset(formset_factory(UploadColumnForm, extra=0)):

    def is_valid(self):
        """
        This is required since validation is on the collection of forms not a single form
        when we can not blame an actual form,  blame the first one
        """
        valid = super().is_valid()
        if valid:
            headings = []
            for form in self.forms:
                headings.append(form.cleaned_data['heading'])

            errors = find_headers_errors(headings)
            if errors:
                for index in range(len(errors)):
                    if errors[index]:
                        for error in errors[index]:
                            self.forms[index].add_error('heading', error)
                valid = False
        return valid


@login_required
def upload_confirm(request, uuid: uuid, headings):
    """
    uuid:  is the filename
    headings: True or False, if the file is suppose to have headings.
    """

    headings = headings == 'True'
    errors = None
    file_path = os.path.join(default_storage.location, "uploads", uuid)
    df = load_dataframe(file_path, headings)
    if not df.empty:
        if request.method == "POST":
            formset = ColumnConfirmFormset(request.POST)
            if formset.is_valid():
                existing = df.columns.values
                index = 0
                headings = []
                for form in formset.forms:
                    heading = form.cleaned_data['heading']
                    if heading != 'ignore':
                        headings.append(heading)
                        value = int(existing[index]) if isinstance(existing[index], np.int64) else str(existing[index])
                        df.rename({value:heading}, inplace=True, axis='columns' )
                    index += 1
                df.fillna(0, inplace=True)
                df = df[headings]
                if 'Amount' not in headings:
                    df['Amount'] = df['Debit'] - df['Credit']

                # Save a file in csv format.
                file_name = os.path.splitext(uuid)[0] + '.csv'
                file_path = default_storage.base_location.joinpath('uploads', file_name)
                set_simple_cache(file_name, file_path, 600)  # Cache prevents file from being deleted (for 10 minutes)
                df.to_csv(file_path, index=False)
                return HttpResponseRedirect(reverse('upload_process', kwargs={'uuid': uuid}))
            errors = f'{uuid} no data available'
    max_examples = 5 if len(df) > 5 else len(df)
    columns = df.columns.tolist()
    initial = []
    for index in range(len(df.dtypes)):
        if headings:
            heading = df.columns[index]
        else:
            heading = 'ignore'
        initial.append({'example' + str(x): df.iloc[0:max_examples][columns[index]].to_list()[x] for x in range(max_examples)})
        initial[index]['heading'] = heading
    formset = ColumnConfirmFormset(initial=initial)
    return render(request, "expenses/upload_confirm.html", {"formset": formset, "errors": errors})


@login_required
def upload_process(request, uuid: uuid):
    file_path = default_storage.base_location.joinpath('uploads', uuid)
    df = load_dataframe(file_path, True)
    if not df.empty:
        existing = pd.DataFrame.from_records(Item.objects.filter(user=request.user).values_list('date', 'description', 'amount'))
        existing.columns = ['Date', 'Description', 'Amount']
        # existing['Date'] = pd.to_datetime(existing['Date'])
        existing['Amount'] = pd.to_numeric(existing['Amount'])  # Decimal to Float
        df = df.round(2)  # Fix up any crazy rounding issues.

        # todo: I won't pretend to understand this, but it works and it's darn fast.
        to_process = df.drop_duplicates().merge(existing.drop_duplicates(), on=['Date', 'Description', 'Amount'], how='left', indicator=True)
        to_process = to_process.loc[to_process._merge == 'left_only', to_process.columns != '_merge']
        if len(to_process) > 0:
            errors = import_dataframe(to_process, request.user)
    return HttpResponseRedirect(reverse('expense_main'))

@login_required
def export_expense_page(request):
    """
    Export equity / transaction data for the logged-in user.
    The format is suitable for reloading into the application using the 'default' format.
    """
    return render(request, "expenses/export.html", {
        'expenses': Item.objects.filter(user=request.user, ignore=False, income=False).count(),
        'income': Item.objects.filter(user=request.user, ignore=False, income=True).count(),
        'hidden': Item.objects.filter(user=request.user, ignore=True).count()})


@login_required
def export_expenses(request):
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="expense_export.csv"'},
    )
    writer = csv.writer(response)
    writer.writerow(['Date', 'Description', 'Amount', 'Category', 'Subcategory', 'Hidden', 'Details', 'Notes'])

    logger.debug('starting dump')
    for item in Item.objects.filter(user=request.user).exclude(split__isnull=False).exclude(amortized__isnull=False):
        cname = item.category.name if item.category else None
        sname = item.subcategory.name if item.subcategory else None
        hide = 'true' if item.ignore else 'false'
        writer.writerow([item.date, item.description, item.amount, cname, sname, hide, item.details, item.notes])
    logger.debug('ending dump')
    return response


@login_required
def load_subcategories(request):
    user = request.user
    category = request.GET.get("category")
    if category:
        choices = SubCategory.objects.filter(category=category).filter(Q(user__isnull=True) | Q(user=user)).order_by('name')
    else:
        choices = SubCategory.objects.none()
    return render(request, "expenses/includes/subcategory_list_options.html", {"subcat": choices})


@login_required
def load_subcategories_search(request):
    """
    This is complicated because sometimes the subcategory will come in as
    an ID,
    sometimes as a string and
    sometimes not at all
    """
    default = copy.copy(DEFAULT_CATEGORIES)
    search = SubCategory.objects.all()
    user = request.user

    category = request.GET.get("category")
    if category and category not in ['- ALL -', '- NONE -']:
        search = SubCategory.objects.filter(category__name=category).filter(Q(user__isnull=True) | Q(user=user))
    if category == '- NONE -':
        search = SubCategory.objects.none()

    for category in search.order_by('name').distinct().values_list('name', flat=True):
        default.append((category, category))

    return render(request, "expenses/includes/search_options.html", {"options": default})


def load_categories_search(request):
    default = copy.copy(DEFAULT_CATEGORIES)
    for category in Category.objects.all().order_by("name").values_list('name', flat=True):
        if not category == 'Income':
            default.append((category, category))
    default.append(('', '------'))
    default.append(('Income', 'Income'))
    return render(request, "expenses/includes/search_options.html", {"options": default})


@login_required
def expense_pie(request):
    """
    Return the json data that will be used to build a pie chart
    - If we are showing all Categories,  then the pie segments will be based on the categories if we have selected a specific category,  then the
      segments will be based on subcategories.
    - If we

    """
    data = []
    labels = []
    colours = []
    super_set = Item.filter_search(Item.objects.filter(user=request.user), request.GET)
    show_sub = False if request.GET['search_category'] == '- ALL -' else True
    if show_sub:
        category_list = super_set.order_by('subcategory__name').values_list('subcategory__name', flat=True).distinct()
    else:
        category_list = super_set.order_by('category__name').values_list('category__name', flat=True).distinct()

    for category in category_list:
        if show_sub:
            item = super_set.filter(subcategory__name=category).aggregate(sum=Sum('amount'))
        else:
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
    labels = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        labels.append(date_to_label(next_date, 'MONTH'))
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta.relativedelta(months=1)

    if show_sub:
        raw_data = super_set.annotate(month=TruncMonth('date')).values('month').annotate(sum=Sum('amount')).values('month', 'sum', 'subcategory__name')
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
                             'stack': 'stack',
                             'backgroundColor': colors.pop()})
            data_dict[name] = len(datasets) - 1
        try:
            datasets[data_dict[name]]['data'][month_dict[element['month']]] += element['sum']
        except KeyError:
            logger.error('Failed on %s' % element)

    return JsonResponse({'datasets': datasets, 'labels': labels, 'colors': COLORS})


@login_required
def cash_flow_chart(request):
    """
    Build the chart data required for the timespan with the following data
    1.  Income
    2.  Expenses
    """

    date_util = DateUtil(period=request.GET.get('period'), span=request.GET.get('span'))
    show_trends = True if request.GET.get('trends') == 'Show' else False
    income = Item.objects.filter(user=request.user, ignore=False, date__gte=date_util.start_date, category__name='Income')
    expense = Item.objects.filter(user=request.user, ignore=False, date__gte=date_util.start_date).exclude(category__name='Income')

    key = 'period'
    if date_util.is_quarter:
        income_set = income.annotate(period=TruncQuarter('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncQuarter('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    elif date_util.is_year:
        income_set = income.annotate(period=TruncYear('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncYear('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    elif date_util.is_month:
        income_set = income.annotate(period=TruncMonth('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncMonth('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    else:
        key = 'date'
        income_set = income.values('date').annotate(total=Sum('amount')).order_by('date')
        expense_set = expense.values('date').annotate(total=Sum('amount')).order_by('date')

    # Data is in a list of [{'period': date, 'total': Decimal()}...] - A bit messy so lets make it a real dictionary
    dates = date_util.dates({'income': 0, 'expenses': 0})
    for element in income_set:
        dates[element[key]]['income'] = float(element['total'])
    for element in expense_set:
        dates[element[key]]['expenses'] = float(element['total'])

    # Lets get the data back to lists
    labels = []
    expenses = []
    income = []
    for key in dates.keys():
        labels.append(date_util.date_to_label(key))
        expenses.append(dates[key]['expenses'])
        income.append(dates[key]['income'])

    data_sets = [
        {'label': 'Expenses', 'fill': False, 'data': expenses, 'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'], 'tension': 0.1},
        {'label': 'Income', 'fill': False, 'data': income, 'borderColor': PALETTE['olive'], 'backgroundColor': PALETTE['olive'], 'tension': 0.1}]

    if show_trends:
        x_indices = np.arange(len(dates))
        slope, intercept = np.polyfit(x_indices, expenses, 1)
        # Calculate trend line points
        expense_trend = [slope * x + intercept for x in x_indices]
        slope, intercept = np.polyfit(x_indices, income, 1)
        income_trend = [slope * x + intercept for x in x_indices]
        data_sets.append({'label': 'Expense-Trend', 'fill': False, 'data': expense_trend, 'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'],
                          'borderDash': [5, 5]})
        data_sets.append({'label': 'Income-Trend', 'fill': False, 'data': income_trend, 'borderColor': PALETTE['olive'], 'backgroundColor': PALETTE['olive'],
                          'borderDash': [5, 5]})

    return JsonResponse({'labels': labels, 'datasets': data_sets})


@login_required
def cash_flow_chart_v2(request):
    """
    Build the chart data required for the timespan with the following data
    1.  Income
    2.  Expenses

        ('MONTH', 'Months'),
        ('QTR', 'Quarters'),
        ('YEAR', 'Years'),

    period = forms.ChoiceField(choices=PERIODS)
    years = forms.IntegerField(required=False, max_value=10)
    show_trends = forms.ChoiceField(required=False, choices=[('Show', 'Yes'), ('Hide', 'No')])

    """

    date_util = DateUtil(period=request.GET.get('period'), span=request.GET.get('span'))
    date_range = date_util.date_range()

    show_trends = True if request.GET.get('trends') == 'Show' else False
    income = Item.objects.filter(user=request.user, ignore=False, date__gte=date_util.start_date, date__lte=date_util.end_date, category__name='Income')
    expense = Item.objects.filter(user=request.user, ignore=False, date__gte=date_util.start_date, date__lte=date_util.end_date).exclude(category__name='Income')

    key = 'period'
    if date_util.is_quarter:
        income_set = income.annotate(period=TruncQuarter('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncQuarter('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    elif date_util.is_year:
        income_set = income.annotate(period=TruncYear('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncYear('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    elif date_util.is_month:
        income_set = income.annotate(period=TruncMonth('date')).values('period').annotate(total=Sum('amount')).order_by('period')
        expense_set = expense.annotate(period=TruncMonth('date')).values('period').annotate(total=Sum('amount')).order_by('period')
    else:
        key = 'date'
        income_set = income.values('date').annotate(total=Sum('amount')).order_by('date')
        expense_set = expense.values('date').annotate(total=Sum('amount')).order_by('date')

    income_df = pd.DataFrame.from_dict(income_set)
    expense_df = pd.DataFrame.from_dict(expense_set)
    income_df.rename(columns={'period': 'Date', 'total': 'Income'}, inplace=True)
    expense_df.rename(columns={'period': 'Date', 'total': 'Expenses'}, inplace=True)
    income_df['Date'] = pd.to_datetime(income_df['Date'])
    expense_df['Date'] = pd.to_datetime(expense_df['Date'])

    master = pd.merge(date_util.date_range(), income_df, on='Date', how='left')
    master = pd.merge(master, expense_df, on='Date', how='left')
    master.fillna(0, inplace=True)

    labels = master['Label'].tolist()
    data_sets = [
        {'label': 'Expenses', 'fill': False, 'data': master['Expenses'].tolist(), 'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'], 'tension': 0.1},
        {'label': 'Income', 'fill': False, 'data': master['Income'].tolist(), 'borderColor': PALETTE['olive'], 'backgroundColor': PALETTE['olive'], 'tension': 0.1}]

    if show_trends:
        master['RI'] = master['Income'].rolling(window=7, min_periods=1, center=False).mean()
        master['RE'] = master['Expenses'].rolling(window=7, min_periods=1, center=False).mean()
        data_sets.append({'label': 'Expense-Trend', 'fill': False, 'data': master['RE'].tolist(), 'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'],
                          'borderDash': [5, 5]})
        data_sets.append({'label': 'Income-Trend', 'fill': False, 'data': master['RI'].tolist(), 'borderColor': PALETTE['olive'], 'backgroundColor': PALETTE['olive'],
                          'borderDash': [5, 5]})

    return JsonResponse({'labels': labels, 'datasets': data_sets})