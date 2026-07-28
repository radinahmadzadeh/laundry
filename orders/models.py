from django.db import models
import requests

def send_real_sms(phone_number, customer_name):
    # شما باید این کلید را از پنل پیامکی خود (مثل کاوه‌نگار) دریافت کنید و اینجا بگذارید
    api_key = "YOUR_API_KEY_HERE" 
    
    # آدرس وب‌سرویس پنل پیامکی
    url = f"https://api.kavenegar.com/v1/{api_key}/sms/send.json"
    
    # متنی که می‌خواهیم ارسال شود
    payload = {
        'receptor': phone_number,
        'message': f"{customer_name} عزیز، سفارش خشکشویی شما آماده تحویل است. \nبرای پیگیری وضعیت می‌توانید به سایت مراجعه کنید."
    }
    
    try:
        # اگر هنوز کلید واقعی را وارد نکرده‌ای، برنامه کرش نکند و فقط چاپ کند
        if api_key == "YOUR_API_KEY_HERE":
            print(f"[شبیه‌ساز پیامک] پیام آماده ارسال به {phone_number} است. لطفاً API Key را وارد کنید.")
        else:
            # ارسال درخواست واقعی به مخابرات
            response = requests.post(url, data=payload, timeout=5)
            print(f"[سیستم پیامکی] وضعیت ارسال: {response.status_code}")
            
    except Exception as e:
        print(f"خطا در ارتباط با سرور پیامک: {e}")

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
                    # تغییر نام تابع در اینجا انجام شد
                    send_real_sms(self.customer.phone, self.customer.name)
            
            super().save(*args, **kwargs)
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, verbose_name="فاکتور")
    item_name = models.CharField(max_length=50, verbose_name="نام لباس (مثل پیراهن)")
    quantity = models.IntegerField(default=1, verbose_name="تعداد")
    price = models.IntegerField(verbose_name="مبلغ")

    def __str__(self):
        return f"{self.quantity} عدد {self.item_name}"