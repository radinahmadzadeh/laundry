from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from orders.models import (
    Customer,
    Order,
    OrderItem,
    PriceCategory,
    PriceItem,
    ShopSettings,
)

staff_required = user_passes_test(lambda u: u.is_authenticated and u.is_staff, login_url='panel_login')


def panel_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('panel_dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('panel_dashboard')
        error = 'نام کاربری یا رمز عبور اشتباه است.'

    return render(request, 'panel/login.html', {'error': error})


def panel_logout(request):
    logout(request)
    return redirect('panel_login')


@staff_required
def dashboard(request):
    today = timezone.localdate()
    orders_today = Order.objects.filter(created_at__date=today)
    revenue_today = orders_today.filter(is_paid=True).aggregate(total=Sum('total_price'))['total'] or 0

    status_summary = [
        {'code': code, 'label': label, 'count': Order.objects.filter(status=code).count()}
        for code, label in Order.STATUS_CHOICES
    ]

    ready_orders = Order.objects.filter(status='ready').select_related('customer')
    pending_courier = Order.objects.filter(courier_requested=True, courier_dispatched=False)

    context = {
        'active': 'dashboard',
        'orders_today_count': orders_today.count(),
        'revenue_today': revenue_today,
        'status_summary': status_summary,
        'ready_orders': ready_orders,
        'pending_courier': pending_courier,
    }
    return render(request, 'panel/dashboard.html', context)


@staff_required
def orders_list(request):
    orders = Order.objects.select_related('customer').order_by('-created_at')

    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()

    if status:
        orders = orders.filter(status=status)
    if q:
        orders = orders.filter(
            Q(customer__phone__icontains=q) | Q(customer__name__icontains=q) | Q(id__icontains=q)
        )

    context = {
        'active': 'orders',
        'orders': orders,
        'status_choices': Order.STATUS_CHOICES,
        'current_status': status,
        'q': q,
    }
    return render(request, 'panel/orders_list.html', context)


@staff_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if request.method == 'POST':
        item_name = request.POST.get('item_name_manual', '').strip() or request.POST.get('item_name', '').strip()
        item_qty = request.POST.get('item_qty')
        item_price = request.POST.get('item_price')

        if item_name and item_qty and item_price:
            OrderItem.objects.create(order=order, item_name=item_name, quantity=int(item_qty), price=item_price)
            messages.success(request, 'قلم جدید اضافه شد.')
        else:
            messages.error(request, 'نام، تعداد و قیمت الزامی است.')
        return redirect('panel_order_detail', order_id=order.id)

    context = {
        'active': 'orders',
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
        'price_items': PriceItem.objects.select_related('category').all(),
    }
    return render(request, 'panel/order_detail.html', context)


@staff_required
def order_item_delete(request, order_id, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order_id=order_id)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'قلم حذف شد.')
    return redirect('panel_order_detail', order_id=order_id)


@staff_required
def order_update_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            order.save()
            messages.success(request, 'وضعیت سفارش بروزرسانی شد.')

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def order_toggle_paid(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.is_paid = not order.is_paid
        order.save()
        messages.success(request, 'وضعیت پرداخت بروزرسانی شد.')

    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def order_delete(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.delete()
        messages.success(request, 'سفارش حذف شد.')
        return redirect('panel_orders')
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def order_create(request):
    customers = Customer.objects.order_by('name')
    price_items = PriceItem.objects.select_related('category').order_by('category__order', 'order')

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        new_name = request.POST.get('new_customer_name', '').strip()
        new_phone = request.POST.get('new_customer_phone', '').strip()
        delivery_days = request.POST.get('delivery_days', '').strip()

        if customer_id:
            customer = get_object_or_404(Customer, id=customer_id)
        elif new_name and new_phone:
            customer, _ = Customer.objects.get_or_create(phone=new_phone, defaults={'name': new_name})
        else:
            messages.error(request, 'لطفاً مشتری را انتخاب یا اطلاعات مشتری جدید را کامل وارد کنید.')
            return redirect('panel_order_create')

        delivery_date = None
        if delivery_days.isdigit():
            delivery_date = date.today() + timedelta(days=int(delivery_days))

        order = Order.objects.create(customer=customer, delivery_date=delivery_date)

        item_names = request.POST.getlist('item_name[]')
        item_qtys = request.POST.getlist('item_qty[]')
        item_prices = request.POST.getlist('item_price[]')

        created_any = False
        for name, qty, price in zip(item_names, item_qtys, item_prices):
            if name.strip() and qty.strip() and price.strip():
                OrderItem.objects.create(order=order, item_name=name.strip(), quantity=int(qty), price=price)
                created_any = True

        if not created_any:
            order.delete()
            messages.error(request, 'حداقل یک قلم لباس باید اضافه شود.')
            return redirect('panel_order_create')

        messages.success(request, f'سفارش #{order.id} با موفقیت ثبت شد.')
        return redirect('panel_order_detail', order_id=order.id)

    context = {
        'active': 'order_create',
        'customers': customers,
        'price_items': price_items,
    }
    return render(request, 'panel/order_form.html', context)


@staff_required
def customers_list(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all().order_by('name')
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    context = {'active': 'customers', 'customers': customers, 'q': q}
    return render(request, 'panel/customers_list.html', context)


@staff_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    orders = customer.order_set.order_by('-created_at')
    context = {'active': 'customers', 'customer': customer, 'orders': orders}
    return render(request, 'panel/customer_detail.html', context)


@staff_required
def pricing_list(request):
    categories = PriceCategory.objects.prefetch_related('items').all()
    return render(request, 'panel/pricing_list.html', {'active': 'pricing', 'categories': categories})


@staff_required
def price_category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            order = PriceCategory.objects.count()
            PriceCategory.objects.create(name=name, order=order)
            messages.success(request, 'دسته‌بندی اضافه شد.')
    return redirect('panel_pricing')


@staff_required
def price_category_delete(request, category_id):
    category = get_object_or_404(PriceCategory, id=category_id)
    if request.method == 'POST':
        category.delete()
        messages.success(request, 'دسته‌بندی حذف شد.')
    return redirect('panel_pricing')


@staff_required
def price_item_create(request):
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        name = request.POST.get('name', '').strip()
        dry = request.POST.get('dry_clean_price', '').strip()
        iron = request.POST.get('iron_only_price', '').strip()

        if category_id and name and dry:
            category = get_object_or_404(PriceCategory, id=category_id)
            order = category.items.count()
            PriceItem.objects.create(
                category=category, name=name,
                dry_clean_price=dry, iron_only_price=iron or None, order=order,
            )
            messages.success(request, 'قیمت جدید اضافه شد.')
        else:
            messages.error(request, 'نام و قیمت خشکشویی الزامی است.')
    return redirect('panel_pricing')


@staff_required
def price_item_update(request, item_id):
    item = get_object_or_404(PriceItem, id=item_id)
    if request.method == 'POST':
        item.name = request.POST.get('name', item.name).strip()
        item.dry_clean_price = request.POST.get('dry_clean_price', item.dry_clean_price).strip()
        item.iron_only_price = request.POST.get('iron_only_price', '').strip() or None
        item.save()
        messages.success(request, 'قیمت بروزرسانی شد.')
    return redirect('panel_pricing')


@staff_required
def price_item_delete(request, item_id):
    item = get_object_or_404(PriceItem, id=item_id)
    if request.method == 'POST':
        item.delete()
        messages.success(request, 'قلم حذف شد.')
    return redirect('panel_pricing')


@staff_required
def courier_requests(request):
    orders = Order.objects.filter(courier_requested=True).select_related('customer').order_by('-created_at')
    return render(request, 'panel/courier_requests.html', {'active': 'courier', 'orders': orders})


@staff_required
def courier_mark_dispatched(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.courier_dispatched = True
        order.save()
        messages.success(request, 'وضعیت پیک به‌روزرسانی شد.')
    return redirect('panel_courier')


@staff_required
def shop_settings_view(request):
    shop = ShopSettings.load()
    if request.method == 'POST':
        shop.name = request.POST.get('name', shop.name).strip()
        shop.tagline = request.POST.get('tagline', shop.tagline).strip()
        shop.phone = request.POST.get('phone', shop.phone).strip()
        shop.address = request.POST.get('address', shop.address).strip()
        shop.save()
        messages.success(request, 'تنظیمات ذخیره شد.')
        return redirect('panel_settings')

    return render(request, 'panel/settings.html', {'active': 'settings', 'shop': shop})
