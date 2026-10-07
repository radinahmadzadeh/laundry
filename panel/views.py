from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from orders.models import (
    Customer,
    Wallet,
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
        item_description = request.POST.get('item_description', '').strip()

        if item_name and item_qty and item_price:
            OrderItem.objects.create(order=order, item_name=item_name, description=item_description, quantity=int(item_qty), price=item_price)
            messages.success(request, 'قلم جدید اضافه شد.')
        else:
            messages.error(request, 'نام، تعداد و قیمت الزامی است.')
        return redirect('panel_order_detail', order_id=order.id)

    context = {
        'active': 'orders',
        'order': order,
        'customers': Customer.objects.order_by('name'),
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
        item_descriptions = request.POST.getlist('item_description[]')

        created_any = False
        for idx, (name, qty, price) in enumerate(zip(item_names, item_qtys, item_prices)):
            description = item_descriptions[idx].strip() if idx < len(item_descriptions) else ''
            if name.strip() and qty.strip() and price.strip():
                OrderItem.objects.create(order=order, item_name=name.strip(), description=description, quantity=int(qty), price=price)
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
    customers = (
        Customer.objects.select_related('wallet')
        .annotate(order_count=Count('order', distinct=True), total_spent=Sum('order__total_price'))
        .all().order_by('name')
    )
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    customer_ids = customers.values('pk')
    summary = Order.objects.filter(customer_id__in=customer_ids).aggregate(total_orders=Count('id'), total_spent=Sum('total_price'))
    context = {
        'active': 'customers',
        'customers': customers,
        'q': q,
        'customer_count': customers.count(),
        'active_count': customers.exclude(password_hash='').count(),
        'total_orders': summary['total_orders'] or 0,
        'total_spent': summary['total_spent'] or 0,
    }
    return render(request, 'panel/customers_list.html', context)


@staff_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer.objects.select_related('wallet'), id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    orders = customer.order_set.order_by('-created_at')
    wallet_transactions = wallet.transactions.select_related('order').all()
    total_spent = orders.filter(is_paid=True).aggregate(total=Sum('total_price'))['total'] or 0
    total_orders = orders.count()
    paid_orders = orders.filter(is_paid=True).count()
    context = {
        'active': 'customers',
        'customer': customer,
        'wallet': wallet,
        'orders': orders,
        'wallet_transactions': wallet_transactions,
        'total_spent': total_spent,
        'total_orders': total_orders,
        'paid_orders': paid_orders,
    }
    return render(request, 'panel/customer_detail.html', context)


@staff_required
def customer_update(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        wallet_balance = request.POST.get('wallet_balance', '').strip()
        if not name or len(name) < 2 or not phone:
            messages.error(request, 'نام و شماره موبایل الزامی است.')
            return redirect('panel_customer_detail', customer_id=customer.id)
        if Customer.objects.exclude(id=customer.id).filter(phone=phone).exists():
            messages.error(request, 'این شماره موبایل برای مشتری دیگری ثبت شده است.')
            return redirect('panel_customer_detail', customer_id=customer.id)
        customer.name, customer.phone = name, phone
        if password:
            from django.contrib.auth.hashers import make_password
            customer.password_hash = make_password(password)
        customer.save()
        wallet, _ = Wallet.objects.get_or_create(customer=customer)
        if wallet_balance:
            try:
                from decimal import Decimal
                value = Decimal(wallet_balance.replace(',', '').replace('٬', '').strip())
                if value < 0: raise ValueError
                wallet.balance = value
                wallet.save()
            except Exception:
                messages.error(request, 'موجودی کیف پول نامعتبر است.')
                return redirect('panel_customer_detail', customer_id=customer.id)
        messages.success(request, 'اطلاعات مشتری با موفقیت ویرایش شد.')
    return redirect('panel_customer_detail', customer_id=customer.id)


@staff_required
def order_update(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        delivery_date = request.POST.get('delivery_date', '').strip()
        if customer_id:
            order.customer = get_object_or_404(Customer, id=customer_id)
        if delivery_date:
            try:
                from datetime import datetime
                order.delivery_date = datetime.strptime(delivery_date, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'تاریخ تحویل نامعتبر است.')
                return redirect('panel_order_detail', order_id=order.id)
        else:
            order.delivery_date = None
        status = request.POST.get('status')
        if status in dict(Order.STATUS_CHOICES):
            order.status = status
        order.is_paid = request.POST.get('is_paid') == 'on'
        order.courier_requested = request.POST.get('courier_requested') == 'on'
        order.courier_dispatched = request.POST.get('courier_dispatched') == 'on'
        if order.courier_dispatched and not order.courier_requested:
            order.courier_requested = True
        order.postal_code = request.POST.get('postal_code', '').strip()
        order.latitude = request.POST.get('latitude', '').strip()
        order.longitude = request.POST.get('longitude', '').strip()
        order.save()
        messages.success(request, 'اطلاعات سفارش با موفقیت ویرایش شد.')
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def order_item_update(request, order_id, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order_id=order_id)
    if request.method == 'POST':
        name = request.POST.get('item_name', '').strip()
        description = request.POST.get('description', '').strip()
        qty = request.POST.get('quantity', '').strip()
        price = request.POST.get('price', '').strip().replace(',', '').replace('٬', '')
        if name and qty.isdigit() and int(qty) > 0 and price.isdigit():
            item.item_name = name
            item.description = description
            item.quantity = int(qty)
            item.price = price
            item.save()
            messages.success(request, 'قلم سفارش ویرایش شد.')
        else:
            messages.error(request, 'نام، تعداد و قیمت قلم را درست وارد کنید.')
    return redirect('panel_order_detail', order_id=order_id)


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

        if category_id and name:
            category = get_object_or_404(PriceCategory, id=category_id)
            order = category.items.count()
            PriceItem.objects.create(
                category=category, name=name,
                dry_clean_price=dry, iron_only_price=iron or None, order=order,
            )
            messages.success(request, 'قیمت جدید اضافه شد.')
        else:
            messages.error(request, 'لطفاً نام لباس را وارد کنید.')
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
        if not order.courier_requested:
            messages.error(request, 'این سفارش درخواست پیک ثبت‌شده‌ای ندارد.')
        else:
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


