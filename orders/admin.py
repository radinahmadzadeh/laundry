from django.contrib import admin
from django.utils.html import format_html 
from .models import Customer, Order, OrderItem

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1

class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'created_at', 'total_price', 'print_button_html') 
    list_filter = ('status', 'created_at') 
    search_fields = ('customer__name', 'customer__phone') 
    inlines = [OrderItemInline] 

    # تغییر استایل دکمه به یک دیزاین بسیار مدرن و جذاب
    def print_button_html(self, obj):
        return format_html(
            '<a class="button" href="/receipt/{}" target="_blank" style="background-image: linear-gradient(to right, #4facfe 0%, #00f2fe 100%); color: white; border-radius: 8px; padding: 8px 16px; text-decoration: none; font-weight: bold; box-shadow: 0 4px 15px rgba(0, 242, 254, 0.4); transition: all 0.3s ease; display: inline-block;">فیش لاکچری</a>', 
            obj.id
        )
    print_button_html.short_description = "عملیات"

class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone')
    search_fields = ('name', 'phone')

admin.site.register(Customer, CustomerAdmin)
admin.site.register(Order, OrderAdmin)