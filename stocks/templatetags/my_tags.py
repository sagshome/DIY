from django import template

register = template.Library()


@register.simple_tag
def equity_value(obj, equity_key, *args):
    value = getattr(obj.data[equity_key].current_data, args[0])
    if len(args) > 1:
        value = args[1].format(value)
    return value
