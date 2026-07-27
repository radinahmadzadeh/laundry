from django.db import models

def send_fake_sms(phone_number, customer_name):
    print("*" * 30)
    print(f"ارسال پیامک به شماره: {phone_number}")
    print(f"متن پیام: {customer_name} عزیز، سفارش خشکشویی شما آماده تحویل است.")
    print("*" * 30)

class Customer(models.Model):
    name = models.CharField(max_length=100, verbose_name="نام مشتری")
    phone = models.CharField(max_length=11, verbose_name="شماره تماس")

    def __str__(self):
        return self.name

class Order(models.Model):
    STATUS_CHOICES = [
        ('processing', 'در حال شستشو'),
        ('ready', 'آماده تحویل'),
        ('delivered', 'تحویل داده شده'),
    ]
    @property
    def total_price(self):
        total = 0
        for item in self.orderitem_set.all():
            total += (item.price * item.quantity)
        return total
    
    total_price.fget.short_description = 'مبلغ کل (تومان)'
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name="مشتری")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing', verbose_name="وضعیت")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")

    def __str__(self):
        return f"فاکتور {self.id} - {self.customer.name}"

    def save(self, *args, **kwargs):
        if self.pk: 
            old_order = Order.objects.get(pk=self.pk)
            
            if old_order.status != 'ready' and self.status == 'ready':
                send_fake_sms(self.customer.phone, self.customer.name)
        
        super().save(*args, **kwargs)
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, verbose_name="فاکتور")
    item_name = models.CharField(max_length=50, verbose_name="نام لباس (مثل پیراهن)")
    quantity = models.IntegerField(default=1, verbose_name="تعداد")
    price = models.IntegerField(verbose_name="مبلغ")

    def __str__(self):
        return f"{self.quantity} عدد {self.item_name}"