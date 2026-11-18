import logging

from datetime import datetime
from dateutil.relativedelta import relativedelta

from django.db.models import Q
from django.shortcuts import render
from expenses.forms import SearchForm, SubCategoryFormSet
from expenses.models import Item, Category, SubCategory, ItemTag, Template, DEFAULT_CATEGORIES

logger = logging.getLogger(__name__)


class ExpenseMixin:
    """
    Used on base page and consumed by base.html - sets menu items
    Ensure required test variables are defined
    """

    def get_context_data(self, **kwargs):
        try:
            context = super().get_context_data(**kwargs)
        except AttributeError:  # Happens when you are mixing in a straight View
            context = {}
        context["expense_context"] = True
        if "warnings" not in context:
            context["warnings"] = ''  # todo: This should be a list
        return context


class SearchMixin:
    """
    Need to blend in range and month,   range is global but how can I be assured the order of the mixin 
    and month is specific to Expense Items.
    """
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        # Range Mixin has priority over search

        self.default_search = {
            "search_category": "- ALL -",
            "search_subcategory": "- ALL -",
            "search_ignore": 'No',
            "search_start_date": datetime.today().date() - relativedelta(years=1),  # Make the same as Range
            "search_end_date": datetime.today().date(),
            "search_amount_qualifier": "gte",
        }
        # Stuff that needs to be pulled out of normal searching
        self.category = request.GET.get("search_category", "- ALL -")
        self.income = request.GET.get("income", "false") == "true"
        self.month = request.GET.get("month", None)
        if self.month:
            try:
                self.month = datetime.strptime(self.month, "%Y-%b")
                self.default_search["search_start_date"] = self.month
                self.default_search["search_end_date"] = (
                    self.month + relativedelta(months=1) - relativedelta(days=1)
                )
            except ValueError:
                self.month = None

    def get_queryset(self):
        """
        Used to set object_list on a ListView,  call it manually on a View
        """
        query = Item.objects.filter(user=self.request.user)
        search_form = SearchForm(self.request.GET or self.default_search)
        if search_form.is_valid():
            query = Item.filter_search(query, search_form.cleaned_data)
        else:
            query = Item.filter_search(query, self.default_search)

        if not self.income:
            query = query.exclude(category__name="Income")

        return query.order_by("-date", "category__name", "subcategory__name")
