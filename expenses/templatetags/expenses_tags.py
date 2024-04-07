import logging

from datetime import datetime, date
from django import template
from django.utils.safestring import mark_safe

from expenses.forms import ItemSearchForm, ItemListForm
from expenses.models import Item
register = template.Library()

logger = logging.getLogger(__name__)

@register.simple_tag
def expense_count(obj, query):
    return obj.filter_count(query)

@register.simple_tag
def expense_amount(obj, query):
    return obj.filter_amount(query)



