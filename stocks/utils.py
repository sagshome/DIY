import platform
import tempfile

from datetime import datetime, date, timedelta
from pathlib import Path


def normalize_date(this_date: date | datetime) -> datetime.date:
    """
    Make every date the start of the next month.    The alpahvantage website is based on the last trading day each month
    :param this_date:  The date to normalize
    :return:  The 1st of the next month (and year if December)
    """

    if this_date.day == 1:
        return datetime(this_date.year, this_date.month, 1).date()

    if this_date.month == 12:
        year = this_date.year + 1
        month = 1
    else:
        year = this_date.year
        month = this_date.month + 1

    return datetime(year, month, 1).date()


def next_date(input_date: date) -> date:
    """
    Given a normalized date,  return the next one
    :param input_date:
    :return:
    """
    new = input_date + timedelta(days=32)
    new = new.replace(day=1)
    return new


def last_date(input_date: date) -> date:
    """
    Given a normalized date,  return the next one
    :param input_date:
    :return:
    """
    new = input_date - timedelta(days=1)
    new = new.replace(day=1)
    return new


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
    return normalize_date(datetime.today().date())


def tempdir() -> Path:
    return Path("/tmp" if platform.system() == "Darwin" else tempfile.gettempdir())
