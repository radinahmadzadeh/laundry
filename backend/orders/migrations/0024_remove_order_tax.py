from django.db import migrations
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce


def drop_tax_from_unpaid_orders(apps, schema_editor):
    # The 10% tax is gone. Paid orders keep the amount that was actually paid; unpaid ones become the plain item sum.
    Order = apps.get_model('orders', 'Order')
    OrderItem = apps.get_model('orders', 'OrderItem')
    item_sum = (
        OrderItem.objects.filter(order=OuterRef('pk'))
        .values('order')
        .annotate(total=Sum(F('price') * F('quantity')))
        .values('total')
    )
    money = DecimalField(max_digits=10, decimal_places=0)
    Order.objects.filter(is_paid=False).update(
        total_price=Coalesce(Subquery(item_sum, output_field=money), Value(0), output_field=money)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0023_order_price_pending'),
    ]

    operations = [
        migrations.RunPython(drop_tax_from_unpaid_orders, migrations.RunPython.noop),
    ]
