import json
import math
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import Http404, HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.utils.http import url_has_allowed_host_and_scheme
from django.db import IntegrityError, transaction
import re
from django.utils import timezone
from .models import Order, OrderItem, OrderReview, Customer, ShopSettings, PriceCategory, PriceItem, Wallet, WalletTransaction
from .templatetags.fa_format import fa_digits, toman
from .postal import lookup_postal_code, normalize_postal, postal_format_error
from .insights import customer_insights
from .loyalty import loyalty_status
from django.db.models import Avg, Count, F


FA_TO_EN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def session_customer_id(request):
    """The logged-in customer's id, or None."""
    if request.session.get('customer_logged_in') and request.session.get('customer_id'):
        return request.session['customer_id']
    return None


def customer_login_redirect(request):
    """Send a guest to the customer login page and bring them back here afterwards."""
    return redirect_to_login(request.get_full_path(), login_url=reverse('customer_login'))

def home(request):
    customer_id = request.session.get('customer_id')
    customer_logged_in = bool(request.session.get('customer_logged_in') and customer_id)
    phone_number = None
    customer_name = None
    order_id = request.GET.get('order_id')
    orders = None
    customer_orders = None
    wallet = None
    loyalty = None
    tracking_error = None

    if customer_logged_in:
        customer = Customer.objects.filter(id=customer_id).first()
        if customer:
            phone_number = customer.phone
            customer_name = customer.name
            wallet, _ = Wallet.objects.get_or_create(customer=customer)
            loyalty = loyalty_status(customer)
            customer_orders = list(
                Order.objects.filter(customer=customer)
                .select_related('review')
                .prefetch_related('orderitem_set')
                .order_by('-created_at')[:30]
            )
            if order_id is not None:
                normalized_order_id = str(order_id).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')).strip()
                if not normalized_order_id.isdigit() or int(normalized_order_id) <= 0:
                    tracking_error = 'شماره فاکتور باید یک عدد مثبت باشد.'
                else:
                    orders = Order.objects.filter(
                        customer=customer,
                        id=int(normalized_order_id),
                    ).select_related('review').prefetch_related('orderitem_set')
                    if not orders.exists():
                        tracking_error = 'شماره فاکتور اشتباه است یا این فاکتور متعلق به حساب شما نیست.'
        else:
            request.session.pop('customer_id', None)
            request.session.pop('customer_logged_in', None)
            customer_logged_in = False

    courier_watch = {}
    for o in list(customer_orders or []) + list(orders or []):
        courier_watch[str(o.id)] = courier_state(o)

    visible_reviews = OrderReview.objects.filter(is_hidden=False)
    review_stats = visible_reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    featured_reviews = list(
        visible_reviews.filter(rating__gte=OrderReview.FEATURE_MIN_RATING)
        .exclude(comment='').select_related('customer')[:6]
    )

    shop = ShopSettings.load()
    categories = list(PriceCategory.objects.prefetch_related('items').all())
    return render(request, 'home.html', {
        'orders': orders,
        'customer_orders': customer_orders,
        'phone': phone_number,
        'customer_name': customer_name,
        'customer_logged_in': customer_logged_in,
        'shop_name': shop.name,
        'shop_tagline': shop.tagline,
        'shop_phone': shop.phone,
        'shop_address': shop.address,
        'shop_map_point': shop.map_point,
        'categories': categories,
        'wallet': wallet,
        'loyalty': loyalty,
        'tracking_error': tracking_error,
        'saved_address': customer if customer_logged_in and customer.has_saved_address else None,
        'courier_watch': courier_watch,
        'status_labels': dict(Order.STATUS_CHOICES),
        'featured_reviews': featured_reviews,
        'review_avg': round(review_stats['avg'] or 0, 1),
        'review_count': review_stats['count'],
        'review_tags': OrderReview.TAG_CHOICES,
    })


def courier_state(order):
    """Order status plus courier flags the customer page watches: [requested, dispatched] for pickup and delivery."""
    return {
        'status': order.status,
        'reviewed': hasattr(order, 'review'),
        'pickup': [order.courier_requested, order.courier_dispatched],
        'delivery': [order.delivery_courier_requested, order.delivery_courier_dispatched],
    }


def courier_status(request):
    """Lightweight poll so the customer page can show 'courier dispatched' as soon as the admin marks it."""
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return JsonResponse({'status': 'error'}, status=403)
    ids = [i for i in request.GET.get('ids', '').split(',') if i.isdigit()][:50]
    orders = Order.objects.filter(customer_id=customer_id, id__in=ids).select_related('review')
    return JsonResponse({'status': 'success', 'orders': {str(o.id): courier_state(o) for o in orders}})

def account_page(request):
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'profile':
            name = request.POST.get('name', '').strip()
            phone = normalize_phone(request.POST.get('phone'))
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            # The phone number is the login: changing it (or the password) needs the current password.
            needs_password = bool(new_password) or phone != customer.phone
            error = None
            if len(name) < 2:
                error = 'لطفاً نام و نام‌خانوادگی معتبر وارد کنید.'
            elif len(name) > MAX_NAME_LENGTH:
                error = f'نام و نام‌خانوادگی حداکثر می‌تواند {fa_digits(MAX_NAME_LENGTH)} حرف باشد.'
            elif not valid_phone(phone):
                error = 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.'
            elif Customer.objects.exclude(id=customer.id).filter(phone=phone).exists():
                error = 'این شماره موبایل برای حساب دیگری ثبت شده است.'
            elif needs_password and (not customer.password_hash or not check_password(current_password, customer.password_hash)):
                error = 'برای تغییر شماره موبایل یا رمز عبور، رمز عبور فعلی را درست وارد کنید.'
            elif new_password and not valid_password(new_password):
                error = 'رمز عبور جدید باید حداقل ۸ کاراکتر باشد.'
            if error:
                messages.error(request, error)
            else:
                customer.name = name
                customer.phone = phone
                if new_password:
                    customer.password_hash = make_password(new_password)
                customer.save()
                if new_password:
                    request.session.cycle_key()
                messages.success(request, 'اطلاعات حساب شما ذخیره شد.')
        elif form_type == 'address':
            address = request.POST.get('address', '').strip()[:1000]
            location, error = clean_courier_location(
                request.POST.get('lat', ''), request.POST.get('lng', ''), request.POST.get('postal', '')
            )
            if error:
                messages.error(request, error)
            else:
                customer.address = address
                customer.address_latitude, customer.address_longitude, customer.address_postal_code = location
                customer.save()
                messages.success(request, 'آدرس شما ذخیره شد و در ثبت سفارش‌ها قابل استفاده است.')
        elif form_type == 'address_delete':
            customer.address = customer.address_latitude = customer.address_longitude = customer.address_postal_code = ''
            customer.save()
            messages.success(request, 'آدرس ثبت‌شده حذف شد.')
        return redirect('account')

    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    return render(request, 'account.html', {
        'customer': customer, 'wallet': wallet, 'insights': customer_insights(customer), 'loyalty': loyalty_status(customer),
    })


def wallet_page(request):
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    customer = get_object_or_404(Customer, id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    transactions = wallet.transactions.select_related('order')[:30]
    return render(request, 'wallet.html', {'wallet': wallet, 'transactions': transactions, 'customer': customer})


def wallet_pay_order(request, order_id):
    """Pay an order from the wallet. POST only (with CSRF): a link or prefetch must never spend money."""
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    invoice_url = f"{reverse('home')}?order_id={order_id}#track-section"
    if request.method != 'POST':
        return redirect(invoice_url)

    order = get_object_or_404(Order, id=order_id, customer_id=customer_id)
    result = pay_order_from_wallet(order, customer_id)
    if result == 'paid':
        messages.success(request, f'فاکتور شماره {fa_digits(order.id)} به مبلغ {toman(order.total_price)} تومان از کیف پول پرداخت شد.')
    elif result == 'already_paid':
        messages.info(request, 'این فاکتور قبلاً پرداخت شده است.')
    elif result == 'invalid':
        messages.error(request, 'مبلغ این فاکتور هنوز مشخص نشده است؛ پس از اعلام قیمت می‌توانید آن را پرداخت کنید.')
    elif result == 'not_ready':
        messages.info(request, PRICE_PENDING_MESSAGE)
    else:
        balance = Wallet.objects.filter(customer_id=customer_id).values_list('balance', flat=True).first() or 0
        messages.error(
            request,
            f'موجودی کیف پول کافی نیست. موجودی فعلی: {toman(balance)} تومان، مبلغ فاکتور: {toman(order.total_price)} تومان.',
        )
    return redirect(invoice_url)


MIN_TOPUP = 10_000
MAX_TOPUP = 50_000_000


def parse_toman_amount(raw):
    """'۵۰۰٬۰۰۰' / '500,000' / '500.000' → 500000. Anything with a real decimal part is rejected (None)."""
    text = re.sub(r'[\s,٬،]', '', str(raw or '').translate(FA_TO_EN_DIGITS))
    if re.fullmatch(r'\d{1,3}(\.\d{3})+', text):  # dots used as thousands separators
        text = text.replace('.', '')
    return int(text) if text.isdigit() else None


def recharge_wallet(request):
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    if request.method != 'POST':
        return redirect('wallet')
    amount = parse_toman_amount(request.POST.get('amount'))
    if amount is None:
        messages.error(request, 'مبلغ را فقط به‌صورت عدد صحیح و به تومان وارد کنید (بدون اعشار).')
        return redirect('wallet')
    if amount < MIN_TOPUP:
        messages.error(request, f'حداقل مبلغ شارژ کیف پول {toman(MIN_TOPUP)} تومان است.')
        return redirect('wallet')
    if amount > MAX_TOPUP:
        messages.error(request, f'حداکثر مبلغ شارژ در هر بار {toman(MAX_TOPUP)} تومان است.')
        return redirect('wallet')

    customer = get_object_or_404(Customer, id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    transaction_obj = WalletTransaction.objects.create(
        wallet=wallet, transaction_type='credit', amount=amount,
        description='شارژ کیف پول از طریق درگاه'
    )
    shop = ShopSettings.load()
    status_code, data, errors = zarinpal_post(ZP_API_REQUEST, {
        'merchant_id': MERCHANT,
        'amount': amount * 10,
        'description': f'شارژ کیف پول {customer.name} - {shop.name}',
        'callback_url': request.build_absolute_uri(f"{reverse('verify_wallet')}?transaction_id={transaction_obj.id}"),
    })
    if status_code == 200 and data.get('code') == 100 and data.get('authority'):
        transaction_obj.authority = data['authority']
        transaction_obj.save(update_fields=['authority'])
        return redirect(ZP_API_STARTPAY.format(authority=data['authority']))
    transaction_obj.delete()
    if status_code is None:
        messages.error(request, 'ارتباط با درگاه پرداخت برقرار نشد؛ چند دقیقه دیگر دوباره تلاش کنید.')
    else:
        code = errors.get('code') if isinstance(errors, dict) else None
        messages.error(request, 'درگاه پرداخت درخواست شارژ را نپذیرفت؛ لطفاً دوباره تلاش کنید.'
                       + (f' (کد خطای درگاه: {fa_digits(code)})' if code else ''))
    return redirect('wallet')


def credit_wallet_transaction(transaction_obj, ref_id):
    """Add a verified top-up to the wallet exactly once.

    The gateway may call back several times (refresh, double tap, parallel requests). Only the
    request whose conditional UPDATE claims the still-unreferenced transaction adds the money.
    """
    with transaction.atomic():
        claimed = WalletTransaction.objects.filter(pk=transaction_obj.pk, reference_id='').update(
            reference_id=ref_id or 'verified'
        )
        if claimed:
            Wallet.objects.filter(pk=transaction_obj.wallet_id).update(
                balance=F('balance') + transaction_obj.amount, updated_at=timezone.now()
            )
    return bool(claimed)


def verify_wallet(request):
    transaction_id = str(request.GET.get('transaction_id') or '')
    authority = request.GET.get('Authority')
    status = request.GET.get('Status')
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    transaction_obj = None
    if transaction_id.isdigit() and authority:
        transaction_obj = WalletTransaction.objects.filter(
            id=int(transaction_id),
            authority=authority,
            transaction_type='credit',
            wallet__customer_id=customer_id,
        ).first()
    if not transaction_obj:
        messages.error(request, 'اطلاعات بازگشت از درگاه معتبر نیست؛ موجودی کیف پول تغییری نکرد.')
        return redirect('wallet')
    if transaction_obj.reference_id:
        messages.info(request, 'این شارژ قبلاً به کیف پول شما اضافه شده است.')
        return redirect('wallet')
    if status != 'OK':
        messages.warning(request, 'پرداخت لغو شد یا ناموفق بود؛ مبلغی به کیف پول شما اضافه یا از آن کم نشد.')
        return redirect('wallet')

    status_code, data, _ = zarinpal_post(
        ZP_API_VERIFY, {'merchant_id': MERCHANT, 'amount': int(transaction_obj.amount) * 10, 'authority': authority}
    )
    if status_code == 200 and data.get('code') in (100, 101):
        ref_id = str(data.get('ref_id') or '')
        if credit_wallet_transaction(transaction_obj, ref_id):
            messages.success(
                request,
                f'کیف پول شما {toman(transaction_obj.amount)} تومان شارژ شد.'
                + (f' کد پیگیری: {fa_digits(ref_id)}' if ref_id else ''),
            )
        else:
            messages.info(request, 'این شارژ قبلاً به کیف پول شما اضافه شده است.')
        return redirect('wallet')
    messages.error(
        request,
        'شارژ کیف پول تأیید نشد. اگر مبلغی از حساب بانکی شما کم شده، طبق قوانین بانکی حداکثر تا ۷۲ ساعت برمی‌گردد؛ '
        'در غیر این صورت با پشتیبانی تماس بگیرید.',
    )
    return redirect('wallet')

def normalize_phone(raw):
    digits = re.sub(r'\D', '', str(raw or '').translate(FA_TO_EN_DIGITS))
    if digits.startswith('0098'):
        digits = '0' + digits[4:]
    elif digits.startswith('98'):
        digits = '0' + digits[2:]
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '0' + digits
    return digits


def valid_phone(phone):
    return len(phone) == 11 and phone.startswith('09')


def valid_password(password):
    # Keep registration simple: accept any password of at least 8 characters.
    return len(password) >= 8


MAX_NAME_LENGTH = 100
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
_dummy_password_hash = None


def burn_password_check(password):
    """Spend the same time as a real password check, so response time does not reveal registered numbers."""
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = make_password('timing-equalizer-password')
    check_password(password, _dummy_password_hash)


def safe_next_url(request, fallback='home'):
    """The ?next= target if it points back into this site, otherwise the fallback page."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return reverse(fallback)


def log_customer_in(request, customer):
    request.session['customer_id'] = customer.id
    request.session['customer_logged_in'] = True
    request.session.cycle_key()


def shop_contact_context():
    shop = ShopSettings.load()
    return {'shop_name': shop.name, 'shop_phone': shop.phone}


def customer_login(request):
    error = None
    phone_value = ''
    if request.method == 'POST':
        phone = normalize_phone(request.POST.get('phone'))
        phone_value = phone
        password = request.POST.get('password', '')
        lock_key = f'customer-login-failures:{phone}'
        if valid_phone(phone) and cache.get(lock_key, 0) >= LOGIN_MAX_FAILURES:
            error = 'به دلیل چند تلاش ناموفق پشت‌سرهم، ورود با این شماره تا ۱۵ دقیقه دیگر ممکن نیست.'
        elif valid_phone(phone) and password:
            customer = Customer.objects.filter(phone=phone).first()
            if customer and customer.password_hash:
                ok = check_password(password, customer.password_hash)
            else:
                burn_password_check(password)
                ok = False
            if ok:
                cache.delete(lock_key)
                log_customer_in(request, customer)
                return redirect(safe_next_url(request))
            try:
                cache.incr(lock_key)
            except ValueError:
                cache.set(lock_key, 1, LOGIN_LOCK_SECONDS)
            error = 'شماره موبایل یا رمز عبور صحیح نیست.'
        else:
            error = 'شماره موبایل یا رمز عبور صحیح نیست.'
    return render(request, 'customer_login.html', {
        'error': error, 'phone_value': phone_value, 'next': safe_next_url(request), **shop_contact_context(),
    })


def customer_register(request):
    error = None
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = normalize_phone(request.POST.get('phone'))
        password = request.POST.get('password', '')
        existing = Customer.objects.filter(phone=phone).first() if valid_phone(phone) else None

        if len(name) < 2:
            error = 'لطفاً نام و نام‌خانوادگی معتبر وارد کنید.'
        elif len(name) > MAX_NAME_LENGTH:
            error = f'نام و نام‌خانوادگی حداکثر می‌تواند {fa_digits(MAX_NAME_LENGTH)} حرف باشد.'
        elif not valid_phone(phone):
            error = 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.'
        elif existing and existing.password_hash:
            error = 'با این شماره موبایل قبلاً حساب ساخته شده است؛ وارد حساب شوید. اگر رمز عبور را فراموش کرده‌اید، با فروشگاه تماس بگیرید.'
        elif existing:
            # Made in the shop (no password yet). Without SMS verification we cannot prove ownership online,
            # so the shop activates it — otherwise anyone could take over someone else's orders.
            error = 'این شماره قبلاً در فروشگاه ثبت شده است. برای فعال‌سازی حساب و دیدن سفارش‌های قبلی، با فروشگاه تماس بگیرید تا رمز عبور برایتان تنظیم شود.'
        elif not valid_password(password):
            error = 'رمز عبور باید حداقل ۸ کاراکتر باشد.'
        else:
            customer = Customer.objects.create(name=name, phone=phone, password_hash=make_password(password))
            Wallet.objects.get_or_create(customer=customer)
            log_customer_in(request, customer)
            return redirect(safe_next_url(request))
    return render(request, 'customer_register.html', {'error': error, 'next': safe_next_url(request), **shop_contact_context()})

def customer_logout(request):
    # POST only, so another site cannot log the customer out with a hidden link.
    if request.method == 'POST':
        request.session.pop('customer_id', None)
        request.session.pop('customer_logged_in', None)
        request.session.cycle_key()
    return redirect('home')

def print_receipt(request, order_id):
    # A receipt holds the customer's name, phone and items: only its owner or shop staff may see it.
    is_staff = request.user.is_authenticated and request.user.is_staff
    customer_id = session_customer_id(request)
    if not is_staff and not customer_id:
        return customer_login_redirect(request)
    order = get_object_or_404(Order.objects.select_related('customer'), id=order_id)
    if not is_staff and order.customer_id != customer_id:
        raise Http404
    shop = ShopSettings.load()
    return render(request, 'receipt.html', {
        'order': order,
        'shop_name': shop.name,
        'shop_tagline': shop.tagline,
        'shop_phone': shop.phone,
        'shop_address': shop.address,
        'is_staff_view': is_staff and order.customer_id != customer_id,
    })

MERCHANT = '00000000-0000-0000-0000-000000000000'
ZP_API_REQUEST = "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
ZP_API_VERIFY = "https://sandbox.zarinpal.com/pg/v4/payment/verify.json"
ZP_API_STARTPAY = "https://sandbox.zarinpal.com/pg/StartPay/{authority}"

def zarinpal_post(url, payload):
    """POST to Zarinpal; returns (http status or None, the 'data' dict, the 'errors' value)."""
    try:
        response = requests.post(url, json=payload, headers={'accept': 'application/json'}, timeout=15)
        body = response.json() if response.content else {}
    except (requests.exceptions.RequestException, ValueError):
        return None, {}, {}
    if not isinstance(body, dict):
        return response.status_code, {}, {}
    data = body.get('data') if isinstance(body.get('data'), dict) else {}
    return response.status_code, data, body.get('errors') or {}


PRICE_PENDING_MESSAGE = (
    'قیمت برخی اقلام این سفارش پس از بررسی لباس مشخص می‌شود؛ '
    'وقتی سفارش آماده تحویل شد، مبلغ نهایی اعلام می‌شود و می‌توانید آن را پرداخت کنید.'
)


def order_track_url(order_id):
    return f"{reverse('home')}?order_id={order_id}#track-section"


def send_request(request, order_id):
    """Start an online (gateway) payment for one of the logged-in customer's orders."""
    customer_id = session_customer_id(request)
    if not customer_id:
        return customer_login_redirect(request)
    order = get_object_or_404(Order, id=order_id, customer_id=customer_id)
    track_url = order_track_url(order.id)
    if order.is_paid:
        messages.info(request, 'این فاکتور قبلاً پرداخت شده است.')
        return redirect(track_url)
    if order.total_price <= 0:
        messages.error(request, 'مبلغ این فاکتور هنوز مشخص نشده است؛ پس از اعلام قیمت می‌توانید آن را پرداخت کنید.')
        return redirect(track_url)
    if not order.payment_open:
        messages.info(request, PRICE_PENDING_MESSAGE)
        return redirect(track_url)

    shop = ShopSettings.load()
    status_code, data, errors = zarinpal_post(ZP_API_REQUEST, {
        'merchant_id': MERCHANT,
        'amount': int(order.total_price) * 10,
        'description': f'پرداخت فاکتور شماره {order.id} - {shop.name}',
        'callback_url': request.build_absolute_uri(f"{reverse('verify_payment')}?order_id={order.id}"),
    })
    if status_code == 200 and data.get('code') == 100 and data.get('authority'):
        # Remember which order this authority belongs to, so a verified payment can only settle that order.
        pending = request.session.get('order_payments', {})
        pending[str(data['authority'])] = order.id
        request.session['order_payments'] = dict(list(pending.items())[-20:])
        return redirect(ZP_API_STARTPAY.format(authority=data['authority']))
    if status_code is None:
        messages.error(request, 'ارتباط با درگاه پرداخت برقرار نشد؛ چند دقیقه دیگر دوباره تلاش کنید.')
    else:
        code = errors.get('code') if isinstance(errors, dict) else None
        messages.error(request, 'درگاه پرداخت درخواست را نپذیرفت؛ لطفاً دوباره تلاش کنید.'
                       + (f' (کد خطای درگاه: {fa_digits(code)})' if code else ''))
    return redirect(track_url)


def verify(request):
    """Return from the gateway: confirm the payment with Zarinpal and mark the order as paid once."""
    order_id = str(request.GET.get('order_id') or '')
    authority = request.GET.get('Authority')
    status = request.GET.get('Status')
    if not order_id.isdigit() or not authority:
        messages.error(request, 'اطلاعات بازگشت از درگاه معتبر نیست.')
        return redirect('home')
    order = get_object_or_404(Order, id=int(order_id))
    customer_id = session_customer_id(request)
    if customer_id and order.customer_id != customer_id:
        raise Http404
    track_url = order_track_url(order.id)
    if order.is_paid:
        messages.info(request, 'این فاکتور پرداخت شده است.')
        return redirect(track_url)
    if status != 'OK':
        messages.warning(request, 'پرداخت لغو شد یا ناموفق بود؛ مبلغی بابت این فاکتور از شما کسر نشد.')
        return redirect(track_url)

    status_code, data, _ = zarinpal_post(ZP_API_VERIFY, {
        'merchant_id': MERCHANT,
        'amount': int(order.total_price) * 10,
        'authority': authority,
    })
    code = data.get('code')
    issued_here = request.session.get('order_payments', {}).get(str(authority)) == order.id
    # 100 = verified now. 101 = verified before; only trust it for the order this authority was issued for,
    # otherwise one payment could settle any other order with the same amount.
    if status_code == 200 and (code == 100 or (code == 101 and issued_here)):
        Order.mark_paid(order.pk, order.customer_id)
        ref_id = str(data.get('ref_id') or '')
        messages.success(request, f'پرداخت فاکتور شماره {fa_digits(order.id)} با موفقیت انجام شد.'
                         + (f' کد پیگیری: {fa_digits(ref_id)}' if ref_id else ''))
        return redirect(track_url)
    messages.error(
        request,
        'پرداخت تأیید نشد. اگر مبلغی از حساب شما کم شده، طبق قوانین بانکی حداکثر تا ۷۲ ساعت برمی‌گردد؛ '
        'در غیر این صورت با پشتیبانی تماس بگیرید.',
    )
    return redirect(track_url)


def parse_price_value(raw):
    if not raw:
        return 0
    fa_digits = '۰۱۲۳۴۵۶۷۸۹'
    normalized = str(raw).translate(str.maketrans(fa_digits, '0123456789')).replace(',', '').replace('٬', '').strip()
    return int(normalized) if normalized.isdigit() else 0


PRICING_THEMES = [
    {'header_bg': 'bg-teal-50', 'header_text': 'text-teal-700', 'header_border': 'border-teal-200'},
    {'header_bg': 'bg-blue-50', 'header_text': 'text-blue-700', 'header_border': 'border-blue-200'},
    {'header_bg': 'bg-rose-50', 'header_text': 'text-rose-700', 'header_border': 'border-rose-200'},
    {'header_bg': 'bg-amber-50', 'header_text': 'text-amber-700', 'header_border': 'border-amber-200'},
    {'header_bg': 'bg-violet-50', 'header_text': 'text-violet-700', 'header_border': 'border-violet-200'},
]

def pricing_menu(request):
    categories = list(PriceCategory.objects.prefetch_related('items').all())
    for index, category in enumerate(categories):
        theme = PRICING_THEMES[index % len(PRICING_THEMES)]
        category.header_bg = theme['header_bg']
        category.header_text = theme['header_text']
        category.header_border = theme['header_border']
    shop = ShopSettings.load()
    return render(request, 'pricing.html', {'categories': categories, 'shop_name': shop.name})

# Couriers only work inside Iran; anything outside (or NaN/inf) is a broken or forged point.
IRAN_LAT_RANGE = (24.0, 40.5)
IRAN_LNG_RANGE = (43.5, 63.5)


def clean_courier_location(lat, lng, postal):
    """Validate a map point and postal code.

    Returns ((lat, lng, postal), None) with normalized strings, or (None, error message).
    """
    try:
        lat_value = float(str(lat).translate(FA_TO_EN_DIGITS))
        lng_value = float(str(lng).translate(FA_TO_EN_DIGITS))
    except (TypeError, ValueError):
        return None, 'لطفاً موقعیت خود را روی نقشه انتخاب کنید.'
    if not (math.isfinite(lat_value) and math.isfinite(lng_value)):
        return None, 'لطفاً موقعیت خود را روی نقشه انتخاب کنید.'
    if not (IRAN_LAT_RANGE[0] <= lat_value <= IRAN_LAT_RANGE[1] and IRAN_LNG_RANGE[0] <= lng_value <= IRAN_LNG_RANGE[1]):
        return None, 'موقعیت انتخاب‌شده خارج از محدوده ارسال است؛ نقطه را روی نقشه درست انتخاب کنید.'
    postal_digits = normalize_postal(postal)
    if postal_format_error(postal_digits):
        return None, postal_format_error(postal_digits)
    if lookup_postal_code(postal_digits)['status'] == 'not_found':
        return None, 'این کد پستی در سامانه پست پیدا نشد؛ لطفاً دوباره بررسی کنید.'
    return (f'{lat_value:.6f}', f'{lng_value:.6f}', postal_digits), None


def postal_lookup(request):
    """Checks a postal code with map.ir and returns its point and address for the customer's map."""
    is_staff = request.user.is_authenticated and request.user.is_staff
    if not session_customer_id(request) and not is_staff:
        return JsonResponse({'status': 'error', 'message': 'ابتدا وارد حساب شوید.'}, status=403)
    code = normalize_postal(request.GET.get('code'))
    if postal_format_error(code):
        return JsonResponse({'status': 'invalid', 'message': postal_format_error(code)})
    # Each lookup costs money: cap how often one visitor can ask.
    who = request.session.session_key or request.META.get('REMOTE_ADDR', '')
    rate_key = f'postal-rate:{who}'
    used = cache.get(rate_key, 0)
    if used >= 30:
        return JsonResponse({'status': 'unavailable', 'message': 'تعداد بررسی‌ها زیاد شد؛ کمی بعد دوباره امتحان کنید.'})
    cache.set(rate_key, used + 1, 600)
    result = lookup_postal_code(code)
    if result['status'] == 'not_found':
        result['message'] = 'این کد پستی در سامانه پست پیدا نشد؛ لطفاً دوباره بررسی کنید.'
    return JsonResponse(result)


def validate_courier_location(lat, lng, postal):
    """Returns an error message if the location/postal code is invalid, else None."""
    return clean_courier_location(lat, lng, postal)[1]


def order_error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def submit_review(request):
    """ثبت امتیاز و نظر مشتری برای سفارشی که تحویل داده شده (هر سفارش فقط یک بار).

    نظرهای دارای متن تا تأیید فروشگاه در سایت نمایش داده نمی‌شوند؛ امتیاز بدون متن مستقیم در میانگین حساب می‌شود.
    """
    customer_id = session_customer_id(request)
    if not customer_id:
        return order_error('برای ثبت نظر ابتدا وارد حساب شوید.', status=403)
    if request.method != 'POST':
        return order_error('درخواست نامعتبر است.', status=405)
    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        return order_error('اطلاعات نظر نامعتبر است.')

    rating = data.get('rating')
    if isinstance(rating, str) and rating.strip().isdigit():
        rating = int(rating)
    if isinstance(rating, bool) or not isinstance(rating, int):
        return order_error('لطفاً امتیاز را انتخاب کنید.')
    if not 1 <= rating <= 5:
        return order_error('امتیاز باید بین ۱ تا ۵ باشد.')

    order_id = str(data.get('order_id') or '')
    order = Order.objects.filter(id=int(order_id), customer_id=customer_id).first() if order_id.isdigit() else None
    if not order:
        return order_error('سفارش پیدا نشد.', status=404)
    if order.status != 'delivered':
        return order_error('بعد از تحویل سفارش می‌توانید نظر بدهید.')

    valid_tags = dict(OrderReview.TAG_CHOICES)
    raw_tags = data.get('tags') if isinstance(data.get('tags'), list) else []
    tags = [t for t in raw_tags if isinstance(t, str) and t in valid_tags]
    comment = data.get('comment')
    comment = comment.strip()[:1000] if isinstance(comment, str) else ''
    review, created = OrderReview.objects.get_or_create(
        order=order,
        defaults={
            'customer_id': customer_id, 'rating': rating, 'comment': comment,
            'tags': ','.join(dict.fromkeys(tags)),
            # Free text is shown publicly only after the shop approves it in the panel.
            'is_hidden': bool(comment),
        },
    )
    if not created:
        return order_error('برای این سفارش قبلاً نظر ثبت کرده‌اید.')
    return JsonResponse({'status': 'success', 'pending_approval': review.is_hidden})


def request_courier(request):
    """Delivery courier for a ready order. The address can be corrected until the courier leaves."""
    customer_id = session_customer_id(request)
    if not customer_id:
        return order_error('برای درخواست پیک ابتدا وارد حساب مشتری شوید.', status=403)
    if request.method != 'POST':
        return order_error('درخواست نامعتبر است.', status=405)
    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        return order_error('اطلاعات درخواست پیک نامعتبر است.')

    order_id = str(data.get('order_id') or '')
    order = Order.objects.filter(id=int(order_id), customer_id=customer_id).first() if order_id.isdigit() else None
    if not order:
        return order_error('این سفارش در حساب شما پیدا نشد.', status=404)
    if order.status == 'delivered':
        return order_error('این سفارش قبلاً تحویل داده شده است.')
    if order.status != 'ready':
        return order_error('این سفارش هنوز آماده تحویل نیست؛ وقتی آماده شد می‌توانید پیک درخواست کنید.')
    if order.delivery_courier_dispatched:
        return order_error('پیک برای این سفارش ارسال شده و دیگر امکان تغییر آدرس نیست؛ برای هماهنگی با فروشگاه تماس بگیرید.')
    location, error = clean_courier_location(data.get('lat'), data.get('lng'), data.get('postal'))
    if error:
        return order_error(error)

    updating = order.delivery_courier_requested
    order.delivery_courier_requested = True
    order.delivery_courier_declined = False
    order.delivery_latitude, order.delivery_longitude, order.delivery_postal_code = location
    order.delivery_address = str(data.get('address') or '').strip()[:500]
    order.save()
    return JsonResponse({
        'status': 'success',
        'message': 'آدرس ارسال به‌روز شد.' if updating else 'درخواست پیک با موفقیت ثبت شد.',
    })


MAX_ITEM_QUANTITY = 50
MAX_ORDER_LINES = 60
# Order.total_price holds at most 10 digits; stay far below that so a single request can never
# store a total that the database cannot read back (which used to break the panel).
MAX_ORDER_TOTAL = 1_000_000_000


def parse_quantity(raw):
    """A whole number between 1 and MAX_ITEM_QUANTITY, or None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    if isinstance(raw, str):
        raw = raw.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')).strip()
        raw = int(raw) if raw.isdigit() else None
    if isinstance(raw, int) and 1 <= raw <= MAX_ITEM_QUANTITY:
        return raw
    return None


def order_item_label(price_item, iron_only):
    """'پیراهن مردانه (فقط اتو)' — the category tells men's and women's items apart on the invoice."""
    name = price_item.name
    category = price_item.category.name
    if category and category not in name:
        name = f'{name} {category}'
    service = 'فقط اتو' if iron_only else 'خشکشویی + اتو'
    return f'{name} ({service})'[:100]


def pay_order_from_wallet(order, customer_id):
    """Pay an unpaid order from the customer's wallet. Safe against double taps and parallel requests.

    Returns 'paid', 'already_paid', 'insufficient', 'invalid' or 'not_ready' (priced after inspection, not ready yet).
    """
    if order.total_price <= 0:
        return 'invalid'
    if not order.is_paid and not order.payment_open:
        return 'not_ready'
    with transaction.atomic():
        wallet, _ = Wallet.objects.get_or_create(customer_id=customer_id)
        if not Order.mark_paid(order.pk, customer_id):
            return 'already_paid'
        debited = Wallet.objects.filter(pk=wallet.pk, balance__gte=order.total_price).update(
            balance=F('balance') - order.total_price, updated_at=timezone.now()
        )
        if not debited:
            transaction.set_rollback(True)
            return 'insufficient'
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='debit',
            amount=order.total_price,
            description=f'پرداخت فاکتور شماره {order.id}',
            order=order,
        )
    order.is_paid = True
    return 'paid'


def refund_wallet_payment(order):
    """Give back what the customer paid for this order from their wallet and not yet got back. Returns the amount.

    Called when staff mark a paid order as unpaid: otherwise the customer could pay for it a second time.
    """
    with transaction.atomic():
        moves = WalletTransaction.objects.filter(order=order).select_for_update()
        paid = sum(t.amount for t in moves if t.transaction_type == 'debit')
        returned = sum(t.amount for t in moves if t.transaction_type == 'credit')
        amount = paid - returned
        if amount <= 0:
            return 0
        wallet = Wallet.objects.get(pk=moves.filter(transaction_type='debit').values_list('wallet_id', flat=True).first())
        Wallet.objects.filter(pk=wallet.pk).update(balance=F('balance') + amount, updated_at=timezone.now())
        WalletTransaction.objects.create(
            wallet=wallet, transaction_type='credit', amount=amount, order=order,
            description=f'بازگشت وجه فاکتور شماره {order.id} (لغو پرداخت توسط فروشگاه)',
        )
    return amount


def place_order(request):
    """
    ثبت سفارش آنلاین از فرم «ثبت سفارش» در home.html (فقط برای مشتری واردشده).
    ورودی JSON:
    {
        "items": [{"line_id": 12, "quantity": 2, "iron_only": false, "price_numeric": 220000, "description": "..."}],
        "delivery_method": "pickup" | "courier",
        "lat": "...", "lng": "...", "postal": "...", "address": "...", "save_address": true,  # فقط برای پیک
        "use_wallet": false,
        "use_discount": false  # تخفیف باشگاه مشتریان؛ سرور خودش بررسی می‌کند که مشتری واقعاً آن را دارد
    }
    همه‌چیز قبل از ساختن سفارش بررسی می‌شود و سفارش در یک تراکنش ساخته می‌شود؛ پس هیچ خطایی
    سفارش نیمه‌کاره یا خالی باقی نمی‌گذارد. اقلامی که قیمتشان «در حال هماهنگی» است با قیمت صفر
    ثبت می‌شوند تا فروشگاه بعداً قیمت را مشخص کند؛ چنین سفارشی تا «آماده تحویل» قابل پرداخت نیست.
    """
    customer_id = session_customer_id(request)
    logged_customer = Customer.objects.filter(id=customer_id).first() if customer_id else None
    if not logged_customer:
        return order_error('برای ثبت سفارش ابتدا وارد حساب مشتری شوید.', status=403)
    if request.method != 'POST':
        return order_error('درخواست نامعتبر است.', status=405)

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        return order_error('اطلاعات سفارش خوانا نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.')
    if not isinstance(data, dict):
        return order_error('اطلاعات سفارش نامعتبر است.')

    items = data.get('items')
    if not isinstance(items, list) or not items:
        return order_error('حداقل یک قلم لباس انتخاب کنید.')
    if len(items) > MAX_ORDER_LINES:
        return order_error('تعداد ردیف‌های سفارش بیش از حد مجاز است.')

    ids = set()
    for item in items:
        if not isinstance(item, dict):
            return order_error('اطلاعات اقلام سفارش نامعتبر است.')
        line_id = str(item.get('line_id') or '')
        if not line_id.isdigit():
            return order_error('یکی از اقلام سفارش دیگر معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.')
        ids.add(int(line_id))
    price_items = PriceItem.objects.select_related('category').in_bulk(ids)

    lines = []
    for item in items:
        price_item = price_items.get(int(item['line_id']))
        if not price_item:
            return order_error('یکی از اقلام سفارش دیگر معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.')
        quantity = parse_quantity(item.get('quantity'))
        if quantity is None:
            return order_error(f'تعداد «{price_item.name}» باید عددی بین ۱ تا {fa_digits(MAX_ITEM_QUANTITY)} باشد.')
        iron_only = item.get('iron_only') is True
        if iron_only and not price_item.iron_only_price:
            return order_error(f'سرویس «فقط اتو» برای «{price_item.name}» ارائه نمی‌شود.')
        price = parse_price_value(price_item.iron_only_price if iron_only else price_item.dry_clean_price)
        # The page may have been open while the shop changed a price: never charge something not shown.
        shown = item.get('price_numeric')
        if isinstance(shown, (int, float)) and not isinstance(shown, bool) and int(shown) != price:
            return order_error('قیمت برخی اقلام به‌روز شده است؛ صفحه را تازه کنید تا قیمت‌های جدید را ببینید.', status=409)
        description = item.get('description')
        description = description.strip()[:500] if isinstance(description, str) else ''
        lines.append((price_item, iron_only, quantity, price, description))

    total = sum(price * quantity for _, _, quantity, price, _ in lines)
    if total > MAX_ORDER_TOTAL:
        return order_error('مبلغ سفارش بیش از حد مجاز است؛ لطفاً با فروشگاه تماس بگیرید.')

    courier = data.get('delivery_method') == 'courier'
    location = None
    if courier:
        location, error = clean_courier_location(data.get('lat'), data.get('lng'), data.get('postal'))
        if error:
            return order_error(error)

    loyalty = None
    if data.get('use_discount') is True:
        # Never trust the page: the discount must really be available to this customer right now.
        loyalty = loyalty_status(logged_customer)
        if not loyalty['available']:
            return order_error(LOYALTY_UNAVAILABLE, status=409)

    try:
        order = create_online_order(logged_customer, lines, total, courier, location, data, loyalty)
    except IntegrityError:
        # Two orders with the discount at the same moment (double tap, two tabs): only one may have it.
        return order_error(LOYALTY_UNAVAILABLE, status=409)

    payment = None
    if data.get('use_wallet') is True and order.payment_open:
        payment = pay_order_from_wallet(order, logged_customer.id)

    return JsonResponse({
        'status': 'success',
        'order_id': order.id,
        'invoice_number': order.id,
        'total': int(order.total_price),
        'discount': order.discount_applied,
        'paid_by_wallet': payment == 'paid',
        'wallet_insufficient': payment == 'insufficient',
        'price_pending': order.price_pending,
        'covered_by_discount': order.covered_by_discount,
        'track_url': f"{reverse('home')}?order_id={order.id}#track-section",
    })


LOYALTY_UNAVAILABLE = 'تخفیف باشگاه مشتریان برای این سفارش در دسترس نیست (یا قبلاً استفاده شده است)؛ صفحه را تازه کنید.'


def create_online_order(customer, lines, total, courier, location, data, loyalty):
    with transaction.atomic():
        order = Order(customer=customer, price_pending=any(price <= 0 for _, _, _, price, _ in lines))
        if loyalty:
            order.discount_amount = loyalty['discount']
            order.discount_period = loyalty['period_start']
        if courier:
            # لباس‌ها هنوز دست ما نرسیده؛ تا وقتی پیک آن‌ها را بیاورد سفارش در مرحله «جمع‌آوری» است
            order.status = 'collecting'
            order.courier_requested = True
            order.latitude, order.longitude, order.postal_code = location
            order.address = str(data.get('address') or '').strip()[:500]
        order.save()
        OrderItem.objects.bulk_create([
            OrderItem(order=order, item_name=order_item_label(price_item, iron_only),
                      quantity=quantity, price=price, description=description)
            for price_item, iron_only, quantity, price, description in lines
        ])
        order.total_price = max(total - int(order.discount_amount), 0)
        order.save(update_fields=['total_price'])
        if courier and data.get('save_address') is True:
            (customer.address_latitude, customer.address_longitude, customer.address_postal_code) = location
            customer.address = order.address[:1000]
            customer.save(update_fields=['address', 'address_latitude', 'address_longitude', 'address_postal_code'])
    return order
