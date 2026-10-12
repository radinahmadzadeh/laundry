"""Persian number and date formatting shared by views and templates."""
from decimal import Decimal, InvalidOperation

import jdatetime
from django import template
from django.utils import timezone

register = template.Library()

FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


@register.filter
def fa_digits(value):
    """Latin digits → Persian digits."""
    return str(value if value is not None else '').translate(FA_DIGITS)


@register.filter
def toman(value):
    """1250000 → ۱٬۲۵۰٬۰۰۰ (non-numeric text is returned unchanged)."""
    try:
        number = int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = '-' if number < 0 else ''
    return sign + f'{abs(number):,}'.replace(',', '٬').translate(FA_DIGITS)


@register.filter
def jalali(value, with_time=True):
    """Aware datetime → '۱۴۰۵/۰۷/۲۰ ۱۷:۱۰' in Tehran time; date → '۱۴۰۵/۰۷/۲۰'."""
    if not value:
        return ''
    if hasattr(value, 'hour'):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        fmt = '%Y/%m/%d %H:%M' if with_time else '%Y/%m/%d'
        text = jdatetime.datetime.fromgregorian(datetime=local).strftime(fmt)
    else:
        text = jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d')
    return fa_digits(text)
