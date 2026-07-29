from django.contrib import admin
from django.utils.html import format_html
import urllib.parse
from .models import Customer, Order, OrderItem

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone')
    search_fields = ('name', 'phone')

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'shamsi_date', 'delivery_date', 'total_price', 'actions_buttons')
    list_filter = ('status',)
    inlines = [OrderItemInline]
    
    readonly_fields = ('total_price',)

    def actions_buttons(self, obj):
        site_url = "radinahmadzadeh.pythonanywhere.com/track/" 
        
        sms_text = f"فاکتور {obj.id} به نام {obj.customer.name} با موفقیت ثبت شد. تاریخ تحویل: {obj.shamsi_date}. برای پیگیری سفارش به لینک زیر مراجعه بفرمایید:\n{site_url}"
        
        encoded_text = urllib.parse.quote(sms_text)
        
        return format_html(
            '<a class="button" style="background-color: #00bcd4; color: white; margin-left: 5px; border-radius: 4px;" href="/receipt/{0}/">فیش لاکچری</a>'
            '<a class="button" style="background-color: #28a745; color: white; border-radius: 4px;" href="sms:{1}?body={2}">📲 پیامک</a>',
            obj.id, obj.customer.phone, encoded_text
        )
    actions_buttons.short_description = "عملیات"