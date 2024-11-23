import csv
import logging

from datetime import datetime
from dateutil import relativedelta
from json import dumps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear
from django.forms import modelformset_factory
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, HttpResponseRedirect, reverse, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView, FormView, ListView

from base.models import COLORS, PALETTE
from base.utils import DIYImportException, DateUtil
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
            if Item.unassigned(user=request.user).count() > 0:
                return HttpResponseRedirect(reverse('expenses_assign'))
            return HttpResponseRedirect(reverse('expense_main'))

    form = UploadFileForm()
    return render(request, "expenses/uploadfile.html", {"form": form})


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
    writer.writerow(['Date', 'Transaction', 'Amount', 'Category', 'Subcategory', 'Hidden', 'Details', 'Notes'])

    logger.debug('starting dump')
    for item in Item.objects.filter(user=request.user).exclude(split__isnull=False).exclude(amortized__isnull=False):
        cname = item.category.name if item.category else None
        sname = item.subcategory.name if item.subcategory else None
        hide = 'true' if item.ignore else 'false'
        writer.writerow([item.date, item.description, item.amount, cname, sname, hide, item.details, item.notes])
    logger.debug('ending dump')
    return response


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
        if not category == 'Income':
            default.append((category, category))
    default.append(('', '------'))
    default.append(('Income', 'Income'))
    return render(request, "expenses/search_options.html", {"options": default})


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
    show_sub = False if request.GET['search_category'] == '- ALL -' or request.GET['search_category'] == 'Income' else True
    show_income = request.GET.get("income")
    if show_income == 'true':
        show_sub = True
    else:
        super_set = super_set.exclude(category__name='Income')

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
    show_income = True if request.GET.get("income") == 'true' else False
    show_sub = False if request.GET['search_category'] == '- ALL -' or request.GET['search_category'] == 'Income' else True
    if show_income == 'true':
        show_sub = True

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
            print(f'Failed on:{element}')

    return JsonResponse({'datasets': datasets, 'labels': months, 'colors': COLORS})


@login_required
def cash_flow_chart(request):
    """
    Build the chart data required for the timespan with the following data
    1.  Income
    2.  Expenses
    """

    user = request.user
    date_util = DateUtil(period=request.GET.get('period'), span=request.GET.get('span'))

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
        dates[element[key]['income']] = element['total']
    for element in expense_set:
        dates[element[key]['expenses']] = element['total']

    # Lets get the data back to lists
    labels = []
    expenses = []
    income = []
    for key in dates.keys():
        labels.append(date_util.date_to_label(key))
        expenses.append(dates[key]['expenses'])
        income.append(dates[key]['income'])

    chart_data = {'labels': labels,
                  'datasets': [
                      {'label': 'Expenses', 'fill': False, 'data': expenses, 'boarderColor': PALETTE['coral'],  'backgroundColor': PALETTE['coral'], 'tension': 0.1},
                      {'label': 'Income', 'fill': False, 'data': income, 'boarderColor': PALETTE['olive'],  'backgroundColor': PALETTE['olive']}
                      ]
                  }

    return JsonResponse(chart_data)
