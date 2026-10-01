from decimal import Decimal, ROUND_HALF_UP
from django import template
register = template.Library()


@register.filter
def money(value):
    if value is None:
        return ''
    value = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    sign = '-' if value < 0 else ''
    whole, fraction = format(abs(value), '.2f').split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while head:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ','.join(groups + [tail])
    return f'{sign}{whole}.{fraction}'


@register.filter
def weight(value):
    return format(Decimal(value).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP), '.3f') if value is not None else ''


@register.filter
def attr(value, name):
    return getattr(value, name, '')


@register.filter
def percent(value):
    if value is None:
        return ''
    return format(Decimal(value) * Decimal('100'), '.2f').rstrip('0').rstrip('.') + '%'
