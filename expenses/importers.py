import csv
import logging

from datetime import date, datetime
from typing import Dict, List

import pandas as pd
from django.contrib.auth.models import User
from base.utils import DIYImportException
from .models import Item, Category, SubCategory

logger = logging.getLogger(__name__)

DEFAULT = {
    'Date': 'Date',
    'Description': 'Description',
    'Amount': 'Amount',
}
EXTRA = {
    'Debit': 'Debit',
    'Credit': 'Credit',
    'Category': 'Category',
    'Subcategory': 'Subcategory',
    'Hidden': 'Hidden',
    'Details': 'Details',
    'Notes': 'Notes',
}


def import_dataframe(df: pd.DataFrame, owner: User):
    """
    Import based on a DataFrame
    """

    if df.empty:
        logger.warning("Attempted to import an empty dataframe")
        return

    if find_headers_errors(df.columns.to_list()):
        logger.error('Invalid Columns in DataFrame %s' % ','.join(df.columns.to_list()))
        return

    categories = dict(Category.objects.all().values_list('name', 'id'))
    for category in categories:
        categories[category] = {'id': categories[category], 'subcategories': {}}

    items = df.to_dict(orient='records')
    objects = []
    for df_item in items:
        item = Item(date=df_item['Date'], description=df_item['Description'], amount=df_item['Amount'], user=owner)
        if 'Hidden' in df_item and isinstance(df_item['Hidden'], bool):
            item.ignore = df_item['Hidden']
        if 'Details' in df_item:
            item.details = df_item['Details']
        if 'Notes' in df_item:
            item.notes = df_item['Notes']
        if 'Category' in df_item and df_item['Category'] in categories:
            item.category_id = categories[df_item['Category']]['id']
            if 'Subcategory' in df_item:
                if df_item['Subcategory'] in categories[df_item['Category']]['subcategories']:
                    item.subcategory_id = categories[df_item['Category']]['subcategories'][df_item['Subcategory']]
                else:
                    try:
                        subcategory = SubCategory.objects.get(category_id=item.category_id, name=df_item['Subcategory'], user__isnull=True)
                    except SubCategory.DoesNotExist:
                        try:
                            subcategory = SubCategory.objects.get(category_id=item.category_id, name=df_item['Subcategory'], user=owner)
                        except:
                            subcategory = SubCategory.objects.create(user=owner, name=df_item['Subcategory'], category_id=item.category_id)
                    categories[df_item['Category']]['subcategories'][df_item['Subcategory']] = subcategory.id
                item.subcategory_id = categories[df_item['Category']]['subcategories'][df_item['Subcategory']]

        objects.append(item)
    Item.objects.bulk_create(objects, batch_size=100)


def find_headers_errors(headers: List[str]) -> List[List[str]]:
    """
    Build a list of errors,  based on the headers supplied
        [[error1, error2,...]
        ]]

    An empty list is a pass

    if not find_header_errors(headers):
        success !

    In case I care about other columns
    tuple(list({'ignore': '-----'}) + list(DEFAULT) + list(EXTRA))
    or
    valid = list(DEFAULT) + list(EXTRA)
    valid.append('ignore')
    """
    def _add_error(existing, index, message) -> List:  # updated
        if not existing:
            existing = [[] for _ in range(len(headers))]
        if not existing[index]:
            existing[index] = [message,]
        else:
            existing[index].append(message)
        return existing

    errors = []
    headings = []
    for index in range(len(headers)):
        heading = headers[index]
        if heading in headings and heading != 'ignore':
            errors = _add_error(errors, index, 'Duplicate heading selected')
        else:
            headings.append(heading)

    if 'Date' not in headings:
        errors = _add_error(errors, 0, 'A Date column is required')
    if 'Description' not in headings:
        errors = _add_error(errors, 0, 'A Description column is required')

    if 'Amount' not in headings:
        # if 'Debit' in headings:
        #     errors = _add_error(errors, headings.index('Debit'), 'Invalid when Amount is selected')
        # if 'Credit' in headings:
        #     errors = _add_error(errors, headings.index('Credit'), 'Invalid when Amount is selected')
    # else:
        if not ('Credit' in headings and 'Debit' in headings):
            errors = _add_error(errors, 0, 'Amount or Debit and Credit are required')
    return errors