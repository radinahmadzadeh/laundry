import math

from django.db import models
import jdatetime
from datetime import timedelta

from django.utils import timezone


def order_tax(subtotal):
    """10% tax on an order subtotal, rounded down to a whole toman."""
    return int(subtotal) * 10 // 100


# Steps of the order tracker: (status, short label, colour tone, headline, what is happening now).
TRACKING_STEPS = (
    ('collecting', 'جمع‌آوری', 'cyan', 'در انتظار پیک', 'پیک به‌زودی برای تحویل گرفتن لباس‌ها به آدرس شما می‌آید.'),
    ('received', 'دریافت', 'cyan', 'لباس‌ها رسید', 'لباس‌ها در فروشگاه بررسی و برای شست‌وشو آماده می‌شوند.'),
    ('washing', 'شست‌وشو', 'cyan', 'در حال شست‌وشو', 'لباس‌ها با روش مناسب جنس پارچه شسته می‌شوند.'),
    ('ironing', 'اتوکشی', 'violet', 'در حال اتوکشی', 'لباس‌ها اتو و فرم‌دهی می‌شوند تا مرتب تحویل‌تان شوند.'),
    ('ready', 'آماده تحویل', 'amber', 'آماده تحویل', 'لباس‌های تمیز و اتوشده منتظر شما هستند.'),
    ('delivered', 'تحویل داده شد', 'emerald', 'تحویل داده شد', 'سفارش به دست شما رسید؛ ممنون که ما را انتخاب کردید.'),
)

class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, unique=True)
    password_hash = models.CharField(max_length=128, blank=True, default='')
    address = models.TextField(blank=True, default='', verbose_name='آدرس ثبت‌شده')
    address_latitude = models.CharField(max_length=50, blank=True, default='', verbose_name='عرض جغرافیایی آدرس')
    address_longitude = models.CharField(max_length=50, blank=True, default='', verbose_name='طول جغرافیایی آدرس')
    address_postal_code = models.CharField(max_length=10, blank=True, default='', verbose_name='کد پستی آدرس')

    class Meta:
        indexes = [models.Index(fields=['name'], name='customer_name_idx')]

    @property
    def has_saved_address(self):
        return bool(self.address_latitude and self.address_longitude)

    @property
    def wallet_balance(self):
        wallet = getattr(self, 'wallet', None)
        return wallet.balance if wallet else 0

    def __str__(self):
        return self.name


class Wallet(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=0, default=0, verbose_name='موجودی کیف پول')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"کیف پول {self.customer.name}"


class WalletTransaction(models.Model):
    TYPE_CHOICES = (
        ('credit', 'شارژ'),
        ('debit', 'پرداخت'),
    )
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    description = models.CharField(max_length=255, blank=True, default='')
    order = models.ForeignKey('Order', null=True, blank=True, on_delete=models.SET_NULL, related_name='wallet_transactions')
    authority = models.CharField(max_length=64, blank=True, default=None, unique=True, null=True)
    reference_id = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['wallet', '-created_at'], name='wallettx_wallet_created_idx')]

    @property
    def gateway_state(self):
        """'done' for settled transactions; a gateway top-up without a reference is 'pending' for a while, then 'failed'."""
        if self.transaction_type != 'credit' or not self.authority or self.reference_id:
            return 'done'
        if self.created_at and timezone.now() - self.created_at < timedelta(minutes=20):
            return 'pending'
        return 'failed'

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} تومان"

class Order(models.Model):
    STATUS_CHOICES = (
        ('collecting', 'در انتظار جمع‌آوری لباس'),
        ('received', 'دریافت شده'),
        ('washing', 'در حال شستشو'),
        ('ironing', 'در حال اتوکشی'),
        ('ready', 'آماده تحویل'),
        ('delivered', 'تحویل داده شده'),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    created_at = models.DateTimeField(auto_now_add=True)
    delivery_date = models.DateField(null=True, blank=True, verbose_name='تاریخ تحویل')
    total_price = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    is_paid = models.BooleanField(default=False, verbose_name='پرداخت شده')
    # مشتری اقلامی انتخاب کرده که قیمتشان بعد از دیدن لباس مشخص می‌شود؛ پرداخت تا «آماده تحویل» بسته است
    price_pending = models.BooleanField(default=False, verbose_name='قیمت‌گذاری پس از بررسی')

    # پیک دریافت: وقتی سفارش جدید ثبت می‌شه و مشتری می‌خواد پیک لباس‌های کثیف رو از خونه‌اش تحویل بگیره
    courier_requested = models.BooleanField(default=False, verbose_name='درخواست پیک (دریافت لباس)')
    courier_dispatched = models.BooleanField(default=False, verbose_name='پیک دریافت ارسال شد')
    latitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='عرض جغرافیایی دریافت (Lat)')
    longitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='طول جغرافیایی دریافت (Lng)')
    postal_code = models.CharField(max_length=10, null=True, blank=True, verbose_name='کد پستی دریافت')
    address = models.CharField(max_length=500, blank=True, default='', verbose_name='آدرس دریافت')
    # «بدون درخواست» فقط وقتی True است که ادمین صریحاً انتخابش کرده؛ در غیر این صورت وضعیت پیک خنثی (تعیین‌نشده) است
    courier_declined = models.BooleanField(default=False, verbose_name='پیک دریافت: بدون درخواست')

    # پیک تحویل: وقتی سفارش آماده تحویله و مشتری می‌خواد لباس تمیز با پیک برایش ارسال شود
    delivery_courier_requested = models.BooleanField(default=False, verbose_name='درخواست پیک (تحویل لباس)')
    delivery_courier_dispatched = models.BooleanField(default=False, verbose_name='پیک تحویل ارسال شد')
    delivery_latitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='عرض جغرافیایی تحویل (Lat)')
    delivery_longitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='طول جغرافیایی تحویل (Lng)')
    delivery_postal_code = models.CharField(max_length=10, null=True, blank=True, verbose_name='کد پستی تحویل')
    delivery_address = models.CharField(max_length=500, blank=True, default='', verbose_name='آدرس تحویل')
    delivery_courier_declined = models.BooleanField(default=False, verbose_name='پیک تحویل: بدون درخواست')

    class Meta:
        # The lists people open all the time: newest orders, one customer's orders, orders by status,
        # and courier requests still waiting for a courier.
        indexes = [
            models.Index(fields=['-created_at'], name='order_created_idx'),
            models.Index(fields=['customer', '-created_at'], name='order_customer_created_idx'),
            models.Index(fields=['status', '-created_at'], name='order_status_created_idx'),
            models.Index(fields=['courier_requested', 'courier_dispatched'], name='order_pickup_courier_idx'),
            models.Index(fields=['delivery_courier_requested', 'delivery_courier_dispatched'], name='order_delivery_courier_idx'),
        ]

    @property
    def shamsi_date(self):
        shamsi = jdatetime.date.fromgregorian(date=timezone.localtime(self.created_at).date())
        return shamsi.strftime("%Y/%m/%d")

    @property
    def shamsi_delivery_date(self):
        if self.delivery_date:
            shamsi = jdatetime.date.fromgregorian(date=self.delivery_date)
            return shamsi.strftime("%Y/%m/%d")
        return None

    @property
    def days_remaining(self):
        if self.delivery_date:
            return (self.delivery_date - timezone.localdate()).days
        return None

    @staticmethod
    def _map_point(lat, lng):
        """'lat,lng' for a map link, or '' when the stored values are not a real point (e.g. old 'nan' data)."""
        try:
            lat_value, lng_value = float(lat), float(lng)
        except (TypeError, ValueError):
            return ''
        if not (math.isfinite(lat_value) and math.isfinite(lng_value)):
            return ''
        if not (-90 <= lat_value <= 90 and -180 <= lng_value <= 180):
            return ''
        return f'{lat_value},{lng_value}'

    @property
    def pickup_map_point(self):
        return self._map_point(self.latitude, self.longitude)

    @property
    def delivery_map_point(self):
        return self._map_point(self.delivery_latitude, self.delivery_longitude)

    def _tracking_steps(self):
        # The pickup step only exists when a courier collects the clothes.
        if self.courier_requested or self.status == 'collecting':
            return TRACKING_STEPS
        return TRACKING_STEPS[1:]

    @property
    def tracking_steps(self):
        """Tracker steps with their state: done, current or todo."""
        steps = self._tracking_steps()
        current = [s[0] for s in steps].index(self.status)
        return [
            {
                'key': key, 'label': label, 'tone': tone, 'number': i + 1,
                'state': 'done' if i < current else ('current' if i == current else 'todo'),
            }
            for i, (key, label, tone, _title, _text) in enumerate(steps)
        ]

    @property
    def tracking_current(self):
        """The current step with its headline, text and position."""
        steps = self._tracking_steps()
        index = [s[0] for s in steps].index(self.status)
        key, label, tone, title, text = steps[index]
        return {
            'key': key, 'label': label, 'tone': tone, 'title': title, 'text': text,
            'number': index + 1, 'count': len(steps),
        }

    def _rope_path(self, upto):
        count = len(self._tracking_steps())
        xs = [(count - 1 - i) * 100 + 50 for i in range(upto + 1)]
        d = f'M {xs[0]} 8'
        for a, b in zip(xs, xs[1:]):
            d += f' Q {(a + b) / 2:g} 26 {b} 8'
        return d

    @property
    def tracking_rope_path(self):
        """SVG path of the sagging clothesline through every step (first step on the right, RTL)."""
        return self._rope_path(len(self._tracking_steps()) - 1)

    @property
    def tracking_rope_done_path(self):
        """The same clothesline, only as far as the current step."""
        return self._rope_path(self.tracking_current['number'] - 1)

    @property
    def tracking_rope_width(self):
        return len(self._tracking_steps()) * 100

    @property
    def subtotal_amount(self):
        return sum(item.price * item.quantity for item in self.orderitem_set.all())

    @property
    def tax_amount(self):
        return order_tax(self.subtotal_amount)

    @property
    def has_unpriced_items(self):
        """Some lines of a price-pending order still wait for the shop to set their price."""
        return self.price_pending and any(item.price <= 0 for item in self.orderitem_set.all())

    @property
    def payment_open(self):
        """Can the customer pay now?

        Fully priced orders can be paid any time. Orders with items priced after inspection only once
        they are ready and every line has a price, so nobody pays a partial total.
        """
        if self.is_paid or self.total_price <= 0:
            return False
        if not self.price_pending:
            return True
        return self.status in ('ready', 'delivered') and not self.has_unpriced_items

    def __str__(self):
        return f"فاکتور {self.id} - {self.customer.name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='', verbose_name='توضیحات لباس')
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=0, default=0)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        subtotal = sum(item.price * item.quantity for item in self.order.orderitem_set.all())
        self.order.total_price = subtotal + order_tax(subtotal)
        self.order.save()

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        subtotal = sum(item.price * item.quantity for item in order.orderitem_set.all())
        order.total_price = subtotal + order_tax(subtotal)
        order.save()

    def __str__(self):
        return f"{self.quantity} عدد {self.item_name}"


class PriceCategory(models.Model):
    name = models.CharField(max_length=50, verbose_name='نام دسته‌بندی')
    order = models.PositiveIntegerField(default=0, verbose_name='ترتیب نمایش')

    class Meta:
        ordering = ['order']
        verbose_name = 'دسته‌بندی قیمت'
        verbose_name_plural = 'دسته‌بندی‌های قیمت'

    def __str__(self):
        return self.name


class PriceItem(models.Model):
    category = models.ForeignKey(PriceCategory, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=100, verbose_name='نوع لباس')
    dry_clean_price = models.CharField(max_length=30, blank=True, default='', verbose_name='خشکشویی + اتو', help_text='اگر قیمت مشخص نیست خالی بگذارید.')
    iron_only_price = models.CharField(max_length=30, null=True, blank=True, verbose_name='فقط اتو', help_text='خالی بگذارید یعنی ---')
    order = models.PositiveIntegerField(default=0, verbose_name='ترتیب نمایش')

    class Meta:
        ordering = ['order']
        verbose_name = 'قیمت خدمت'
        verbose_name_plural = 'لیست قیمت‌ها'

    def __str__(self):
        return f"{self.category.name} - {self.name}"


class ShopSettings(models.Model):
    name = models.CharField(max_length=100, default='خشکشویی و سفید شویی آرین', verbose_name='نام فروشگاه')
    tagline = models.CharField(max_length=150, blank=True, default='خشکشویی و سفید شویی آرین', verbose_name='تگ‌لاین')
    phone = models.CharField(max_length=20, blank=True, default='۰۹۱۲-۳۲۷۷۸۸۱', verbose_name='شماره تماس')
    address = models.TextField(blank=True, default='تهران، ارم، بلوار فردوس غرب، خیابان بهار جنوبی', verbose_name='آدرس')
    latitude = models.FloatField(null=True, blank=True, default=35.7262837, verbose_name='عرض جغرافیایی فروشگاه')
    longitude = models.FloatField(null=True, blank=True, default=51.2922665, verbose_name='طول جغرافیایی فروشگاه')

    @property
    def map_point(self):
        """'lat,lng' of the shop for map links, or '' when no location is set."""
        if self.latitude is None or self.longitude is None:
            return ''
        return f'{self.latitude},{self.longitude}'

    class Meta:
        verbose_name = 'تنظیمات فروشگاه'
        verbose_name_plural = 'تنظیمات فروشگاه'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.name



class OrderReview(models.Model):
    """نظر و امتیاز مشتری بعد از تحویل سفارش. نظرهای ۵ ستاره (با متن) در صفحه اول نمایش داده می‌شوند."""
    TAG_CHOICES = (
        ('quality', 'کیفیت شستشو'),
        ('ironing', 'اتوی بی‌نقص'),
        ('on_time', 'تحویل به‌موقع'),
        ('courier', 'پیک سریع'),
        ('behavior', 'برخورد محترمانه'),
        ('price', 'قیمت منصفانه'),
    )
    FEATURE_MIN_RATING = 5

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='review')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(verbose_name='امتیاز')
    comment = models.TextField(blank=True, default='', verbose_name='نظر')
    tags = models.CharField(max_length=200, blank=True, default='', verbose_name='برچسب‌ها')
    is_hidden = models.BooleanField(default=False, verbose_name='عدم نمایش در سایت')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at'], name='review_created_idx'),
            models.Index(fields=['is_hidden', 'rating'], name='review_visible_rating_idx'),
        ]
        verbose_name = 'نظر مشتری'
        verbose_name_plural = 'نظرات مشتریان'

    @property
    def tag_labels(self):
        labels = dict(self.TAG_CHOICES)
        return [labels[t] for t in self.tags.split(',') if t in labels]

    @property
    def is_featured(self):
        return self.rating >= self.FEATURE_MIN_RATING and bool(self.comment.strip()) and not self.is_hidden

    @property
    def display_name(self):
        # برای حفظ حریم خصوصی: نام کوچک + حرف اول نام خانوادگی
        parts = (self.customer.name or '').split()
        if not parts:
            return 'مشتری'
        return parts[0] if len(parts) == 1 else f'{parts[0]} {parts[-1][0]}.'

    @property
    def shamsi_date(self):
        return jdatetime.date.fromgregorian(date=timezone.localtime(self.created_at).date()).strftime("%Y/%m/%d")

    def __str__(self):
        return f"نظر فاکتور {self.order_id} - {self.rating} ستاره"
