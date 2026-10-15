"""Numbers and fun facts about one customer's orders, for their account page."""
import re
from collections import Counter

import jdatetime
from django.utils import timezone

from .models import Order

# Order item names look like «کت و شلوار مردانه (خشکشویی + اتو)»: garment, then the service.
ITEM_NAME = re.compile(r'^(?P<garment>.*?)\s*\((?P<service>[^()]*)\)\s*$')
WEEKDAYS = ('شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه')  # jdatetime: Saturday = 0


def split_item_name(name):
    """('کت و شلوار مردانه', 'خشکشویی + اتو') from an order item name; service is '' when absent."""
    match = ITEM_NAME.match(name or '')
    if not match:
        return (name or '').strip(), ''
    return match.group('garment').strip(), match.group('service').strip()



def customer_insights(customer):
    orders = list(
        Order.objects.filter(customer=customer).prefetch_related('orderitem_set').order_by('created_at')
    )

    garments, services = Counter(), Counter()
    pieces_by_order = {}
    for order in orders:
        pieces = 0
        for item in order.orderitem_set.all():
            garment, service = split_item_name(item.item_name)
            garments[garment] += item.quantity
            services['iron' if 'فقط اتو' in service else 'dry'] += item.quantity
            pieces += item.quantity
        pieces_by_order[order.id] = pieces

    pieces = sum(garments.values())
    count = len(orders)
    invoiced = sum(int(o.total_price) for o in orders)
    priced = [o for o in orders if o.total_price > 0]
    courier = sum(1 for o in orders if o.courier_requested or o.delivery_courier_requested)

    top = garments.most_common(5)
    most = top[0][1] if top else 0
    top_items = [
        {'name': name, 'count': n, 'share': round(n * 100 / pieces) if pieces else 0,
         'width': round(n * 100 / most) if most else 0}
        for name, n in top
    ]

    weekday, weekday_count = None, 0
    if count >= 2:
        days = Counter(jdatetime.date.fromgregorian(date=timezone.localtime(o.created_at).date()).weekday() for o in orders)
        best, weekday_count = days.most_common(1)[0]
        weekday = WEEKDAYS[best]

    biggest = max(orders, key=lambda o: pieces_by_order[o.id]) if orders else None
    first, last = (orders[0], orders[-1]) if orders else (None, None)
    today = timezone.localdate()

    facts = []
    # A favourite only when one garment clearly leads (one shirt and one coat is not a favourite).
    if top and top[0][1] >= 2 and (len(top) == 1 or top[0][1] > top[1][1]):
        facts.append({'icon': 'hanger', 'text': f'محبوب‌ترین لباس شما «{top[0][0]}» است؛ تا حالا {top[0][1]} تکه از آن را به ما سپرده‌اید.'})
    if weekday:
        facts.append({'icon': 'calendar', 'text': f'بیشتر سفارش‌هایتان را {weekday}‌ها ثبت کرده‌اید.'})
    if biggest and pieces_by_order[biggest.id] > 1:
        facts.append({'icon': 'box', 'text': f'بزرگ‌ترین سفارش‌تان فاکتور #{biggest.id} بود، با {pieces_by_order[biggest.id]} تکه لباس.'})
    if services['dry'] or services['iron']:
        if services['iron'] > services['dry']:
            facts.append({'icon': 'iron', 'text': 'بیشتر لباس‌هایتان را فقط برای اتو می‌آورید؛ معلوم است خودتان هم اهل شست‌وشو هستید.'})
        else:
            facts.append({'icon': 'drop', 'text': 'بیشتر لباس‌هایتان کامل خشکشویی و اتو می‌شوند.'})
    if first:
        days_with_us = (today - timezone.localtime(first.created_at).date()).days
        facts.append({'icon': 'heart', 'text': (
            'اولین سفارش‌تان امروز بود؛ خوش آمدید!' if days_with_us == 0 else
            f'{days_with_us} روز است که لباس‌هایتان را به ما می‌سپارید.'
        )})
    if courier:
        facts.append({'icon': 'truck', 'text': f'{courier} بار پیک ما لباس‌ها را از خانه برده یا آورده است.'})

    return {
        'orders_count': count,
        'pieces': pieces,
        'invoiced': invoiced,
        'paid': sum(int(o.total_price) for o in orders if o.is_paid),
        'average': round(sum(int(o.total_price) for o in priced) / len(priced)) if priced else 0,
        'active': sum(1 for o in orders if o.status != 'delivered'),
        'top_items': top_items,
        'dry_pieces': services['dry'],
        'iron_pieces': services['iron'],
        'dry_share': round(services['dry'] * 100 / pieces) if pieces else 0,
        'courier_orders': courier,
        'pickup_orders': count - courier,
        'facts': facts,
        'first_order': first,
        'recent_orders': list(reversed(orders[-3:])),
    }
