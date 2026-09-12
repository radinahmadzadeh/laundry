from django.db import models
import jdatetime
from datetime import date

class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, unique=True)

    def __str__(self):
        return self.name

class Order(models.Model):
    STATUS_CHOICES = (
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
    courier_requested = models.BooleanField(default=False, verbose_name='درخواست پیک')
    latitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='عرض جغرافیایی (Lat)')
    longitude = models.CharField(max_length=50, null=True, blank=True, verbose_name='طول جغرافیایی (Lng)')
    postal_code = models.CharField(max_length=10, null=True, blank=True, verbose_name='کد پستی')

    @property
    def shamsi_date(self):
        shamsi = jdatetime.date.fromgregorian(date=self.created_at.date())
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
            return (self.delivery_date - date.today()).days
        return None

    @property
    def subtotal_amount(self):
        return sum(item.price * item.quantity for item in self.orderitem_set.all())
        
    @property
    def tax_amount(self):
        return int(float(self.subtotal_amount) * 0.10)

    def __str__(self):
        return f"فاکتور {self.id} - {self.customer.name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=0, default=0) 

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        subtotal = sum(item.price * item.quantity for item in self.order.orderitem_set.all())
        self.order.total_price = subtotal + int(float(subtotal) * 0.10)
        self.order.save()

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        subtotal = sum(item.price * item.quantity for item in order.orderitem_set.all())
        order.total_price = subtotal + int(float(subtotal) * 0.10)
        order.save()

    def __str__(self):
        return f"{self.quantity} عدد {self.item_name}"