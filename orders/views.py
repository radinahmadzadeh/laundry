import json
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
import re
from .models import Order, OrderItem, Customer, ShopSettings, PriceCategory, PriceItem, Wallet, WalletTransaction

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
                    ).prefetch_related('orderitem_set')
                    if not orders.exists():
                        tracking_error = 'شماره فاکتور اشتباه است یا این فاکتور متعلق به حساب شما نیست.'
        else:
            request.session.pop('customer_id', None)
            request.session.pop('customer_logged_in', None)
            customer_logged_in = False

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
    })

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
    if order.is_paid:
        messages.info(request, 'این فاکتور قبلاً پرداخت شده است.')
        return redirect('home')
    if order.total_price <= 0:
        messages.error(request, 'مبلغ این فاکتور برای پرداخت با کیف پول معتبر نیست.')
        return redirect('home')

    with transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(customer_id=customer_id)
        if wallet.balance < order.total_price:
            messages.error(request, f'موجودی کیف پول کافی نیست. موجودی فعلی: {wallet.balance:,} تومان')
            return redirect('home')
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
    return redirect('home')


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


def verify_wallet(request):
    transaction_id = request.GET.get('transaction_id')
    authority = request.GET.get('Authority')
    status = request.GET.get('Status')
    if not transaction_id or not authority:
        return HttpResponse('اطلاعات تراکنش کیف پول نامعتبر است.')
    customer_id = request.session.get('customer_id')
    transaction_obj = get_object_or_404(
        WalletTransaction,
        id=transaction_id,
        authority=authority,
        transaction_type='credit',
        wallet__customer_id=customer_id,
    )
    if status != 'OK':
        return redirect('wallet')
    amount = int(transaction_obj.amount) * 10
    data = {'merchant_id': MERCHANT, 'amount': amount, 'authority': authority}
    try:
        response = requests.post(ZP_API_VERIFY, json=data, headers={'accept': 'application/json'}, timeout=15)
        response_json = response.json() if response.content else {}
        code = response_json.get('data', {}).get('code')
        if response.status_code == 200 and code in (100, 101):
            ref_id = str(response_json.get('data', {}).get('ref_id', ''))
            with transaction.atomic():
                locked_wallet = Wallet.objects.select_for_update().get(pk=transaction_obj.wallet_id)
                if not transaction_obj.reference_id:
                    locked_wallet.balance += transaction_obj.amount
                    locked_wallet.save(update_fields=['balance', 'updated_at'])
                    transaction_obj.reference_id = ref_id or 'verified'
                    transaction_obj.save(update_fields=['reference_id'])
            return redirect('wallet')
    except requests.exceptions.RequestException:
        pass
    return HttpResponse('شارژ کیف پول تایید نشد. در صورت کسر وجه، لطفاً با پشتیبانی تماس بگیرید.')

def normalize_phone(raw):
    digits = str(raw or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    digits = re.sub(r'\D', '', digits)
    if digits.startswith('98'):
        digits = '0' + digits[2:]
    return digits

def valid_password(password):
    return (
        len(password) >= 8
        and bool(re.search(r'[A-Za-z]', password))
        and bool(re.search(r'\d', password))
        and bool(re.search(r'[^A-Za-z0-9]', password))
    )

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
        password_confirm = request.POST.get('password_confirm', '')
        order_id = request.POST.get('order_id', '').strip()

        if not name or len(name) < 2:
            error = 'لطفاً نام و نام‌خانوادگی معتبر وارد کنید.'
        elif len(phone) != 11 or not phone.startswith('09'):
            error = 'شماره موبایل باید با ۰۹ شروع شود و ۱۱ رقم باشد.'
        elif Customer.objects.filter(phone=phone).exists():
            error = 'این شماره موبایل قبلاً ثبت شده است. اگر حساب قدیمی دارید، از گزینه فعال‌سازی حساب قدیمی استفاده کنید.'
        elif not valid_password(password):
            error = 'رمز عبور باید حداقل ۸ کاراکتر و شامل حروف انگلیسی، عدد و یک نماد باشد.'
        elif password != password_confirm:
            error = 'تکرار رمز عبور با رمز اصلی یکسان نیست.'
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
    order = get_object_or_404(Order, id=order_id)
    shop = ShopSettings.load()
    return render(request, 'receipt.html', {
        'order': order,
        'shop_name': shop.name,
        'shop_tagline': shop.tagline,
        'shop_phone': shop.phone,
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

def validate_courier_location(lat, lng, postal):
    """Returns an error message if the courier pickup location/postal code is invalid, else None."""
    try:
        float(lat)
        float(lng)
    except (TypeError, ValueError):
        return 'موقعیت مکانی نامعتبر است.'
    postal_digits = str(postal or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
    if not postal_digits.isdigit() or len(postal_digits) != 10:
        return 'کد پستی باید ۱۰ رقم باشد.'
    return None


def request_courier(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            lat = data.get('lat')
            lng = data.get('lng')
            postal = data.get('postal')
            if not request.session.get('customer_logged_in') or not request.session.get('customer_id'):
                return JsonResponse({'status': 'error', 'message': 'برای درخواست پیک ابتدا وارد حساب مشتری شوید.'}, status=403)

            order = get_object_or_404(Order, id=order_id, customer_id=request.session.get('customer_id'))
            if order.status != 'ready':
                return JsonResponse({
                    'status': 'error',
                    'message': 'این سفارش هنوز آماده تحویل نیست.'
                })
            if order.delivery_courier_requested:
                return JsonResponse({
                    'status': 'error',
                    'message': 'درخواست پیک برای این فاکتور قبلاً ثبت شده است و امکان تغییر آدرس وجود ندارد.'
                })
            error = validate_courier_location(lat, lng, postal)
            if error:
                return JsonResponse({'status': 'error', 'message': error})
            order.delivery_courier_requested = True
            order.delivery_latitude = lat
            order.delivery_longitude = lng
            order.delivery_postal_code = postal
            order.save()
            return JsonResponse({'status': 'success', 'message': 'درخواست پیک با موفقیت ثبت شد.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'failed', 'message': 'درخواست نامعتبر است.'})


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
            order.courier_requested = True
            order.latitude = lat
            order.longitude = lng
            order.postal_code = postal
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