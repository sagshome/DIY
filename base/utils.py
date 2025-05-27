import logging
import os
import platform
import pandas as pd
import tempfile

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from io import StringIO
from pathlib import Path
from pandas import Period
from typing import Dict, List

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.template import loader

logger = logging.getLogger(__name__)

class ReadonlyFieldsMixin:
    readonly_fields: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Optional: make fields readonly in the UI
        for field_name in self.readonly_fields:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs['readonly'] = True

                style = self.fields[field_name].widget.attrs.get('style', '')
                if not style.endswith(';') and style:
                    style += ';'
                self.fields[field_name].widget.attrs['style'] = f"{style} background-color:Wheat;"

    def clean(self):
        cleaned_data = super().clean()

        if self.instance.pk:  # only check if updating an existing instance
            for field_name in self.readonly_fields:
                original_value = getattr(self.instance, field_name, None)
                new_value = cleaned_data.get(field_name)

                if original_value != new_value:
                    self.add_error(field_name, f"{field_name} cannot be changed.")
                    # Revert to original value to be extra safe
                    cleaned_data[field_name] = original_value

        return cleaned_data

def append_styles(widget, **styles):
    existing_style = widget.attrs.get('style', '')
    style_dict = dict([s.split(':') for s in existing_style.rstrip(';').split(';') if ':' in s])
    style_dict.update(styles)
    new_style = '; '.join(f'{k.strip()}: {v.strip()}' for k, v in style_dict.items()) + ';'
    widget.attrs['style'] = new_style


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
    Examples using Sep 27th, 2024, span 4 years
        YEAR = End: Dec 31st 2023  Start Jan 1st 2020
        MONTH = End: Aug 31st, 2024,  Start Sep 1st, 2020
        QTR = End: Jun 30th, 2024, Start Apr 1st, 2020

        Jan 1st - Mar 31st
        Apr 1st = Jun 30th
        July 1st = Sep 30th
        Oct 1st = Dec 31st


    """

    def __init__(self, period: str = 'QTR', span: int = 3, initial=datetime.now().date(), use_today=False):
        if period not in ['YEAR', 'MONTH', 'QTR']:
            logger.error('Invalid PERIOD value:%s' % period)
            period = 'QTR'
        self.period = period

        try:
            self.span = int(span)
        except ValueError:
            logger.error('Invalid SPAN value:%s' % span)
            self.span = 3

        if not use_today:
            initial = initial.replace(day=1)

        # initial = datetime.now().date().replace(day=1)  # Always start at the start of a month

        if period == 'YEAR':
            self.start_date = initial.replace(month=1).replace(day=1) - relativedelta(years=self.span)
            if use_today:
                self.end_date = initial.replace(month=12).replace(day=31)
            else:
                self.end_date = initial.replace(month=12).replace(day=31) - relativedelta(years=1)
            self.step = 12

        elif period == 'MONTH':
            self.end_date = initial   # use_today,  just pass in the date as initial
            self.start_date = initial - relativedelta(years=self.span)  # Nov/2024 -> Nov 2022
            self.step = 1
        else:  # QTR
            self.step = 3
            if initial.month < 4:
                self.start_date = initial.replace(month=1) - relativedelta(years=self.span-1)
                self.end_date = initial.replace(month=12).replace(day=31)
            elif initial.month < 7:  # in 2nd QTR so end is 1st
                self.start_date = initial.replace(month=4) - relativedelta(years=self.span)
                self.end_date = initial.replace(month=3).replace(day=31)
            elif initial.month < 10:
                self.start_date = initial.replace(month=7) - relativedelta(years=self.span)
                self.end_date = initial.replace(month=6).replace(day=30)
            else:
                self.start_date = initial.replace(month=10) - relativedelta(years=self.span)
                self.end_date = initial.replace(month=9).replace(day=30)

    def date_range(self):
        start = self.start_date.strftime('%Y-%m-%d')
        end = self.end_date.strftime('%Y-%m-%d')
        if self.is_quarter:
            date_range = pd.date_range(start, end, freq='QS')
            formatted_dates = date_range.strftime('%Y')
        elif self.is_year:
            date_range = pd.date_range(start, end, freq='YS')
            formatted_dates = date_range.strftime('%Y')
        else:
            date_range = pd.date_range(start, end, freq='MS')
            formatted_dates = date_range.strftime('%Y-%b')

        dataframe = pd.DataFrame({'Date': date_range, 'Label': formatted_dates})
        if self.is_quarter:  # todo: fix this is the actual clause above,  this is a hack
            dataframe['Label'] = dataframe['Date'].dt.year.astype(str) + '-Q' + dataframe['Date'].dt.quarter.astype(str)

        return dataframe

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


def cache_dataframe(key: str, dataframe: pd.DataFrame, timeout=36000):
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
        #  Used when debugging.
        if key.endswith('Components') and 'TBuy' not in list(dataframe.columns):
            assert False, f'Saving corrupt Dataframe for {key}'
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
        logger.debug('going after the %s cache' % key)
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


'''
df = pd.read_excel('/home/scott/shared/Finance/rawdata/scott_qt_jan12024_feb242025.xlsx')
df2 = pd.read_csv('/home/scott/shared/Finance/rawdata/csv/CIBC-ALL.csv', header=None)
df3 = pd.read_excel('/home/scott/shared/Finance/rawdata/Activities_for_01Feb2018_to_06Jan2022.ods', engine='odf')

headings = df.dtypes.to_dict()
for item in headings:
    print (item, headings.get(item).name)
->     'object' vs 'float64'    ?

float(df['Quantity'].sum())
df3.replace(np.nan, 0, inplace=True)
df.columns = ['a', 'b', 'c', 'd']...
    
'''

def load_dataframe(filepath: str, header: bool = True) -> pd.DataFrame:
    file_ext = os.path.splitext(filepath)[1]
    try:
        if file_ext == '.csv':
            if header:
                df = pd.read_csv(filepath)
            else:
                df = pd.read_csv(filepath, header=None)
        elif file_ext == '.ods':
            if header:
                df = pd.read_excel(filepath, engine='odf')
            else:
                df = pd.read_excel(filepath, engine='odf', header=None)
        else:
            if header:
                df = pd.read_excel(filepath)
            else:
                df = pd.read_excel(filepath, header=None)
        return df
    except FileNotFoundError:
        logger.error('File Not Found: %s' % filepath)
    except KeyError:
        logger.error('File Format Error: %s' % filepath)
    except UnicodeDecodeError:
        logger.error('File UnicodeDecodeError Error: %s' % filepath)
    except ValueError:
        logger.error('File Format Value Error: %s' % filepath)
    except:
        logger.error('Unknown Error: %s' % filepath)

    return pd.DataFrame()

def send_basic_mail(subject: str, to: str=settings.EMAIL_HOST_USER, template: str='base/basic_mail.html', context: dict = None):
    template = 'base/basic_mail.html'
    if 'subject' not in context:
        context['subject'] = subject

    body = loader.render_to_string(template, context)
    try:
        send_mail(subject=subject, message=body, from_email=settings.EMAIL_HOST_USER, recipient_list=[to,], html_message=body)
    except Exception:
        logger.exception("Failed to send %s to %s", (subject, to))




def send_diy_mail(subject, to, template, data):
    from django.template import loader
    from django.core.mail import EmailMultiAlternatives
    site_name = 'IOOM'
    domain = 'itsonlyourmoney.com'
    context = {
        "email": to,
        "domain": domain,
        "site_name": site_name,
        "user": to,
        "protocol": "http"}

    for item in data:
        context[item] = data[item]

    subject = subject
    body = loader.render_to_string(template, context)
    email_message = EmailMultiAlternatives(subject, body, None, to)

    try:
        email_message.send()
    except Exception:
        logger.exception("Failed to send to %s", to)


