"""Customer loyalty: spend enough in one 30-day period and get a discount in the next one.

Periods are counted from the customer's first payment or delivery (Customer.loyalty_started_at), so they
never shift when staff later change an order. What counts is what the customer paid in a period (online, from
the wallet or marked paid in the shop), by the moment it was paid, at the amount actually paid; an order that
staff mark unpaid again stops counting. The discount can be used on one order, only in the period right after
it was earned, and never stacks or carries over.
"""
from datetime import timedelta

import jdatetime
from django.db.models import Sum
from django.utils import timezone

from .models import Order

PERIOD_DAYS = 30
GOAL = 5_000_000
DISCOUNT = 500_000


def shamsi(moment):
    return jdatetime.date.fromgregorian(date=timezone.localtime(moment).date()).strftime('%Y/%m/%d')


def paid_in(customer, start, end):
    """Toman paid for orders between start and end."""
    total = Order.objects.filter(
        customer=customer, is_paid=True, paid_at__gte=start, paid_at__lt=end,
    ).aggregate(total=Sum('total_price'))['total']
    return int(total or 0)


def loyalty_status(customer, now=None):
    """Where the customer stands this period, and whether they have a discount to use right now."""
    now = now or timezone.now()
    status = {'goal': GOAL, 'discount': DISCOUNT, 'period_days': PERIOD_DAYS, 'started': False,
              'available': False, 'used_order_id': None}
    started = customer.loyalty_started_at
    if not started or started > now:
        return status

    period = timedelta(days=PERIOD_DAYS)
    index = (now - started) // period
    start = started + index * period
    end = start + period
    spent = paid_in(customer, start, end)
    status.update({
        'started': True,
        'period_number': index + 1,
        'period_start': start,
        'period_end': end,
        'ends_on': shamsi(end - timedelta(seconds=1)),
        'next_starts_on': shamsi(end),
        'days_left': max((end - now).days, 0),
        'spent': spent,
        'remaining': max(GOAL - spent, 0),
        'progress': min(round(spent * 100 / GOAL), 100),
        'reached': spent >= GOAL,
    })

    earned = index >= 1 and paid_in(customer, start - period, start) >= GOAL
    if earned:
        # Any discounted order placed since this period began uses it up, even if the period's start
        # was ever stored differently on that order.
        used = Order.objects.filter(customer=customer, discount_amount__gt=0, created_at__gte=start).first() \
            or Order.objects.filter(customer=customer, discount_period=start).first()
        status['used_order_id'] = used.id if used else None
        status['available'] = not used
    status['earned'] = earned
    return status
