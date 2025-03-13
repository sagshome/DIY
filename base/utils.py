import logging
import platform
import pandas as pd
import tempfile

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class DIYImportException(Exception):
    pass


class BoolReason:
    def __init__(self, result: bool, reason: str = None):
        self.result = result
        self.reason = reason

    def __bool__(self):
        return self.result == True

    def __str__(self):
        return self.reason


class DateUtil:
    """
    A class to set step and start date based on period and span
    This keeps our code DRY
    """

    def __init__(self, period: str = 'QTR', span: int = 3):
        self.period = period if period else 'QTR'
        try:
            self.span = int(span)
        except ValueError:
            logger.error('Invalid SPAN value: %s' % span)
            self.span = 3
        self.today = datetime.now().date().replace(day=1)

        if period == 'YEAR':
            self.step = 12
            self.start_date = self.today.replace(year=self.today.year - (self.span + 1)).replace(month=1)  # Nov/2024 -> Dec/2021
        elif period == 'MONTH':
            self.start_date = self.today.replace(year=self.today.year - self.span)  # Nov/2024 -> Nov 2022
            self.step = 1
        else:  # QTR
            self.step = 3
            start_date = self.today.replace(year=(self.today.year - self.span))
            if self.today.month < 4:
                self.start_date = start_date.replace(month=1)
            elif self.today.month < 7:
                self.start_date = start_date.replace(month=4)
            elif self.today.month < 10:
                self.start_date = start_date.replace(month=7)
            else:
                self.start_date = start_date.replace(month=10)

    @classmethod
    def label_to_values(cls, label: str):
        """
        Based on a label value, return a start and end date
        """
        try:  # start of the month
            start_date = datetime.strptime(label, '%Y-%b').replace(day=1).date()
            end_date = start_date + relativedelta(day=31)  # Will set to the last day of the month
        except ValueError:  # start of the year
            start_date = datetime.strptime(label, '%Y').replace(day=1, month=1).date()
            end_date = start_date.replace(month=12, day=31)
        except ValueError:
            values = label.split('-')
            if len(values) == 2:
                try:
                    year = datetime.strptime(values[1], '%Y').replace(day=1).date()
                    if values[0] == 'Q1':
                        start_date = datetime(year, 1, 1)
                    elif values[0] == 'Q2':
                        start_date = datetime(year, 4, 1)
                    elif values[0] == 'Q3':
                        start_date = datetime(year, 7, 1)
                    elif values[0] == 'Q4':
                        start_date = datetime(year, 10, 1)
                    else:
                        start_date = end_date = None
                    if start_date:
                        end_date = start_date + relativedelta(months=3) - relativedelta(days=1)
                except ValueError:
                    start_date = end_date = None
        return start_date, end_date

    @property
    def is_month(self):
        return self.period == 'MONTH'

    @property
    def is_quarter(self):
        return self.period == 'QTR'

    @property
    def is_year(self):
        return self.period == 'YEAR'

    def dates(self, init_dict=None):
        next_date = self.start_date
        dates = {}
        while next_date <= self.today:
            dates[next_date] = {} if not init_dict else init_dict.copy()
            next_date = next_date + relativedelta(months=self.step)
        return dates

    def date_to_label(self, label_date: date) -> str:
        return date_to_label(label_date, self.period)


def date_to_label(label_date: date, period: str) -> str:
    if period == 'YEAR':
        value = str(label_date.year)
    elif period == 'MONTH':
        value = label_date.strftime('%Y-%b')
    elif period == 'QTR':
        if label_date.month < 4:
            value = 'Q1-' + str(label_date.year)
        elif label_date.month < 7:
            value = 'Q2-' + str(label_date.year)
        elif label_date.month < 10:
            value = 'Q3-' + str(label_date.year)
        else:
            value = 'Q4-' + str(label_date.year)
    else:  # I guess this is by the day
        value = label_date.strftime('%d-%b-%Y')
    return value


def label_to_values(label: str):
    """
    Based on a label value, return a start and end date
    """
    start_date = end_date = None
    try:  # start of the month
        start_date = datetime.strptime(label, '%Y-%b').replace(day=1).date()
        end_date = start_date + relativedelta(day=31)  # Will set to the last day of the month
    except ValueError:  # start of the year
        try:
            start_date = datetime.strptime(label, '%Y').replace(day=1, month=1).date()
            end_date = start_date.replace(month=12, day=31)
        except ValueError:
            values = label.split('-')
            if len(values) == 2:
                try:
                    year = datetime.strptime(values[1], '%Y').year
                    if values[0] == 'Q1':
                        start_date = datetime(year, 1, 1)
                    elif values[0] == 'Q2':
                        start_date = datetime(year, 4, 1)
                    elif values[0] == 'Q3':
                        start_date = datetime(year, 7, 1)
                    elif values[0] == 'Q4':
                        start_date = datetime(year, 10, 1)
                    if start_date:
                        start_date = start_date.date()
                        end_date = start_date + relativedelta(months=3) - relativedelta(days=1)
                except ValueError:
                    pass
    return start_date, end_date


def set_simple_cache(key, data, timeout=36000):
    if not settings.NO_CACHE:
        cache.set(key, data, timeout)


def get_simple_cache(key):
    data = None
    if not settings.NO_CACHE:
        data = cache.get(key)
    return data


def clear_simple_cache(key):
    if not settings.NO_CACHE:
        cache.delete(key)


def cache_dataframe(key, dataframe, timeout=36000):
    """
    Cache a Pandas DataFrame.

    Args:
        key (str): The cache key.
        dataframe (pd.DataFrame): The DataFrame to cache.
        timeout (int): Cache expiration time in seconds (default: 1 hour).
    """
    # Serialize the DataFrame to a binary format
    if not settings.NO_CACHE:
        dataframe = dataframe.reset_index(drop=True)
        cache.set(key, dataframe.to_json(), timeout)


def clear_cached_dataframe(key):
    if not settings.NO_CACHE:
        cache.delete(key)


def get_cached_dataframe(key):
    """
    Retrieve a Pandas DataFrame from the cache.

    Args:
        key (str): The cache key.

    Returns:
        pd.DataFrame or None: The cached DataFrame, or None if not found.
    """
    # Retrieve the binary data from the cache
    if not settings.NO_CACHE:
        logger.debug('going after the cache')
        try:
            json_data = cache.get(key)
            if json_data:
                # Deserialize the binary data back into a DataFrame
                return pd.read_json(StringIO(json_data))
        except TypeError:
            logger.debug('Had some strange data with key %s -> clearing the data' % key)
            clear_cached_dataframe(key)
    return pd.DataFrame(columns=[])  # Return a .empty dataframe


def normalize_date(this_date) -> datetime.date:
    """
    Make every date the start of the next month.    The alpahvantage website is based on the last trading day each month
    :param this_date:  The date to normalize
    :return:  The 1st of the next month (and year if December)
    """
    return datetime(this_date.year, this_date.month, 1).date()


def next_date(input_date: date) -> date:
    """
    Given a normalized date,  return the next one
    :param input_date:
    :return:
    """
    return input_date + relativedelta(months=1)


def normalize_today() -> datetime.date:
    return datetime.today().replace(day=1).date()


def tempdir() -> Path:
    return Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())


def aggregate_or_0(expression):
    """
    Evaluate and express
    """
    value = expression
    value = value if value else 0
    return value
