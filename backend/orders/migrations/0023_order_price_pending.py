from django.db import migrations, models


def mark_unpriced_orders(apps, schema_editor):
    # Unpaid orders that already hold an item without a price wait for the shop's final price too.
    Order = apps.get_model('orders', 'Order')
    Order.objects.filter(is_paid=False, orderitem__price__lte=0).update(price_pending=True)


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0022_scale_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='price_pending',
            field=models.BooleanField(default=False, verbose_name='قیمت‌گذاری پس از بررسی'),
        ),
        migrations.RunPython(mark_unpriced_orders, migrations.RunPython.noop),
    ]
