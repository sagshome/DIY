import logging
from pandas import DataFrame, DateOffset, DatetimeIndex, Timedelta, Timestamp, concat, date_range, timedelta_range, concat
from pandas.tseries.offsets import BDay

from datetime import datetime, date, time, timedelta
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo

from typing import Union

logger = logging.getLogger(__name__)

EPOCH = Timestamp('January-01-2000')
DEFAULT_ZONE = "America/Toronto"

"""
When used in yfinance history
from wealth.dates_dataframe import FullDatesDF
dates_df = FullDatesDF()
import yfinance as yf
t = yf.Ticker('BCE.TO')

yf_minute = t.history(auto_adjust=False, start=dates_df.yf_minute_start, end=dates_df.yf_minute_end, interval='15m').reset_index()
yf_day = t.history(auto_adjust=False, start=dates_df.yf_day_start, end=dates_df.yf_day_end, interval='1d').reset_index()
yf_month = t.history(auto_adjust=False, start=dates_df.yf_month_start, end=dates_df.yf_month_end, interval='1mo').reset_index()
   # df = vdf.merge(dates_df.minutes_df, on='Datetime', how='left')

# bug Tickers.history does not work with start and end.
# So just use tickers for the 15minute jobs, and figure out how to merge the new results to existing dataframes!


dj_minute = pd.DataFrame(Value.objects.filter(investment__symbol='BCE.TO', scope='minute', date__gte=dates_df.minute_start).values('date', 'value'))
dj_minute = pd.DataFrame(Value.objects.filter(investment__searchable=True, scope='minute', date__gte=dates_df.minute_start).values('date', 'symbol', 'value'))
test if empty
    dj_minute.rename(columns={"date": "Datetime"}, inplace=True)
    # Anything with scope of minute older the min() should be deleted (as part of daily update)
    df = yf_minute.merge(dj_minute, on='Datetime', how='left')  # NaN for value means we need to add it,  value not close to adjusted close = update it.
    df['value'] = df['value'].astype("float64")
    import numpy as np
    df[~np.isclose(df["Adj Close"], df["value"])]   -> everything that changed
else:
    everything in yf_minute


vdf_day = t.history(auto_adjust=False, start=dates_df.day_start, end=dates_df.day_end, interval='1d').reset_index()

"""

IOOM_RANGES = ['week', 'month', 'ytd', 'year', '3years', '5years', 'all']
IOOM_RANGE_STR = ['1 Week', '1 Month', 'Year to Date', '1 Year', '3 Years', '5 Years', 'All Time']
IOOM_DEFAULT_RANGE = 'year'

class IOOMDates:

    # Standard dates based on age - without build ~= .5 ms of overhead - with build (full dataframe - 15 ms)
    def __init__(self, start: date = EPOCH, last: date = datetime.now().date(), force: bool = False, build: bool = True):
        """
        Calculate the border dates based on
        yf.Tickers(searchable).history(interval='15m', period='20d', auto_adjust=False), which is 4 calendar weeks
        """

        # start = start if start else EPOCH
        start = self.align_day(start, keep_month=True)
        last = self.align_day(last, keep_month=True)

        self.day_end = last
        if force:
            self.day_start = start
        else:
            self.day_start = BDay().rollforward(last - Timedelta(weeks=52) + DateOffset(day=1)).date()  # Start of the month 1 year ago

        self.month_end = last  # End of the previous month
        self.month_start = start.replace(day=1)
        self.months_df = DataFrame()
        self.days_df = DataFrame()

        if build:
            self.months_df = DataFrame({'Date': date_range(start=self.month_start, end=last, freq='MS')})
            self.days_df = DataFrame({'Date': date_range(start=self.day_start, end=last, freq='B')})
            self.scoped_df = concat([self.months_df.loc[self.months_df['Date'] < self.days_df['Date'].min()], self.days_df])

    def adjust_for_period(self, value: Union[Timestamp, datetime, date]) -> Union[Timestamp, datetime]:
        """
         return a timestamp that will align with the IOOM value periods

            If value is not timezone aware it will be made so.
            Adjusted for period values are:
                value > 1 Year,  date is set to the 1st of month at 00:00:00
                value < 1 year and > 4 weeks, monday to friday at 00:00:00
                value < 4 weeks, monday to friday at xx:yy:zz

        """
        if not (isinstance(value, Timestamp) or isinstance(value, datetime)):
            raise TypeError(f"Unsupported date type: {type(value)}")

        if value.tzinfo is None:
            value = self.ioom_ts(value)

        if value < self.month_end:
            return value.replace(day=1)

        if value < self.day_end:
            if isinstance(value, Timestamp):
                value = value.normalize()
            else:
                value = value.replace(hour=0, minute=0, second=0, microsecond=0)

            if value < self.month_end:
                value.replace(day=1)
            else:
                value = self.align_day(value)
        else:
            value = self.align_day(value)  # Not sure of the use case where I would be doing this >

        return value

    @staticmethod
    def align_day(value: Union[Timestamp, datetime, date], keep_month: bool = True) -> date:
        """
        Return a date that is between a monday and friday

        value - A date like value
        keep_month  - bool
        return Date must be Monday to Friday
        keep_month then make sure you don't adjust to a new month
        """
        if isinstance(value, Timestamp):
            value = value.date()
        elif isinstance(value, date) and not isinstance(value, datetime):
            pass
        elif isinstance(value, datetime):
            value = value.date()
        else:
            raise TypeError(f"Unsupported type: {type(value)}")

        saturday = 5

        weekday = value.weekday()
        if weekday < saturday:
            return value

        month = value.month
        adjust_by = 1 if weekday == saturday else 2  # For Sunday -> Moves day of week to Friday
        value = value - relativedelta(days=adjust_by)

        if keep_month and value.month != month:
            value = value + relativedelta(days=3)  # Moves day of week from last Friday to next Monday
        return value

    @staticmethod
    def max_day_scope():
        return BDay().rollforward(datetime.today() - Timedelta(weeks=52) + DateOffset(day=1)).date()

    @staticmethod
    def tz_aware(value: Union[Timestamp, datetime, date]) -> bool:
        if isinstance(value, date) and not isinstance(value, datetime):
            return False  # Dates are not timezone aware
        if isinstance(value, Timestamp) or isinstance(value, datetime):
            return value.tzinfo is not None
        raise TypeError(f"Unsupported type: {type(value)}")

    @staticmethod
    def range_to_scope(range_value: str):
        if range_value not in IOOM_RANGES or range_value in ['3years', '5years', 'all']:
            return 'month'
        return 'day'

    @staticmethod
    def range_to_string(range_value: str):
        try:
            return IOOM_RANGE_STR[IOOM_RANGES.index(range_value)]
        except ValueError:
            return f'Invalid Range {range_value}'

    def range_start(self, range_value: str) -> Timestamp:

        if range_value == 'week':
            value = self.day_end - relativedelta(weeks=1)
        elif range_value == 'month':
            value = self.day_end - relativedelta(months=1)
        elif range_value == 'ytd':
            value = self.day_end.replace(month=1, day=1)
        elif range_value == 'year':
            value = self.day_end - relativedelta(years=1)
        elif range_value == '3years':
            value = self.day_end - relativedelta(years=3)
        elif range_value == '5years':
            value = self.day_end - relativedelta(years=5)
        else:
            value = self.month_start  # todo: test if this should be force to day=1
            if range_value != 'all':
                logger.error('Range value of %s requested' % range_value)
        return Timestamp(value)

    @classmethod
    def ioom_ts(cls, value: Union[Timestamp, datetime, date],
                use_timezone: bool = True, tm_zone: str = DEFAULT_ZONE, force=False, to_python=False) -> Union[datetime, Timestamp]:
        """
        Convert a date/datetime/pd.Timestamp to a timezone aware date/datetime/Timestamp

        return aways has a timestamp

        value - A time type object
        use_timezone - bool,  set to True (default) to not convert if the value is already tz aware
        tm_zone - A timezone string, optional
        force - set to the start of the day - default is False (unless a date value is supplied)
        to_python - change pd.Timestamp to datetime - default is False A pd.Timestamp is returned
        """

        if use_timezone and cls.tz_aware(value):
            zone_key = value.tzinfo
        else:
            try:  # Test to see if the key is ok
                zone_key = ZoneInfo(tm_zone)
            except:  # Can't seem to locate - ZoneInfoNotFoundError:
                logger.error("Invalid timezone supplied (%s) for %s - defaulting to UTC" % (tm_zone, value))
                tm_zone = DEFAULT_ZONE
                zone_key = ZoneInfo(tm_zone)

        # This order is important
        if isinstance(value, Timestamp):
            if value.tzinfo is not None:
                value = value.tz_convert(tm_zone)
            else:
                value = value.tz_localize(tm_zone)

            if force:
                value = value.normalize()

            if to_python:
                value = value.to_pydatetime()

        elif isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, time.min, tzinfo=zone_key)

        if isinstance(value, datetime):  # Could be set based on above
            if force:
                return datetime.combine(value, time.min, tzinfo=zone_key)
            else:
                if value.tzinfo is None:
                    value = value.replace(tzinfo=zone_key)
                else:
                    value = value.astimezone(zone_key)
        else:
            raise TypeError(f"Unsupported date type: {type(value)}")

        return value

    @classmethod
    def ts_align(cls, value: Union[Timestamp, datetime, date],
                 use_timezone: bool = True, tm_zone: str = DEFAULT_ZONE, force=False, to_python=False) -> Union[datetime, Timestamp]:
        """
        Adjust timestamp based on day of the week
        """
        return cls.align_day(cls.ioom_ts(value, use_timezone, tm_zone, force, to_python))




