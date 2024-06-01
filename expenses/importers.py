import csv
import logging

from datetime import date, datetime
from typing import Dict

from django.contrib.auth.models import User
from base.utils import DIYImportException
from .models import Item

logger = logging.getLogger(__name__)

DEFAULT = {
        'Date': 'Date',
        'Transaction': 'Transaction',
        'Amount': 'Amount',
}


class ExpenseImporter:
    """
    Do not import objects tha the CSV file into a pd structure, so we can sort it.   Sorting is required, so we can calculate the dividends
    based on the amount of shares owned.
    1. pass1 build imports{date}{amount}{description}[1] - for anything not in the DB
    """


    def __init__(self, reader: csv.reader, user: User, headers: Dict[str, str], source: str):
        self.source = source
        self.headers = headers  # A dictionary map for csv_columns to pd_columns
        self.mappings = self.get_headers(reader)
        self.cache = {}
        NO_DETAILS = '~~NO DETAILS~~'
        for row in reader:
            xa_date: date = self.csv_date(row)
            if xa_date:  # Skip blank lines
                description: str = self.csv_transaction(row)
                amount: float = self.csv_amount(row)
                details: str = self.csv_details(row)
                if not details:
                    details = NO_DETAILS
                if Item.objects.filter(date=xa_date, description=description, amount=amount).exists():
                    logger.warning('Duplicate row: Date %s %s %s' % (date, description, amount))
                else:
                    # Store this data so we can add later
                    if xa_date not in self.cache:
                        self.cache[xa_date] = {}
                    if amount not in self.cache[xa_date]:
                        self.cache[xa_date][amount] = {}
                    if description not in self.cache[xa_date]:
                        self.cache[xa_date][amount][description] = {}
                    if details not in self.cache[xa_date][amount][description]:
                        self.cache[xa_date][amount][description][details] = 0
                    self.cache[xa_date][amount][description][details] += 1

        # We have eliminated anything already in the DB,  so go ahead and add these records
        for c_date in self.cache.keys():
            for c_amount in self.cache[c_date].keys():
                for c_description in self.cache[c_date][c_amount]:
                    for c_detail in self.cache[c_date][c_amount][c_description]:
                        for record in range(self.cache[c_date][c_amount][c_description][c_detail]):
                            this_detail = None if c_detail == NO_DETAILS else c_detail
                            Item.objects.create(date=c_date, user=user, description=c_description, amount=c_amount,
                                                details=this_detail, source=self.source)

    def get_headers(self, csv_reader):
        if set(DEFAULT.keys()) - set(self.headers.keys()):
            missing = str(set(self._columns) - set(self.headers.keys()))
            raise DIYImportException('CSV, required column(s) are missing (%s)' % missing)

        header = next(csv_reader)
        return_dict = {}
        for column in self.headers:
            return_dict[column] = header.index(self.headers[column])
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


class Generic(ExpenseImporter):
    """
    Downloaded my transactions from manulife and looking to import them
    :param file_name:
    :return:
    """
    def __init__(self, file_name: csv.reader, user: User, source: str):
        super().__init__(file_name, user, DEFAULT, source)


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


