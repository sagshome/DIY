from django import template
from stocks.models import normalize_today
register = template.Library()


@register.simple_tag
def equity_value(obj, equity_key, *args):
    print(obj, equity_key)
    pd = getattr(obj, 'pd')
    try:
        value = pd.loc[(pd['Date'] == normalize_today()) & (pd['Equity'] == equity_key)][args[0]].iloc[0]
    except KeyError:
        print(f'Error searching on {args[0]}')
        value = 0

    #value = getattr(obj.data[equity_key].current_data, args[0])
    if len(args) > 1:
        value = args[1].format(value)
    return value
