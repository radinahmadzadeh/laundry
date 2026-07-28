from django.db import models
import jdatetime

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
        ('packaging', 'بسته‌بندی'),
        ('ready', 'آماده تحویل'),
        ('delivered', 'تحویل داده شده'),
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    created_at = models.DateTimeField(auto_now_add=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=0, default=0)

    @property
    def shamsi_date(self):
        shamsi = jdatetime.date.fromgregorian(date=self.created_at.date())
        return shamsi.strftime("%Y/%m/%d")

    def __str__(self):
        return f"فاکتور {self.id} - {self.customer.name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    item_name = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=0, default=0) 

    def __str__(self):
        return f"{self.quantity} عدد {self.item_name}"