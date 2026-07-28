from django.shortcuts import render
from .models import Order
from django.shortcuts import get_object_or_404

def track_order(request):
    customer_orders = None
    phone_number = request.GET.get('phone') 
    
    if phone_number:
        customer_orders = Order.objects.filter(customer__phone=phone_number).order_by('-created_at')
        
    return render(request, 'track.html', {'orders': customer_orders, 'phone': phone_number})

def print_receipt(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    return render(request, 'receipt.html', {'order': order})