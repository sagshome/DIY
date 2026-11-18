import copy
import csv
import json
import logging
import numpy as np
import os
import pandas as pd
import uuid

from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear
from django.forms import modelformset_factory, formset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views.generic import CreateView, DeleteView, DetailView, UpdateView, ListView, View

from base.mixins import ModalMixin, RangeMixin
from base.models import COLORS, PALETTE
from base.utils import DateUtil, date_to_label, set_simple_cache, load_dataframe

from expenses.importers import import_dataframe, find_headers_errors
from expenses.forms import ItemForm, ItemAddForm, ItemAmortizeForm, ItemEditForm, ItemSplitForm, TemplateForm, SearchForm, UploadFileForm, UploadColumnForm, SubCategoryFormSet, TagFormSet
from expenses.mixins import SearchMixin, ExpenseMixin
from expenses.models import Item, Category, SubCategory, ItemTag, Template, DEFAULT_CATEGORIES

from django.http import JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


class ItemAdd(LoginRequiredMixin, ModalMixin, CreateView):
    model = Item
    form_class = ItemAddForm
    success_url = reverse_lazy('expense_main')
    template_name = 'expenses/cards/item_form.html'

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Add'
        context['help_file'] = "expenses/help/item.html"
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)


class ItemDelete(LoginRequiredMixin, ModalMixin, DeleteView):
    model = Item
    template_name = 'base/basic_confirm_delete.html'
    success_url = reverse_lazy('expense_main')

    def form_valid(self, form):
        self.object.delete()
        return JsonResponse({"ok": True, "redirect": self.get_success_url()})

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['extra_text'] = 'Deleting an Expense/Income Item may not persist if you redo an import.  Perhaps you should just use edit and ignore this record.'
        context['object_type'] = 'Expense'
        return context


class ItemDups(LoginRequiredMixin, ExpenseMixin, ListView):
    model = Item
    template_name = 'expenses/listdups.html'

    def get_queryset(self):
        df = pd.DataFrame(Item.objects.filter(user=self.request.user).values().order_by('id'))
        df = df[df.duplicated(subset=['description', 'date', 'amount'], keep=False)].sort_values(['date', 'description'])
        # todo: This does not belong here but it is after 11PM
        Item.objects.filter(id__in=df['id']).delete()
        return Item.objects.filter(id__in=df['id']).order_by('date', 'description')


class ItemEdit(LoginRequiredMixin, ModalMixin, UpdateView):
    model = Item
    form_class = ItemEditForm
    template_name = "expenses/cards/item_form.html"
    success_url = reverse_lazy('expense_main')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['action'] = 'Edit'
        if self.object.split:
            context['siblings'] = Item.objects.filter(split_id=self.object.split_id).exclude(pk=self.object.pk)
        context['amortized'] = self.object.amortized
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        if form.is_valid():
            obj = form.save()
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)


class ItemSplit(LoginRequiredMixin, ModalMixin, UpdateView):
    model = Item
    form_class = ItemSplitForm
    template_name = "expenses/cards/item_split.html"
    success_url = reverse_lazy('expense_main')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Split'
        if self.object.split:
            context['siblings'] = Item.objects.filter(split_id=self.object.split_id).exclude(pk=self.object.pk)
        context['amortized'] = self.object.amortized
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        original = copy.copy(self.object)
        form = self.get_form()
        if form.is_valid():
            form.save(commit=False)
            original.create_split_items(form)
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)


class ItemUnSplit(LoginRequiredMixin, ModalMixin, DetailView):
    model = Item
    template_name = 'base/modals/basic_confirm.html'
    success_url = reverse_lazy('expense_main')

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['card_header'] = 'Rollback Split Item Records'
        context['card_body'] = 'This record, and the other records it was split with will all be rolled back to the original record.'
        return context

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj:
            if obj.split:
                obj.split.destroy_split()

            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": True, "errors": "Failed to lookup"})


class ItemUnAmortize(LoginRequiredMixin, ModalMixin, DetailView):
    model = Item
    template_name = 'base/modals/basic_confirm.html'
    success_url = reverse_lazy('expense_main')

    def get_object(self, queryset=None):
        return super().get_object(queryset=Item.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['card_header'] = 'Remove Amortization Item Records'
        context['card_body'] = 'This record, and the other records that were amortized will all be rolled back to the original record.'
        return context

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj:
            if obj.amortized:
                obj.unamortize()

            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": True, "errors": "Failed to lookup"})


class ItemAmortize(LoginRequiredMixin, ModalMixin, View):
    form_class = ItemAmortizeForm
    template_name = "expenses/cards/item_amortize.html"
    success_url = reverse_lazy('expense_main')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def dispatch(self, request, *args, **kwargs):
        self.object = get_object_or_404(
            Item,
            pk=kwargs['pk'],
            user=request.user
        )
        return super().dispatch(request, *args, **kwargs)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Amortize'
        context['instance'] = self.object
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data()
        context['form'] = self.form_class()
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        form = self.form_class(data=request.POST)
        if form.is_valid():
            self.object.amortize(form.cleaned_data['periods'], form.cleaned_data['direction'])
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)


#class SubCategoryUpdateView(ModalBaseMixin, LoginRequiredMixin, ExpenseMixin, ContextMixinBase, FormView):
class SubCategoryUpdateView(LoginRequiredMixin, ExpenseMixin, View):
    template_name = "base/modals/basic_modal_formset_table.html"

    def get_queryset(self):
        return SubCategory.objects.filter(user=self.request.user)

    def get(self, request, *args, **kwargs):
        formset = SubCategoryFormSet(queryset=self.get_queryset())
        return render(request, self.template_name, {"formset": formset})

    def post(self, request, *args, **kwargs):
        formset = SubCategoryFormSet(request.POST, queryset=self.get_queryset(), user=request.user)

        if not formset.is_valid():
            errors = []
            for i, form in enumerate(formset):
                for field, messages in form.errors.items():
                    errors.append(
                        {
                            "field": field,
                            "index": i,
                            "messages": messages,
                        }
                    )

            return JsonResponse({"ok": False, "errors": errors})
            '''
            return JsonResponse({
                "ok": False,
                "errors": formset.errors,
            })
            '''
        changed = []
        for form in formset:
            if form.has_changed():
                changed.append({
                    "pk": form.instance.pk,
                    "fields": form.changed_data,
                    "is_new": form.instance.pk is None,
                })

        formset.save()

        return JsonResponse({
            "ok": True,
            "close": True,
        })


class TagUpdateView(LoginRequiredMixin, ExpenseMixin, View):
    template_name = "base/modals/basic_modal_formset_table.html"

    def get_queryset(self):
        return ItemTag.objects.filter(user=self.request.user)

    def get(self, request, *args, **kwargs):
        formset = TagFormSet(queryset=self.get_queryset())
        return render(request, self.template_name, {"formset": formset})

    def post(self, request, *args, **kwargs):
        formset = TagFormSet(request.POST, queryset=self.get_queryset(), user=request.user)

        if not formset.is_valid():
            errors = []
            for i, form in enumerate(formset):
                for field, messages in form.errors.items():
                    errors.append(
                        {
                            "field": field,
                            "index": i,
                            "messages": messages,
                        }
                    )

            return JsonResponse({"ok": False, "errors": errors})
        changed = []
        for form in formset:
            if form.has_changed():
                changed.append({
                    "pk": form.instance.pk,
                    "fields": form.changed_data,
                    "is_new": form.instance.pk is None,
                })

        formset.save()

        return JsonResponse({
            "ok": True,
            "close": True,
        })

@login_required
@require_POST
def expense_tags_api(request, pk):

    expense = Item.objects.get(pk=pk, user=request.user)
    data = json.loads(request.body)
    tag_ids = data.get('tags', [])
    tags = ItemTag.objects.filter(id__in=tag_ids)
    expense.tags.set(tags)

    return JsonResponse({
        'success': True,
        'tags': [
            {
                'id': tag.id,
                'value': tag.value,
            }
            for tag in tags
        ]
    })


class ListTemplates(LoginRequiredMixin, ExpenseMixin, ListView):
    model = Template
    template_name = 'expenses/templates.html'

    def get_queryset(self):
        return Template.objects.filter(user=self.request.user).order_by('-count')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class AddTemplateView(LoginRequiredMixin, ModalMixin, CreateView):
    model = Template
    form_class = TemplateForm
    success_url = reverse_lazy('expenses_assign')
    template_name = 'base/modals/basic_card.html'

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
        context['action'] = 'Create Template'
        context['success_url'] = self.request.META.get('HTTP_REFERER', reverse('expenses_assign'))
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            form.save()
            return JsonResponse({"ok": True, "redirect": self.get_success_url()})
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)


class ItemFormSet(modelformset_factory(Item, form=ItemEditForm, extra=0)):
    def save(self, commit=True):
        # Call the original save method to save the forms in the formset
        super(ItemFormSet, self).save(commit=commit)

        # Custom action (e.g., send an email notification)
        if commit:
            # Perform your custom action here
            pass


def cash_help(request):
    return render(request, 'expenses/includes/help.html', {'success_url': request.META.get('HTTP_REFERER', '/')})


class ExpenseMainView(LoginRequiredMixin, ExpenseMixin, SearchMixin, RangeMixin, ListView):
    model = Item
    template_name = 'expenses/main.html'

    def get_context_data(self, **kwargs):
        total = self.object_list.aggregate(Sum('amount'))['amount__sum']
        total_length = self.object_list.count()
        missing = self.object_list.filter(category__isnull=True).count()
        self.object_list = self.object_list.order_by('-date', '-id')[0:299]
        context = super().get_context_data(**kwargs)
        context['total'] = total
        if total_length != self.object_list.count():
            context['info'] = f'Item list has been truncated - {total_length - self.object_list.count()} records omitted.  Use the charts above to filter the list to see a subset of records.'
        if missing:
            context['warnings'] = f' {missing} Expense Items have not been processed. Use <a href="{reverse_lazy('expenses_assign')}">Assign Expense Categories</a> to assign categories'

        context['tags'] = ItemTag.objects.filter(user=self.request.user)
        #format_html('Please review the information at <a href="{}">{}</a>', reverse_lazy('expenses_assign'), 'Assign Expenses')
        # f'{missing} Expense Items have not been processed. <a href="{reverse_lazy('expenses_assign')}">Assign Expense Categories</a>'
        return context


class ExpensePieView(LoginRequiredMixin, ExpenseMixin, SearchMixin, RangeMixin, ListView):
    model = Item

    def render_to_response(self, context, **response_kwargs):
        labels = []
        data = []
        show_sub = False if self.category == "- ALL -" else True
        if show_sub:
            category_list = (
                self.object_list.order_by("subcategory__name")
                .values_list("subcategory__name", flat=True)
                .distinct()
            )
        else:
            category_list = (
                self.object_list.order_by("category__name")
                .values_list("category__name", flat=True)
                .distinct()
            )

        for category in category_list:
            if show_sub:
                item = (
                    self.object_list.filter(subcategory__name=category)
                    .order_by("subcategory__name")
                    .aggregate(sum=Sum("amount"))
                )
            else:
                item = (
                    self.object_list.filter(category__name=category)
                    .order_by("category__name")
                    .aggregate(sum=Sum("amount"))
                )

            labels.append(category)
            value = int(item["sum"])
            data.append(value)
        return JsonResponse({"data": data, "labels": labels, "colors": COLORS})


class ExpenseBarView(LoginRequiredMixin, ExpenseMixin, SearchMixin, RangeMixin, ListView):
    model = Item

    def render_to_response(self, context, **response_kwargs):
        show_sub = False if self.category == "- ALL -" else True

        if self.object_list.count() == 0:
            return JsonResponse({"datasets": [], "labels": []})

        first_date = self.object_list.earliest("date").date.replace(day=1)
        last_date = self.object_list.latest("date").date.replace(day=1)

        months = []
        labels = []
        month_dict = {}
        next_date = first_date
        while next_date <= last_date:
            months.append(next_date)
            labels.append(date_to_label(next_date, "MONTH"))
            month_dict[next_date] = len(months) - 1
            next_date = next_date + relativedelta(months=1)

        if show_sub:
            raw_data = (
                self.object_list.annotate(month=TruncMonth("date"))
                .values("month")
                .annotate(sum=Sum("amount"))
                .values("month", "sum", "subcategory__name")
                .order_by("subcategory__name")
            )
        else:
            raw_data = (
                self.object_list.annotate(month=TruncMonth("date"))
                .values("month")
                .annotate(sum=Sum("amount"))
                .values("month", "sum", "category__name")
                .order_by("category__name")
            )

        colors = COLORS.copy()
        colors.reverse()

        initial_data = [0 for i in range(len(months))]
        datasets = []

        data_dict = {}
        for element in raw_data:
            name = (
                element["subcategory__name"] if show_sub else element["category__name"]
            )
            this_date = element["month"]
            if name not in data_dict:
                datasets.append(
                    {
                        "label": name,
                        "data": initial_data.copy(),
                        "stack": "stack",
                        "backgroundColor": colors.pop(),
                    }
                )
                data_dict[name] = len(datasets) - 1
            try:
                datasets[data_dict[name]]["data"][month_dict[element["month"]]] += (
                    element["sum"]
                )
            except KeyError:
                logger.error("Failed on %s" % element)

        return JsonResponse({"datasets": datasets, "labels": labels, "colors": COLORS})


class DetailEditView(LoginRequiredMixin, SearchMixin, ExpenseMixin, View):
    template_name = 'expenses/detail_edit.html'
    assigning = False

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        self.action = request.POST.get('action', 'search')

        if self.action == 'save':
            pass # Process the existing formset

        elif self.action == 'search':
            pass


    def get_context_data(self):
        context = super().get_context_data(**self.kwargs)
        context['tags'] = ItemTag.objects.all().order_by('value'),
        context['help_file'] = 'expenses/help/main.html'
        context['assigning'] = self.assigning
        return context

    def get_formset(self, filters, data=None):
        if self.assigning:
            Item.apply_templates(self.request.user)

        full_list = Item.filter_search(Item.objects.filter(user=self.request.user), filters)[:300]
        if data:
            return ItemFormSet(data, initial=full_list)
        return ItemFormSet(queryset=full_list)

    def get(self, request, *args, **kwargs):

        context = self.get_context_data()
        if self.assigning:
            self.default_search['search_category'] = '- NONE -'

        context['search_form'] = SearchForm(request.GET or self.default_search)
        if context['search_form'].is_valid():
            context["formset"] = self.get_formset(context['search_form'].cleaned_data)
        else:
            context['formset'] = self.get_formset(self.default_search)
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        # Nov 11,  what if I change the search and what does that do to the formset ??? 
        context = self.get_context_data()
        context['search_form'] = SearchForm(request.GET or self.default_search)
        if context['search_form'].is_valid():
            formset = self.get_formset(context['search_form'].cleaned_data, data=request.POST)
            if formset.is_valid():
                formset.save()
                context["formset"] = self.get_formset(self.default_search)
        else:
            context["formset"] = self.get_formset(self.default_search, data=request.POST)

        if self.assigning:
            return redirect('expense_main')

        return render(request, self.template_name, context)


class AssignFormSet(modelformset_factory(Item, form=ItemForm, extra=0)):
    def save(self, commit=True):
        # Call the original save method to save the forms in the formset
        super(AssignFormSet, self).save(commit=commit)

        # Custom action (e.g., send an email notification)
        if commit:
            # Perform your custom action here
            pass


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
    else:
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
    df = df.fillna('')
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
                    try:
                        df['Debit'] = df['Debit'].replace("", 0).astype('float64')
                        df['Credit'] = df['Credit'].replace("", 0).astype('float64')
                        df['Amount'] = df['Debit'] - df['Credit']
                    except:
                        pass

                # Save a file in csv format.
                file_name = os.path.splitext(uuid)[0] + '.csv'
                file_path = default_storage.base_location.joinpath('uploads', file_name)
                set_simple_cache(file_name, file_path, 600)  # Cache prevents file from being deleted (for 10 minutes)
                df.to_csv(file_path, index=False)
                return HttpResponseRedirect(reverse('upload_process', kwargs={'uuid': uuid}))
            errors = f'{uuid} no data available'
    max_examples = 11 if len(df) > 11 else len(df)
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
        df['Date'] = pd.to_datetime(df['Date'])
        df['abs_amount'] = df['Amount'].astype(float).abs()
        df = df.round(2)  # Fix up any crazy rounding issues.

        existing = pd.DataFrame.from_records(Item.objects.filter(user=request.user).values_list('date', 'description', 'amount'))
        if not existing.empty:
            existing.columns = ['Date', 'Description', 'Amount']
            existing['Date'] = pd.to_datetime(existing['Date'])
            existing['Amount'] = pd.to_numeric(existing['Amount'])  # Decimal to Float

            # existing['abs_amount'] = existing['Amount'].astype(float).abs()
            existing = existing.round(2)

            # todo: I won't pretend to understand this, but it works and it's darn fast.
            to_process = df.drop_duplicates().merge(existing.drop_duplicates(), on=['Date', 'Description', 'Amount'], how='left', indicator=True)
            to_process = to_process.loc[to_process._merge == 'left_only', to_process.columns != '_merge']
        else:
            to_process = df

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


'''
def load_categories_search(request):
    default = copy.copy(DEFAULT_CATEGORIES)
    for category in Category.objects.all().order_by("name").values_list('name', flat=True):
        if not category == 'Income':
            default.append((category, category))
    default.append(('', '------'))
    default.append(('Income', 'Income'))
    return render(request, "expenses/includes/search_options.html", {"options": default})
'''

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

    master = date_util.date_range()
    data_sets = []
    if not income_df.empty:
        income_df['Date'] = pd.to_datetime(income_df['Date'])
        master = pd.merge(master, income_df, on='Date', how='left')
    else:
        master['Income'] = 0

    if not expense_df.empty:
        expense_df['Date'] = pd.to_datetime(expense_df['Date'])
        master = pd.merge(master, expense_df, on='Date', how='left')
    else:
        master['Expenses'] = 0

    master.fillna(0, inplace=True)

    labels = master['Label'].tolist()
    data_sets.append(
        {'label': 'Expenses', 'fill': False, 'data': master['Expenses'].tolist(),
         'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'], 'tension': 0.1})
    if show_trends:
        master['RI'] = master['Income'].rolling(window=7, min_periods=1, center=False).mean()
        data_sets.append(
            {'label': 'Income-Trend', 'fill': False, 'data': master['RI'].tolist(), 'borderColor': PALETTE['olive'],
             'backgroundColor': PALETTE['olive'],
             'borderDash': [5, 5]})

    data_sets.append(
        {'label': 'Income', 'fill': False, 'data': master['Income'].tolist(),
         'borderColor': PALETTE['olive'], 'backgroundColor': PALETTE['olive'], 'tension': 0.1})
    if show_trends:
        master['RE'] = master['Expenses'].rolling(window=7, min_periods=1, center=False).mean()
        data_sets.append({'label': 'Expense-Trend', 'fill': False, 'data': master['RE'].tolist(),
                          'borderColor': PALETTE['coral'], 'backgroundColor': PALETTE['coral'],
                          'borderDash': [5, 5]})

    return JsonResponse({'labels': labels, 'datasets': data_sets})