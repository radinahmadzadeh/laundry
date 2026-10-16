import re
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from orders.views import FA_TO_EN_DIGITS, MAX_ORDER_TOTAL, normalize_phone, valid_password, valid_phone
from orders.models import (
    Customer,
    OrderReview,
    Wallet,
    WalletTransaction,
    Order,
    OrderItem,
    PriceCategory,
    PriceItem,
    ShopSettings,
)

staff_required = user_passes_test(lambda u: u.is_authenticated and u.is_staff, login_url='panel_login')

MAX_PANEL_QUANTITY = 1000
MAX_ITEM_PRICE = 100_000_000

# Page sizes for the panel lists, so a page stays light however many customers and orders there are.
ORDERS_PER_PAGE = 50
CUSTOMERS_PER_PAGE = 50
CUSTOMER_ORDERS_PER_PAGE = 20
REVIEWS_PER_PAGE = 30
COURIER_HISTORY_LIMIT = 40
DASHBOARD_READY_LIMIT = 15
CUSTOMER_SEARCH_LIMIT = 10
ITEM_INPUT_ERROR = 'تعداد باید عدد صحیح بین ۱ تا ۱۰۰۰ و قیمت عدد صحیح (تومان) باشد.'


def clean_item_numbers(qty, price):
    """(quantity, price) as whole numbers, or None. Accepts Persian digits and thousands separators."""
    qty = str(qty or '').translate(FA_TO_EN_DIGITS).strip()
    price = re.sub(r'[\s,٬]', '', str(price or '').translate(FA_TO_EN_DIGITS))
    if not qty.isdigit() or not price.isdigit():
        return None
    qty, price = int(qty), int(price)
    if not 1 <= qty <= MAX_PANEL_QUANTITY or price > MAX_ITEM_PRICE:
        return None
    return qty, price


def total_within_limit(total):
    # Order.total_price stores at most 10 digits; a larger total breaks every page that lists the order.
    return total <= MAX_ORDER_TOTAL


UNPRICED_READY_WARNING = (
    'سفارش آماده تحویل شد، ولی قیمت برخی اقلام هنوز صفر است؛ '
    'تا قیمت آن‌ها را وارد نکنید، مشتری نمی‌تواند این فاکتور را پرداخت کند.'
)


def warn_if_ready_unpriced(request, order):
    if order.status == 'ready' and order.has_unpriced_items:
        messages.warning(request, UNPRICED_READY_WARNING)


def paginate(request, queryset, per_page, param='page'):
    """One page of a list; a bad or too-high ?page= shows the nearest real page."""
    return Paginator(queryset, per_page).get_page(request.GET.get(param))


def redirect_back(request, fallback, **kwargs):
    """Follow ?next= only when it stays on this site."""
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(fallback, **kwargs)


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
            target = request.POST.get('next') or request.GET.get('next') or ''
            if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(target)
            return redirect('panel_dashboard')
        error = 'نام کاربری یا رمز عبور اشتباه است.'

    return render(request, 'panel/login.html', {'error': error})


def panel_logout(request):
    # POST only, so another site cannot log staff out with a hidden link.
    if request.method == 'POST':
        logout(request)
        return redirect('panel_login')
    return redirect('panel_dashboard')


@staff_required
def dashboard(request):
    # A time range (not created_at__date) so the created_at index is used.
    start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    today = Order.objects.filter(created_at__gte=start, created_at__lt=start + timedelta(days=1)).aggregate(
        count=Count('id'), revenue=Sum('total_price', filter=Q(is_paid=True)),
    )

    counts = dict(Order.objects.values_list('status').annotate(n=Count('id')).order_by())
    status_summary = [
        {'code': code, 'label': label, 'count': counts.get(code, 0)}
        for code, label in Order.STATUS_CHOICES
    ]

    ready_orders = Order.objects.filter(status='ready').select_related('customer').order_by('-created_at')[:DASHBOARD_READY_LIMIT]
    pending_pickup = Order.objects.filter(courier_requested=True, courier_dispatched=False).count()
    pending_delivery = Order.objects.filter(delivery_courier_requested=True, delivery_courier_dispatched=False).count()

    context = {
        'active': 'dashboard',
        'orders_today_count': today['count'],
        'revenue_today': today['revenue'] or 0,
        'status_summary': status_summary,
        'ready_orders': ready_orders,
        'ready_count': counts.get('ready', 0),
        'pending_pickup_count': pending_pickup,
        'pending_delivery_count': pending_delivery,
        'pending_courier_count': pending_pickup + pending_delivery,
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
        'orders': paginate(request, orders, ORDERS_PER_PAGE),
        'status_choices': Order.STATUS_CHOICES,
        'current_status': status,
        'q': q,
    }
    return render(request, 'panel/orders_list.html', context)


@staff_required
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.select_related('customer'), id=order_id)

    if request.method == 'POST':
        item_name = request.POST.get('item_name_manual', '').strip() or request.POST.get('item_name', '').strip()
        item_qty = request.POST.get('item_qty')
        item_price = request.POST.get('item_price')
        item_description = request.POST.get('item_description', '').strip()

        numbers = clean_item_numbers(item_qty, item_price)
        if not (item_name and item_qty and item_price):
            messages.error(request, 'نام، تعداد و قیمت الزامی است.')
        elif not numbers:
            messages.error(request, ITEM_INPUT_ERROR)
        elif not total_within_limit(order.subtotal_amount + numbers[0] * numbers[1]):
            messages.error(request, 'مبلغ این سفارش بیش از حد مجاز می‌شود.')
        else:
            OrderItem.objects.create(order=order, item_name=item_name[:100], description=item_description,
                                     quantity=numbers[0], price=numbers[1])
            messages.success(request, 'قلم جدید اضافه شد.')
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
            warn_if_ready_unpriced(request, order)

    return redirect_back(request, 'panel_order_detail', order_id=order.id)


@staff_required
def order_toggle_paid(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        order.is_paid = not order.is_paid
        order.save()
        messages.success(request, 'وضعیت پرداخت بروزرسانی شد.')

    return redirect_back(request, 'panel_order_detail', order_id=order.id)


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
    price_items = PriceItem.objects.select_related('category').order_by('category__order', 'order')

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        new_name = request.POST.get('new_customer_name', '').strip()
        new_phone = normalize_phone(request.POST.get('new_customer_phone', ''))
        delivery_days = request.POST.get('delivery_days', '').strip()

        if customer_id:
            customer = get_object_or_404(Customer, id=customer_id)
        elif new_name and new_phone:
            if not valid_phone(new_phone):
                messages.error(request, 'شماره موبایل مشتری باید با ۰۹ شروع شود و ۱۱ رقم باشد.')
                return redirect('panel_order_create')
            # Same normalized number → same customer, so their online account sees this order too.
            customer, _ = Customer.objects.get_or_create(phone=new_phone, defaults={'name': new_name[:100]})
        else:
            messages.error(request, 'لطفاً مشتری را انتخاب یا اطلاعات مشتری جدید را کامل وارد کنید.')
            return redirect('panel_order_create')

        delivery_date = None
        delivery_days = delivery_days.translate(FA_TO_EN_DIGITS)
        if delivery_days.isdigit() and int(delivery_days) <= 365:
            delivery_date = timezone.localdate() + timedelta(days=int(delivery_days))

        item_names = request.POST.getlist('item_name[]')
        item_qtys = request.POST.getlist('item_qty[]')
        item_prices = request.POST.getlist('item_price[]')
        item_descriptions = request.POST.getlist('item_description[]')

        lines = []
        for idx, (name, qty, price) in enumerate(zip(item_names, item_qtys, item_prices)):
            if not (name.strip() and qty.strip() and price.strip()):
                continue
            numbers = clean_item_numbers(qty, price)
            if not numbers:
                messages.error(request, f'ردیف «{name.strip()}»: {ITEM_INPUT_ERROR}')
                return redirect('panel_order_create')
            description = item_descriptions[idx].strip() if idx < len(item_descriptions) else ''
            lines.append((name.strip()[:100], description, *numbers))

        if not lines:
            messages.error(request, 'حداقل یک قلم لباس باید اضافه شود.')
            return redirect('panel_order_create')
        if not total_within_limit(sum(qty * price for _, _, qty, price in lines)):
            messages.error(request, 'مبلغ این سفارش بیش از حد مجاز است.')
            return redirect('panel_order_create')

        with transaction.atomic():
            order = Order.objects.create(customer=customer, delivery_date=delivery_date)
            for name, description, qty, price in lines:
                OrderItem.objects.create(order=order, item_name=name, description=description, quantity=qty, price=price)

        messages.success(request, f'سفارش #{order.id} با موفقیت ثبت شد.')
        return redirect('panel_order_detail', order_id=order.id)

    context = {
        'active': 'order_create',
        'price_items': price_items,
    }
    return render(request, 'panel/order_form.html', context)


@staff_required
def customers_list(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.order_by('name', 'id')
    if q:
        customers = customers.filter(Q(name__icontains=q) | Q(phone__icontains=q))

    summary = Order.objects.filter(customer_id__in=customers.values('pk')).aggregate(total_orders=Count('id'), total_spent=Sum('total_price'))
    page = paginate(request, customers, CUSTOMERS_PER_PAGE)
    # Order totals only for the customers on this page (a GROUP BY over every customer gets slow).
    customer_orders = Order.objects.filter(customer=OuterRef('pk')).order_by().values('customer')
    page.object_list = list(
        Customer.objects.filter(pk__in=[c.pk for c in page.object_list])
        .select_related('wallet')
        .annotate(
            order_count=Coalesce(Subquery(customer_orders.annotate(n=Count('id')).values('n')), 0),
            total_spent=Coalesce(Subquery(customer_orders.annotate(t=Sum('total_price')).values('t')), 0,
                                 output_field=IntegerField()),
        )
        .order_by('name', 'id')
    )
    context = {
        'active': 'customers',
        'customers': page,
        'q': q,
        'customer_count': page.paginator.count,
        'active_count': customers.exclude(password_hash='').count(),
        'total_orders': summary['total_orders'] or 0,
        'total_spent': summary['total_spent'] or 0,
    }
    return render(request, 'panel/customers_list.html', context)


@staff_required
def customer_search(request):
    """A few customers matching a name or phone, for the customer picker on the order pages."""
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'results': []})
    phone = q.translate(FA_TO_EN_DIGITS)
    customers = Customer.objects.filter(Q(name__icontains=q) | Q(phone__contains=phone)).order_by('name', 'id')
    results = [{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers[:CUSTOMER_SEARCH_LIMIT]]
    return JsonResponse({'results': results})


@staff_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer.objects.select_related('wallet'), id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    orders = customer.order_set.order_by('-created_at')
    totals = orders.aggregate(
        total_orders=Count('id'), paid_orders=Count('id', filter=Q(is_paid=True)),
        total_spent=Sum('total_price', filter=Q(is_paid=True)),
    )
    context = {
        'active': 'customers',
        'customer': customer,
        'wallet': wallet,
        'orders': paginate(request, orders, CUSTOMER_ORDERS_PER_PAGE),
        'wallet_transactions': paginate(request, wallet.transactions.select_related('order'), CUSTOMER_ORDERS_PER_PAGE, 'tx_page'),
        'total_spent': totals['total_spent'] or 0,
        'total_orders': totals['total_orders'],
        'paid_orders': totals['paid_orders'],
    }
    return render(request, 'panel/customer_detail.html', context)


@staff_required
def customer_update(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = normalize_phone(request.POST.get('phone', ''))
        password = request.POST.get('password', '')
        raw_wallet_balance = request.POST.get('wallet_balance', '').strip()
        wallet_value = None

        if not name or len(name) < 2 or not phone:
            messages.error(request, 'نام و شماره موبایل الزامی است.')
            return redirect('panel_customer_detail', customer_id=customer.id)
        if not valid_phone(phone):
            messages.error(request, 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.')
            return redirect('panel_customer_detail', customer_id=customer.id)
        if password and not valid_password(password):
            messages.error(request, 'رمز عبور مشتری باید حداقل ۸ کاراکتر باشد.')
            return redirect('panel_customer_detail', customer_id=customer.id)
        if Customer.objects.exclude(id=customer.id).filter(phone=phone).exists():
            messages.error(request, 'این شماره موبایل برای مشتری دیگری ثبت شده است.')
            return redirect('panel_customer_detail', customer_id=customer.id)

        if raw_wallet_balance:
            digit_map = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
            normalized_balance = raw_wallet_balance.translate(digit_map)
            for separator in (',', '٬', '،', '.', '٫', ' '):
                normalized_balance = normalized_balance.replace(separator, '')
            if not normalized_balance.isdigit() or len(normalized_balance) > 12:
                messages.error(request, 'موجودی کیف پول نامعتبر است. مبلغ را به تومان و بدون علامت منفی وارد کنید.')
                return redirect('panel_customer_detail', customer_id=customer.id)
            from decimal import Decimal
            wallet_value = Decimal(normalized_balance)

        if password:
            from django.contrib.auth.hashers import make_password
            customer.password_hash = make_password(password)

        digit_map_fa = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        customer.address = request.POST.get('address', '').strip()[:1000]
        customer.address_latitude = request.POST.get('address_latitude', '').strip()
        customer.address_longitude = request.POST.get('address_longitude', '').strip()
        customer.address_postal_code = request.POST.get('address_postal_code', '').strip().translate(digit_map_fa)

        with transaction.atomic():
            customer.name, customer.phone = name, phone
            customer.save()
            wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=customer)
            if wallet_value is not None and wallet_value != wallet.balance:
                difference = wallet_value - wallet.balance
                wallet.balance = wallet_value
                wallet.save(update_fields=['balance', 'updated_at'])
                WalletTransaction.objects.create(
                    wallet=wallet,
                    transaction_type='credit' if difference > 0 else 'debit',
                    amount=abs(difference),
                    description=(
                        'شارژ دستی توسط مدیریت'
                        if difference > 0
                        else 'کاهش دستی موجودی توسط مدیریت'
                    ),
                )
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
        locations = {}
        for prefix, label in (('', 'دریافت'), ('delivery_', 'تحویل')):
            lat = request.POST.get(f'{prefix}latitude', '').strip()
            lng = request.POST.get(f'{prefix}longitude', '').strip()
            postal = re.sub(r'[\s\-]', '', request.POST.get(f'{prefix}postal_code', '').translate(FA_TO_EN_DIGITS))
            if (lat or lng) and not Order._map_point(lat.translate(FA_TO_EN_DIGITS), lng.translate(FA_TO_EN_DIGITS)):
                messages.error(request, f'مختصات پیک {label} نامعتبر است.')
                return redirect('panel_order_detail', order_id=order.id)
            if postal and (not postal.isdigit() or len(postal) != 10):
                messages.error(request, f'کد پستی پیک {label} باید ۱۰ رقم باشد.')
                return redirect('panel_order_detail', order_id=order.id)
            locations[prefix] = (lat.translate(FA_TO_EN_DIGITS), lng.translate(FA_TO_EN_DIGITS), postal)
        order.latitude, order.longitude, order.postal_code = locations['']
        order.delivery_latitude, order.delivery_longitude, order.delivery_postal_code = locations['delivery_']
        order.save()
        messages.success(request, 'اطلاعات سفارش با موفقیت ویرایش شد.')
        warn_if_ready_unpriced(request, order)
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def order_item_update(request, order_id, item_id):
    item = get_object_or_404(OrderItem, id=item_id, order_id=order_id)
    if request.method == 'POST':
        name = request.POST.get('item_name', '').strip()
        description = request.POST.get('description', '').strip()
        numbers = clean_item_numbers(request.POST.get('quantity'), request.POST.get('price'))
        other_lines = item.order.subtotal_amount - item.price * item.quantity
        if not name or not numbers:
            messages.error(request, 'نام، تعداد و قیمت قلم را درست وارد کنید. ' + ITEM_INPUT_ERROR)
        elif not total_within_limit(other_lines + numbers[0] * numbers[1]):
            messages.error(request, 'مبلغ این سفارش بیش از حد مجاز می‌شود.')
        else:
            item.item_name = name[:100]
            item.description = description
            item.quantity, item.price = numbers
            item.save()
            messages.success(request, 'قلم سفارش ویرایش شد.')
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
def order_courier_state(request, order_id):
    """Set one courier flow (pickup/delivery) to one state: none, requested, dispatched,
    or 'unset' (neutral — nothing selected)."""
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        kind = request.POST.get('kind')
        state = request.POST.get('state')
        if kind in ('pickup', 'delivery') and state in ('unset', 'none', 'requested', 'dispatched'):
            requested = state in ('requested', 'dispatched')
            dispatched = state == 'dispatched'
            declined = state == 'none'
            if kind == 'pickup':
                order.courier_requested, order.courier_dispatched, order.courier_declined = requested, dispatched, declined
            else:
                order.delivery_courier_requested, order.delivery_courier_dispatched, order.delivery_courier_declined = requested, dispatched, declined
            order.save()
            messages.success(request, 'وضعیت پیک خنثی شد.' if state == 'unset' else 'وضعیت پیک ذخیره شد.')
    return redirect('panel_order_detail', order_id=order.id)


@staff_required
def courier_requests(request):
    """Both courier request kinds, each tagged so pickup (dirty clothes) and delivery (clean clothes) are never mixed up."""
    # Every request still waiting for a courier, plus the latest ones already sent (not the whole history).
    pickups = Order.objects.filter(courier_requested=True).select_related('customer')
    deliveries = Order.objects.filter(delivery_courier_requested=True).select_related('customer')
    pickups = [*pickups.filter(courier_dispatched=False), *pickups.filter(courier_dispatched=True).order_by('-id')[:COURIER_HISTORY_LIMIT]]
    deliveries = [*deliveries.filter(delivery_courier_dispatched=False),
                  *deliveries.filter(delivery_courier_dispatched=True).order_by('-id')[:COURIER_HISTORY_LIMIT]]
    requests_list = []
    for order in pickups:
        requests_list.append({
            'kind': 'pickup', 'order': order, 'postal': order.postal_code, 'address': order.address,
            'point': order.pickup_map_point, 'dispatched': order.courier_dispatched,
        })
    for order in deliveries:
        requests_list.append({
            'kind': 'delivery', 'order': order, 'postal': order.delivery_postal_code, 'address': order.delivery_address,
            'point': order.delivery_map_point, 'dispatched': order.delivery_courier_dispatched,
        })
    requests_list.sort(key=lambda r: (r['dispatched'], -r['order'].id))
    return render(request, 'panel/courier_requests.html', {'active': 'courier', 'requests': requests_list})


@staff_required
def courier_mark_dispatched(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        kind = request.POST.get('kind', 'pickup')
        if kind == 'delivery':
            if not order.delivery_courier_requested:
                messages.error(request, 'این سفارش درخواست پیک تحویل ثبت‌شده‌ای ندارد.')
            else:
                order.delivery_courier_dispatched = True
                order.delivery_courier_declined = False
                order.save()
                messages.success(request, 'وضعیت پیک تحویل لباس تمیز به‌روزرسانی شد.')
        else:
            if not order.courier_requested:
                messages.error(request, 'این سفارش درخواست پیک دریافت ثبت‌شده‌ای ندارد.')
            else:
                order.courier_dispatched = True
                order.courier_declined = False
                order.save()
                messages.success(request, 'وضعیت پیک دریافت لباس کثیف به‌روزرسانی شد.')
    return redirect('panel_courier')


@staff_required
def reviews_list(request):
    reviews = OrderReview.objects.select_related('customer', 'order')
    rating = request.GET.get('rating', '')
    if rating.isdigit():
        reviews = reviews.filter(rating=int(rating))
    stats = OrderReview.objects.aggregate(
        avg=Avg('rating'), count=Count('id'), low=Count('id', filter=Q(rating__lte=2)),
        featured=Count('id', filter=Q(is_hidden=False, rating__gte=OrderReview.FEATURE_MIN_RATING) & ~Q(comment='')),
    )
    return render(request, 'panel/reviews_list.html', {
        'active': 'reviews',
        'reviews': paginate(request, reviews, REVIEWS_PER_PAGE),
        'current_rating': rating,
        'review_avg': round(stats['avg'] or 0, 1),
        'review_count': stats['count'],
        'featured_count': stats['featured'],
        'low_count': stats['low'],
    })


@staff_required
def review_toggle_hidden(request, review_id):
    review = get_object_or_404(OrderReview, id=review_id)
    if request.method == 'POST':
        review.is_hidden = not review.is_hidden
        review.save(update_fields=['is_hidden'])
        messages.success(request, 'نظر از سایت پنهان شد.' if review.is_hidden else 'نظر تأیید شد و در سایت قابل نمایش است.')
    return redirect_back(request, 'panel_reviews')


def parse_map_point(text):
    """(lat, lng) from '35.72, 51.29' or from a pasted Neshan/Google Maps link; None if not found."""
    text = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٫،', '0123456789.,'))
    lat_match = re.search(r'lat=(-?\d+(?:\.\d+)?)', text)
    lng_match = re.search(r'lng=(-?\d+(?:\.\d+)?)', text)
    if lat_match and lng_match:
        numbers = [lat_match.group(1), lng_match.group(1)]
    else:
        numbers = re.findall(r'-?\d+\.\d+', text)[:2]
    if len(numbers) != 2:
        return None
    lat, lng = float(numbers[0]), float(numbers[1])
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


@staff_required
def shop_settings_view(request):
    shop = ShopSettings.load()
    if request.method == 'POST':
        shop.name = request.POST.get('name', shop.name).strip()
        shop.tagline = request.POST.get('tagline', shop.tagline).strip()
        shop.phone = request.POST.get('phone', shop.phone).strip()
        shop.address = request.POST.get('address', shop.address).strip()
        location = request.POST.get('location', '').strip()
        if not location:
            shop.latitude = shop.longitude = None
        else:
            point = parse_map_point(location)
            if point is None:
                messages.error(request, 'موقعیت فروشگاه شناخته نشد؛ عرض و طول جغرافیایی را مثل «35.72, 51.29» وارد کنید.')
                return redirect('panel_settings')
            shop.latitude, shop.longitude = point
        shop.save()
        messages.success(request, 'تنظیمات ذخیره شد.')
        return redirect('panel_settings')

    return render(request, 'panel/settings.html', {'active': 'settings', 'shop': shop})


