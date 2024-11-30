import logging
import pickle
import platform
import tempfile

from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class DIYImportException(Exception):
    pass


class DateUtil:
    '''
    A class to set step and start date based on period and span
    This keeps our code DRY

    Basic utility date to label
    '''

    def __init__(self, period: str = 'QTR', span: int = 3):
        self.period = period if period else 'QTR'
        self.span = span if span else 3
        self.today = datetime.now().date().replace(day=1)

        if period == 'YEAR':
            self.step = 12
            self.start_date = self.today.replace(year=self.today.year - (self.span + 1)).replace(month=12)  # Nov/2024 -> Dec/2021
        elif period == 'MONTH':
            self.start_date = self.today.replace(year=self.today.year - self.span)  # Nov/2024 -> Nov 2022
            self.step = 1
        else:  # QTR
            self.step = 3
            start_date = self.today.replace(year=(self.today.year - self.span))
            if self.today.month < 4:
                self.start_date = start_date.replace(month=3)
            elif self.today.month < 7:
                self.start_date = start_date.replace(month=6)
            elif self.today.month < 10:
                self.start_date = start_date.replace(month=9)
            else:
                self.start_date = start_date.replace(month=12)

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
        if self.period == 'Year':
            value = str(label_date.year)
        elif self.period == 'Month':
            value = label_date.strftime('%Y-%b')
        elif self.period == 'QTR':
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


def cache_dataframe(key, dataframe, timeout=3600):
    """
    Cache a Pandas DataFrame.

    Args:
        key (str): The cache key.
        dataframe (pd.DataFrame): The DataFrame to cache.
        timeout (int): Cache expiration time in seconds (default: 1 hour).
    """
    # Serialize the DataFrame to a binary format
    if not settings.NO_CACHE:
        pickled_data = pickle.dumps(dataframe)
        cache.set(key, pickled_data, timeout)


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
        pickled_data = cache.get(key)
        if pickled_data:
            logger.debug('Returned cache for %s' % key)
            cache.set(key, pickled_data, 3600)
            # Deserialize the binary data back into a DataFrame
            return pickle.loads(pickled_data)
    return None


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


def last_date(input_date: date) -> date:
    """
    Given a normalized date,  return the next one
    :param input_date:
    :return:
    """
    return input_date - relativedelta(months=1)


def month_delta(first_date: date, second_date: date) -> int:
    """
    Give two dates (where the first is less than the second) return number of months that have passed
    :param first_date:
    :param second_date:
    :return:
    """
    years = (second_date.year - first_date.year) * 12
    months = second_date.month - first_date.month
    return months + years


def normalize_today() -> datetime.date:
    return datetime.today().replace(day=1).date()


def tempdir() -> Path:
    return Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())
