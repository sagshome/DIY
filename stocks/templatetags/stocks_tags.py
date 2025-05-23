import logging
from babel.numbers import format_decimal
from datetime import datetime, date
from django import template
from django.utils.safestring import mark_safe
from django.utils.translation import to_locale, get_language

from stocks.models import normalize_today
register = template.Library()

logger = logging.getLogger(__name__)
@register.simple_tag
def render_help_text(field):
    if hasattr(field, 'help_text'):
        return mark_safe(
            "<a><img src='/static/img/icons/help.gif' title='{help_text}' /></a>".format(**{'help_text': field.help_text})
        )
    return ''


@register.simple_tag
def month_year(obj, field):
    date_field = getattr(obj, field)
    if isinstance(date_field, date) or isinstance(date_field, datetime):
        return date_field.strftime("%b-%Y")
    else:
        return '-'


@register.simple_tag
def calc_return(obj, value):
    cost = abs(obj)
    value = abs(value)
    result = round(cost-value)
    result_str = format_decimal(abs(result), locale=to_locale(get_language()))

    if result > 0:
        return f'has a net loss of ${result_str}'
    elif result < 0:
        return f"has a net gain of ${result_str}"
    else:
        return "has not loss or gain"


@register.simple_tag
def equity_value(obj, equity_key, *args):
    """
    pd.loc[(pd['Date'] == this_day) & (pd['Equity'] == equity_key)].groupby('Equity')[args[0]].agg(['sum']).iloc[0]['sum']
    """
    this_day = normalize_today()
    try:
        value = obj.get_eattr(args[0], this_day, symbol=equity_key)
    except KeyError:
        logger.error('%s %s Error searching on %s' % (obj, equity_key, args[0]))
        value = 0

    if len(args) > 1:
        value = args[1].format(value)
    return value
