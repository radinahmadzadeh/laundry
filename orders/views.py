import json
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from .models import Order, Customer, PriceCategory, ShopSettings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

def track_order(request):
    phone_number = request.GET.get('phone')
    order_id = request.GET.get('order_id')
    orders = None

    if phone_number and order_id:
        orders = Order.objects.filter(customer__phone=phone_number, id=order_id)

    context = {
        'orders': orders,
        'phone': phone_number,
    }

    return render(request, 'track.html', context)

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

    amount = int(order.total_price) * 10
    description = f"پرداخت فاکتور شماره {order.id} - باکسیت"

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
                    return HttpResponse(f"<div style='font-family:Tahoma; text-align:center; margin-top:50px;'><h1>پرداخت با موفقیت انجام شد!</h1><p>کد پیگیری: {ref_id}</p><a href='/track/?phone={order.customer.phone}'>بازگشت به سایت</a></div>")

                elif response_json.get('data') and response_json['data'].get('code') == 101:
                    return HttpResponse("این تراکنش قبلاً با موفقیت تایید شده است.")
                else:
                    return HttpResponse("تراکنش ناموفق بود یا مبلغ همخوانی نداشت.")

            return HttpResponse(f"خطا در تایید تراکنش. کد سرور: {response.status_code}")
        except Exception as e:
            return HttpResponse("خطای شبکه هنگام تایید تراکنش.")
    else:
        return HttpResponse("<div style='font-family:Tahoma; text-align:center; margin-top:50px; color:red;'><h1>پرداخت توسط شما لغو شد.</h1><button onclick='history.back()'>بازگشت</button></div>")

def pricing_menu(request):
    categories = PriceCategory.objects.prefetch_related('items').all()
    
    shop = ShopSettings.load()
    
    context = {
        'categories': categories,
        'shop_name': shop.name,
    }
    return render(request, 'pricing.html', context)

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