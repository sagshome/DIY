from django import template
from stocks.models import today
register = template.Library()


@register.simple_tag
def equity_value(obj, equity_key, *args):
    pd = getattr(obj, 'pd')
    value = pd.loc[(pd['Date'] == today()) & (pd['Equity'] == equity_key)][args[0]].iloc[0]

    #value = getattr(obj.data[equity_key].current_data, args[0])
    if len(args) > 1:
        value = args[1].format(value)
    return value
