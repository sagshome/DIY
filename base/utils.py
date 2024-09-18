import platform
import tempfile

from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path


class DIYImportException(Exception):
    pass


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
