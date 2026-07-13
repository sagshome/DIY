import logging
import pandas as pd
import traceback

from pandas.tseries.offsets import BusinessDay
from typing import Union
from dateutil.relativedelta import relativedelta

from django.db.models import QuerySet

logger = logging.getLogger(__name__)




