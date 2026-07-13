"""
Support both redis and non-redis caches for both simple and dataframe structures
"""
import logging
import pandas as pd
import time

from typing import Union, Dict
from django.core.cache import cache

CACHE_TTL = 60 * 60  # 60 minutes

# Cache Keys are:
