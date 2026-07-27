from django.shortcuts import render
from .models import Order

def track_order(request):
    customer_orders = None
    # گرفتن شماره موبایل از کادر جستجوی کاربر
    phone_number = request.GET.get('phone') 
    
    if phone_number:
        # جستجوی تمام فاکتورهایی که شماره مشتری آن‌ها با شماره وارد شده یکی است
        customer_orders = Order.objects.filter(customer__phone=phone_number).order_by('-created_at')
        
    return render(request, 'track.html', {'orders': customer_orders, 'phone': phone_number})