from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0012_wallet_wallettransaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='password_hash',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
