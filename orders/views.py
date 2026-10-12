import json
import math
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import Http404, HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
import re
from django.utils import timezone
from .models import Order, OrderItem, OrderReview, Customer, ShopSettings, PriceCategory, PriceItem, Wallet, WalletTransaction
from .templatetags.fa_format import fa_digits, toman
from django.db.models import Avg, Count, F


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
    tracking_error = None

    if customer_logged_in:
        customer = Customer.objects.filter(id=customer_id).first()
        if customer:
            phone_number = customer.phone
            customer_name = customer.name
            wallet, _ = Wallet.objects.get_or_create(customer=customer)
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
        'categories': categories,
        'wallet': wallet,
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
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return redirect('customer_login')
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        if form_type == 'profile':
            name = request.POST.get('name', '').strip()
            phone = normalize_phone(request.POST.get('phone'))
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            error = None
            if len(name) < 2:
                error = 'لطفاً نام و نام‌خانوادگی معتبر وارد کنید.'
            elif len(phone) != 11 or not phone.startswith('09'):
                error = 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.'
            elif Customer.objects.exclude(id=customer.id).filter(phone=phone).exists():
                error = 'این شماره موبایل برای حساب دیگری ثبت شده است.'
            elif new_password:
                if not customer.password_hash or not check_password(current_password, customer.password_hash):
                    error = 'رمز عبور فعلی صحیح نیست.'
                elif not valid_password(new_password):
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

    return render(request, 'account.html', {'customer': customer})


def wallet_page(request):
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return redirect('customer_login')
    customer = get_object_or_404(Customer, id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    transactions = wallet.transactions.select_related('order')[:30]
    return render(request, 'wallet.html', {'wallet': wallet, 'transactions': transactions, 'customer': customer})


def wallet_pay_order(request, order_id):
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return redirect('customer_login')
    if request.method != 'GET':
        return redirect('home')

    order = get_object_or_404(Order, id=order_id, customer_id=customer_id)
    invoice_url = f"{reverse('home')}?order_id={order.id}#track-section"
    if order.is_paid:
        messages.info(request, 'این فاکتور قبلاً پرداخت شده است.')
        return redirect(invoice_url)
    if order.total_price <= 0:
        messages.error(request, 'مبلغ این فاکتور برای پرداخت با کیف پول معتبر نیست.')
        return redirect(invoice_url)

    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(customer_id=customer_id)
        if wallet.balance < order.total_price:
            messages.error(request, f'موجودی کیف پول کافی نیست. موجودی فعلی: {wallet.balance:,} تومان')
            return redirect(invoice_url)
        wallet.balance -= order.total_price
        wallet.save(update_fields=['balance', 'updated_at'])
        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type='debit',
            amount=order.total_price,
            description=f'پرداخت فاکتور شماره {order.id}',
            order=order,
        )
        order.is_paid = True
        order.save(update_fields=['is_paid'])

    messages.success(request, f'فاکتور شماره {order.id} با موفقیت از کیف پول پرداخت شد.')
    return redirect(invoice_url)


def recharge_wallet(request):
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return redirect('customer_login')
    if request.method != 'POST':
        return redirect('wallet')
    try:
        amount = int(request.POST.get('amount', '0').replace(',', '').replace('.', '').strip())
    except (TypeError, ValueError):
        amount = 0
    if amount < 10000:
        messages.error(request, 'حداقل مبلغ شارژ کیف پول ۱۰٬۰۰۰ تومان است.')
        return redirect('wallet')

    customer = get_object_or_404(Customer, id=customer_id)
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    transaction_obj = WalletTransaction.objects.create(
        wallet=wallet, transaction_type='credit', amount=amount,
        description='شارژ کیف پول از طریق درگاه'
    )
    shop = ShopSettings.load()
    data = {
        'merchant_id': MERCHANT,
        'amount': amount * 10,
        'description': f'شارژ کیف پول {customer.name} - {shop.name}',
        'callback_url': request.build_absolute_uri(f'/wallet/verify/?transaction_id={transaction_obj.id}'),
    }
    try:
        response = requests.post(ZP_API_REQUEST, json=data, headers={'accept': 'application/json'}, timeout=15)
        response_json = response.json() if response.content else {}
        if response.status_code == 200 and response_json.get('data', {}).get('code') == 100:
            authority = response_json['data']['authority']
            transaction_obj.authority = authority
            transaction_obj.save(update_fields=['authority'])
            return redirect(ZP_API_STARTPAY.format(authority=authority))
        transaction_obj.delete()
        error_code = response_json.get('errors', {}).get('code', 'نامشخص')
        messages.error(request, f'ایجاد تراکنش شارژ کیف پول ناموفق بود. کد درگاه: {error_code}')
    except requests.exceptions.RequestException:
        transaction_obj.delete()
        messages.error(request, 'ارتباط با درگاه پرداخت برقرار نشد.')
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

    data = {'merchant_id': MERCHANT, 'amount': int(transaction_obj.amount) * 10, 'authority': authority}
    try:
        response = requests.post(ZP_API_VERIFY, json=data, headers={'accept': 'application/json'}, timeout=15)
        response_json = response.json() if response.content else {}
    except (requests.exceptions.RequestException, ValueError):
        response, response_json = None, {}
    payload = response_json.get('data') if isinstance(response_json, dict) else None
    code = payload.get('code') if isinstance(payload, dict) else None
    if response is not None and response.status_code == 200 and code in (100, 101):
        ref_id = str(payload.get('ref_id') or '')
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
    digits = str(raw or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    digits = re.sub(r'\D', '', digits)
    if digits.startswith('98'):
        digits = '0' + digits[2:]
    return digits

def valid_password(password):
    # Keep registration simple: accept any password of at least 8 characters.
    return len(password) >= 8

def customer_login(request):
    error = None
    if request.method == 'POST':
        phone = normalize_phone(request.POST.get('phone'))
        password = request.POST.get('password', '')
        if len(phone) == 11 and phone.startswith('09') and password:
            customer = Customer.objects.filter(phone=phone).first()
            if customer and customer.password_hash and check_password(password, customer.password_hash):
                request.session['customer_id'] = customer.id
                request.session['customer_logged_in'] = True
                request.session.cycle_key()
                return redirect('home')
        error = 'شماره موبایل یا رمز عبور صحیح نیست.'
    return render(request, 'customer_login.html', {'error': error})

def customer_register(request):
    error = None
    success = None
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = normalize_phone(request.POST.get('phone'))
        password = request.POST.get('password', '')

        if not name or len(name) < 2:
            error = 'لطفاً نام و نام‌خانوادگی معتبر وارد کنید.'
        elif len(phone) != 11 or not phone.startswith('09'):
            error = 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.'
        elif Customer.objects.filter(phone=phone).exists():
            error = 'این شماره موبایل قبلاً ثبت شده است. اگر حساب قدیمی دارید، از گزینه فعال‌سازی حساب قدیمی استفاده کنید.'
        elif not valid_password(password):
            error = 'رمز عبور باید حداقل ۸ کاراکتر باشد.'
        else:
            customer = Customer.objects.create(
                name=name,
                phone=phone,
                password_hash=make_password(password),
            )
            Wallet.objects.get_or_create(customer=customer)
            request.session['customer_id'] = customer.id
            request.session['customer_logged_in'] = True
            request.session.cycle_key()
            return redirect('home')
    return render(request, 'customer_register.html', {'error': error})

def customer_logout(request):
    request.session.pop('customer_id', None)
    request.session.pop('customer_logged_in', None)
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
        'is_staff_view': is_staff and order.customer_id != customer_id,
    })

MERCHANT = '00000000-0000-0000-0000-000000000000'
ZP_API_REQUEST = "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
ZP_API_VERIFY = "https://sandbox.zarinpal.com/pg/v4/payment/verify.json"
ZP_API_STARTPAY = "https://sandbox.zarinpal.com/pg/StartPay/{authority}"

def send_request(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    if order.is_paid:
        return HttpResponse("این فاکتور قبلاً پرداخت شده است.")

    shop = ShopSettings.load()
    amount = int(order.total_price) * 10
    description = f"پرداخت فاکتور شماره {order.id} - {shop.name}"

    callback_path = f'/verify/?order_id={order.id}'
    CallbackURL = request.build_absolute_uri(callback_path)
    data = {
        "merchant_id": MERCHANT,
        "amount": amount,
        "description": description,
        "callback_url": CallbackURL,
    }
    data = json.dumps(data)
    headers = {'content-type': 'application/json', 'accept': 'application/json'}

    try:
        response = requests.post(ZP_API_REQUEST, data=data, headers=headers, timeout=15)

        if response.status_code == 200:
            response_json = response.json()
            if response_json.get('data') and response_json['data'].get('code') == 100:
                authority = response_json['data']['authority']
                return redirect(ZP_API_STARTPAY.format(authority=authority))
            else:
                error_code = response_json.get('errors', {}).get('code', 'نامشخص')
                return HttpResponse(f"خطا در ایجاد تراکنش. کد ارور بانک: {error_code}")
        else:
            return HttpResponse(f"خطا در ارتباط با زرین‌پال.<br>کد وضعیت: {response.status_code}<br>متن خطا: {response.text}")

    except requests.exceptions.RequestException as e:
        return HttpResponse(f"خطای شبکه! آیا اینترنت متصل است یا VPN روشن است؟ <br> {e}")

def verify(request):
    order_id = request.GET.get('order_id')
    authority = request.GET.get('Authority')
    status = request.GET.get('Status')

    if not order_id or not authority:
        return HttpResponse("اطلاعات تراکنش نامعتبر است.")

    order = get_object_or_404(Order, id=order_id)

    if status == 'OK':
        amount = int(order.total_price) * 10
        data = {
            "merchant_id": MERCHANT,
            "amount": amount,
            "authority": authority,
        }
        data = json.dumps(data)
        headers = {'content-type': 'application/json', 'accept': 'application/json'}

        try:
            response = requests.post(ZP_API_VERIFY, data=data, headers=headers)
            if response.status_code == 200:
                response_json = response.json()
                if response_json.get('data') and response_json['data'].get('code') == 100:

                    order.is_paid = True
                    order.save()

                    ref_id = response_json['data']['ref_id']
                    return HttpResponse(f"<div style='font-family:Tahoma; text-align:center; margin-top:50px;'><h1>پرداخت با موفقیت انجام شد!</h1><p>کد پیگیری: {ref_id}</p><a href='/?phone={order.customer.phone}&order_id={order.id}#track-section'>بازگشت به سایت</a></div>")

                elif response_json.get('data') and response_json['data'].get('code') == 101:
                    return HttpResponse("این تراکنش قبلاً با موفقیت تایید شده است.")
                else:
                    return HttpResponse("تراکنش ناموفق بود یا مبلغ همخوانی نداشت.")

            return HttpResponse(f"خطا در تایید تراکنش. کد سرور: {response.status_code}")
        except Exception as e:
            return HttpResponse("خطای شبکه هنگام تایید تراکنش.")
    else:
        return HttpResponse("<div style='font-family:Tahoma; text-align:center; margin-top:50px; color:red;'><h1>پرداخت توسط شما لغو شد.</h1><button onclick='history.back()'>بازگشت</button></div>")

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

FA_TO_EN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
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
    postal_digits = re.sub(r'[\s\-‌]', '', str(postal or '').translate(FA_TO_EN_DIGITS))
    if not postal_digits.isdigit() or len(postal_digits) != 10:
        return None, 'کد پستی باید ۱۰ رقم باشد.'
    return (f'{lat_value:.6f}', f'{lng_value:.6f}', postal_digits), None


def validate_courier_location(lat, lng, postal):
    """Returns an error message if the location/postal code is invalid, else None."""
    return clean_courier_location(lat, lng, postal)[1]


def order_error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def submit_review(request):
    """ثبت امتیاز و نظر مشتری برای سفارشی که تحویل داده شده (هر سفارش فقط یک بار)."""
    customer_id = request.session.get('customer_id')
    if not request.session.get('customer_logged_in') or not customer_id:
        return JsonResponse({'status': 'error', 'message': 'برای ثبت نظر ابتدا وارد حساب شوید.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'درخواست نامعتبر است.'}, status=405)
    try:
        data = json.loads(request.body)
        rating = int(data.get('rating'))
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': 'لطفاً امتیاز را انتخاب کنید.'})
    if not 1 <= rating <= 5:
        return JsonResponse({'status': 'error', 'message': 'امتیاز باید بین ۱ تا ۵ باشد.'})

    order = Order.objects.filter(id=data.get('order_id'), customer_id=customer_id).first()
    if not order:
        return JsonResponse({'status': 'error', 'message': 'سفارش پیدا نشد.'}, status=404)
    if order.status != 'delivered':
        return JsonResponse({'status': 'error', 'message': 'بعد از تحویل سفارش می‌توانید نظر بدهید.'})

    valid_tags = dict(OrderReview.TAG_CHOICES)
    tags = [t for t in (data.get('tags') or []) if t in valid_tags]
    comment = str(data.get('comment') or '').strip()[:1000]
    review, created = OrderReview.objects.get_or_create(
        order=order,
        defaults={'customer_id': customer_id, 'rating': rating, 'comment': comment, 'tags': ','.join(dict.fromkeys(tags))},
    )
    if not created:
        return JsonResponse({'status': 'error', 'message': 'برای این سفارش قبلاً نظر ثبت کرده‌اید.'})
    return JsonResponse({'status': 'success', 'featured': review.is_featured})


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


def place_order(request):
    """
    ثبت سفارش آنلاین از فرم «ثبت سفارش» در home.html.
    ورودی JSON مورد انتظار:
    {
        "name": "...", "phone": "...",
        "items": [{"name": "...", "quantity": 1, "price_numeric": 520000, "price_raw": "520,000"}, ...],
        "delivery_method": "pickup" | "courier",
        "lat": "...", "lng": "...", "postal": "..."   # فقط وقتی courier باشه
    }
    اگه مشتری با این شماره موبایل قبلاً وجود نداشته باشه، یک Customer جدید ساخته می‌شه.
    اگه قیمت بعضی اقلام متنی/غیرعددی باشه (price_numeric خالی)، قیمت آیتم صفر ثبت می‌شه
    تا بعداً از پنل ادمین توسط شما اصلاح بشه.
    """
    if not request.session.get('customer_logged_in') or not request.session.get('customer_id'):
        return JsonResponse({'status': 'error', 'message': 'برای ثبت سفارش ابتدا وارد حساب مشتری شوید.'}, status=403)

    logged_customer = Customer.objects.filter(id=request.session.get('customer_id')).first()
    if not logged_customer:
        return JsonResponse({'status': 'error', 'message': 'حساب مشتری معتبر نیست؛ دوباره وارد شوید.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'درخواست نامعتبر است.'})

    try:
        data = json.loads(request.body)

        items = data.get('items') or []
        delivery_method = data.get('delivery_method')

        if not items:
            return JsonResponse({'status': 'error', 'message': 'حداقل یک قلم لباس انتخاب کنید.'})

        # پیدا کردن یا ساختن مشتری بر اساس شماره موبایل
        customer = logged_customer
        order = Order.objects.create(customer=customer)

        if delivery_method == 'courier':
            lat = data.get('lat')
            lng = data.get('lng')
            postal = data.get('postal')
            error = validate_courier_location(lat, lng, postal)
            if error:
                order.delete()
                return JsonResponse({'status': 'error', 'message': error})
            # لباس‌ها هنوز دست ما نرسیده؛ تا وقتی پیک آن‌ها را بیاورد سفارش در مرحله «جمع‌آوری» است
            order.status = 'collecting'
            order.courier_requested = True
            order.courier_declined = False
            order.latitude = lat
            order.longitude = lng
            order.postal_code = postal
            order.address = str(data.get('address') or '').strip()[:500]
            order.save()

        for item in items:
            quantity = max(1, int(item.get('quantity') or 1))
            try:
                price_item = PriceItem.objects.get(id=int(item.get('line_id')))
            except (TypeError, ValueError, PriceItem.DoesNotExist):
                order.delete()
                return JsonResponse({'status': 'error', 'message': 'یکی از اقلام سفارش دیگر معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.'})
            iron_only = bool(item.get('iron_only'))
            raw_price = price_item.iron_only_price if iron_only else price_item.dry_clean_price
            price = parse_price_value(raw_price)
            item_name = price_item.name + (' (فقط اتو)' if iron_only else ' (خشکشویی + اتو)')
            OrderItem.objects.create(
                order=order,
                item_name=item_name[:100],
                quantity=quantity,
                price=price,
                description=(item.get('description') or '').strip()[:2000],
            )

        order.refresh_from_db()

        paid_by_wallet = False
        wallet_insufficient = False
        if data.get('use_wallet') and order.total_price > 0:
            with transaction.atomic():
                wallet, _ = Wallet.objects.select_for_update().get_or_create(customer=logged_customer)
                if wallet.balance >= order.total_price:
                    wallet.balance -= order.total_price
                    wallet.save(update_fields=['balance', 'updated_at'])
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        transaction_type='debit',
                        amount=order.total_price,
                        description=f'پرداخت فاکتور شماره {order.id}',
                        order=order,
                    )
                    order.is_paid = True
                    order.save(update_fields=['is_paid'])
                    paid_by_wallet = True
                else:
                    wallet_insufficient = True

        return JsonResponse({
            'status': 'success',
            'order_id': order.id,
            'invoice_number': order.id,
            'paid_by_wallet': paid_by_wallet,
            'wallet_insufficient': wallet_insufficient,
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})