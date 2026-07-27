from django.contrib import admin
from .models import Customer, Order, OrderItem

# ۱. این کلاس باعث می‌شود بتوانیم لباس‌ها را داخل خود فرم فاکتور اضافه کنیم
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1 # یک ردیف خالی همیشه برای اضافه کردن لباس جدید آماده می‌گذارد

# ۲. تنظیمات پیشرفته برای نمایش جدول فاکتورها
class OrderAdmin(admin.ModelAdmin):
    # کلمه total_price به انتهای این لیست اضافه شد
    list_display = ('id', 'customer', 'status', 'created_at', 'total_price') 
    
    list_filter = ('status', 'created_at') 
    search_fields = ('customer__name', 'customer__phone') 
    inlines = [OrderItemInline]
# ۳. تنظیمات برای نمایش جدول مشتریان
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone')
    search_fields = ('name', 'phone')

# ۴. ثبت نهایی در پنل ادمین
admin.site.register(Customer, CustomerAdmin)
admin.site.register(Order, OrderAdmin)
# توجه: OrderItem را دیگر جداگانه ثبت نمی‌کنیم چون داخل خود فاکتور قرار گرفت