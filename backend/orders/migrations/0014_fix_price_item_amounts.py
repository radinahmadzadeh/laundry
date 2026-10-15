from django.db import migrations


def divide_price_by_ten(value):
    if value is None:
        return value
    raw = str(value).strip()
    if not raw:
        return raw
    normalized = raw.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    compact = normalized.replace(',', '').replace('.', '')
    if compact.isdigit() and int(compact) % 10 == 0:
        return str(int(compact) // 10)
    return raw


def multiply_price_by_ten(value):
    if value is None:
        return value
    raw = str(value).strip()
    if not raw:
        return raw
    normalized = raw.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    compact = normalized.replace(',', '').replace('.', '')
    if compact.isdigit():
        return str(int(compact) * 10)
    return raw


def forwards(apps, schema_editor):
    PriceItem = apps.get_model('orders', 'PriceItem')
    for item in PriceItem.objects.all().iterator():
        item.dry_clean_price = divide_price_by_ten(item.dry_clean_price)
        item.iron_only_price = divide_price_by_ten(item.iron_only_price)
        item.save(update_fields=['dry_clean_price', 'iron_only_price'])


def backwards(apps, schema_editor):
    PriceItem = apps.get_model('orders', 'PriceItem')
    for item in PriceItem.objects.all().iterator():
        item.dry_clean_price = multiply_price_by_ten(item.dry_clean_price)
        item.iron_only_price = multiply_price_by_ten(item.iron_only_price)
        item.save(update_fields=['dry_clean_price', 'iron_only_price'])


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0013_customer_password_hash'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
