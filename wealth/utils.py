import logging
import pandas as pd
import traceback

from pandas.tseries.offsets import BusinessDay
from typing import Union
from dateutil.relativedelta import relativedelta

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

def ETF_breakdown(etf: str):
    '''
    Goal is to change component ETFs into a breakdown of top companies and top sectors by %
    Using YF,
    l1 = yf.Ticker('FGRO.NE')
    if validate ETF
        l1.funds_data.top_holdings.reset_index()
        and if they return ETFs, process them as well.
    '''

