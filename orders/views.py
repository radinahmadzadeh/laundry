import json
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Order, ShopSettings, PriceCategory

def home(request):
    phone_number = request.GET.get('phone')
    order_id = request.GET.get('order_id')
    orders = None

    if phone_number and order_id:
        orders = Order.objects.filter(customer__phone=phone_number, id=order_id)

    shop = ShopSettings.load()
    categories = list(PriceCategory.objects.prefetch_related('items').all())
    
    return render(request, 'home.html', {
        'orders': orders,
        'phone': phone_number,
        'shop_name': shop.name,
        'shop_tagline': shop.tagline,
        'shop_phone': shop.phone,
        'shop_address': shop.address,
        'categories': categories,
    })

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

@csrf_exempt
def request_courier(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data.get('order_id')
            lat = data.get('lat')
            lng = data.get('lng')
            postal = data.get('postal')
            order = get_object_or_404(Order, id=order_id)
            if order.courier_requested:
                return JsonResponse({
                    'status': 'error',
                    'message': 'درخواست پیک برای این فاکتور قبلاً ثبت شده است و امکان تغییر آدرس وجود ندارد.'
                })
            order.courier_requested = True
            order.latitude = lat
            order.longitude = lng
            order.postal_code = postal
            order.save()
            return JsonResponse({'status': 'success', 'message': 'درخواست پیک با موفقیت ثبت شد.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'failed', 'message': 'درخواست نامعتبر است.'})