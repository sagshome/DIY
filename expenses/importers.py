import csv
import logging

from datetime import date, datetime
from typing import Dict

from django.contrib.auth.models import User
from base.utils import DIYImportException
from .models import Item, Category, SubCategory

logger = logging.getLogger(__name__)

DEFAULT = {
        'Date': 'Date',
        'Transaction': 'Transaction',
        'Amount': 'Amount',
}


class ExpenseImporter:
    """
    """

    def __init__(self, reader: csv.reader, user: User, headers: Dict[str, str], source: str):
        logger.debug('Starting Import')
        self.source = source
        self.headers = headers  # A dictionary map for csv_columns to pd_columns
        self.mappings = self.get_headers(reader)
        self.warnings = []
        self.categories = None
        NO_DETAILS = '~~NO DETAILS~~'
        process_categories = 'Category' in self.headers
        items = []
        for row in reader:
            xa_date: date = self.csv_date(row)
            if xa_date:  # Skip blank lines
                description: str = self.csv_transaction(row)
                amount: float = self.csv_amount(row)
                details: str = self.csv_details(row)
                if Item.objects.filter(user=user, date=xa_date, description=description, amount=amount).exists():
                    self.warnings.append('Duplicate row: Date %s %s %s' % (date, description, amount))
                else:
                    ignore = False
                    category = subcategory = None
                    if self.csv_ignore(row):
                        ignore = True
                    else:
                        category = self.csv_category(row)
                        subcategory = self.csv_subcategory(row, category)
                    items.append((xa_date, amount, description, details, category, subcategory, ignore))

        # We have eliminated anything already in the DB,  so go ahead and add these records
        logger.debug('Building Records')
        objects = []
        for item in items:
            objects.append(Item(date=item[0], amount=item[1], description=item[2], details=item[3], category=item[4], subcategory=item[5], ignore=item[6],
                                source=self.source, user=user))
        logger.debug('Importing')
        Item.objects.bulk_create(objects, batch_size=100)
        logger.debug('Imported')
    @staticmethod
    def get_category_data():
        categories = {}
        for item in SubCategory.objects.all():
            if item.category.name not in categories:
                categories[item.category.name] = {}
                categories[item.category.name]['object'] = item.category
                categories[item.category.name]['subcat'] = {}
            categories[item.category.name]['subcat'][item.name] = item
        return categories

    def get_headers(self, csv_reader):
        if set(DEFAULT.keys()) - set(self.headers.keys()):
            missing = str(set(self._columns) - set(self.headers.keys()))
            raise DIYImportException('CSV, required column(s) are missing (%s)' % missing)

        header = next(csv_reader)
        return_dict = {}
        for column in self.headers:
            try:
                return_dict[column] = header.index(self.headers[column])
            except ValueError:
                logger.info('Non critical Column:%s is missing from data' % column)
        return return_dict

    def csv_date(self, row) -> date:
        try:
            data = row[self.mappings['Date']]
            if data:
                try:
                    return datetime.strptime(data, '%Y-%m-%d')
                except ValueError:  # pragma: no cover
                    logger.debug('Invalid date %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No date on row %s' % row)
        return None

    def csv_transaction(self, row) -> str:
        return row[self.mappings['Transaction']]

    def csv_details(self, row) -> str:
        """
        Optional
        """
        if 'Detail' in self.mappings:
            return row[self.mappings['Detail']]
        else:
            return None

    def csv_amount(self, row) -> float:
        try:
            data = row[self.mappings['Amount']]
            if data.startswith('$'):
                data = data[1:]
            if data:
                try:
                    return float(data)
                except ValueError:  # pragma: no cover
                    logger.debug('Invalid Amount %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No Amount on row %s' % row)
        return 0

    def csv_ignore(self, row) -> bool:
        if 'Hidden' in self.mappings:
            if row[self.mappings['Hidden']] == 'true':
                return True
        return False

    def csv_category(self, row) -> Category:
        if 'Category' in self.mappings:
            if not self.categories:
                self.categories = self.get_category_data()
            value = row[self.mappings['Category']]
            if value in self.categories:
                return self.categories[value]['object']
        return None

    def csv_subcategory(self, row, category):
        if 'Subcategory' in self.mappings:
            if category:
                value = row[self.mappings['Subcategory']]
                if category.name in self.categories:
                    if value in self.categories[category.name]['subcat']:
                        return self.categories[category.name]['subcat'][value]
        return None


class Generic(ExpenseImporter):
    """
    Downloaded my transactions from manulife and looking to import them
    :param file_name:
    :return:
    """
    def __init__(self, file_name: csv.reader, user: User, source: str):
        super().__init__(file_name, user,{
        'Date': 'Date',
        'Transaction': 'Transaction',
        'Amount': 'Amount',
        'Category': 'Category',
        'Subcategory': 'Subcategory',
        'Hidden': 'Hidden',
        'Detail': 'Details',
    } , source)


class PersonalCSV(ExpenseImporter):

    def __init__(self, file_name: csv.reader, user: User, source: str):
        super().__init__(file_name, user, {
        'Date': 'Date',
        'Transaction': 'Transaction',
        'Amount': 'Debit',
        'Credit': 'Credit',
        'Detail': 'Card'
    }, source)


class CIBC_VISA(ExpenseImporter):
    """
    Downloaded my transactions from manulife and looking to import them
    :param file_name:
    :return:
    """
    def __init__(self, file_name: csv.reader, user: User, source: str):
        super().__init__(file_name, user,{}, source)

    def get_headers(self, csv_reader):
        """
        CIBC banking does not have headers - so make them up
        """
        return {'Amount': 2, 'Date': 0, 'Transaction': 1, 'Credit': 3, 'Detail': 4}

    def csv_amount(self, row) -> float:
        amount = super().csv_amount(row)
        try:
            data = row[self.mappings['Credit']]
            if data:
                try:
                    data = float(data)
                    amount = amount - data
                except ValueError:  # pragma: no cover
                    logger.debug('Invalid Credit %s on row %s' % (data, row))
        except IndexError:
            logger.debug('No Credit on row %s' % row)

        return amount


class CIBC_Bank(CIBC_VISA):
    """
    Same as VISA but no details column    :return:
    """

    def get_headers(self, csv_reader):
        """
        CIBC banking does not have headers - so make them up
        """
        return {'Amount': 2, 'Date': 0, 'Transaction': 1, 'Credit': 3}


