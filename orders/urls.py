from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'), 
    
    path('customer-login/', views.customer_login, name='customer_login'),
    path('customer-logout/', views.customer_logout, name='customer_logout'),
    path('wallet/', views.wallet_page, name='wallet'),
    path('wallet/recharge/', views.recharge_wallet, name='recharge_wallet'),
    path('wallet/verify/', views.verify_wallet, name='verify_wallet'),
    path('wallet/pay/<int:order_id>/', views.wallet_pay_order, name='wallet_pay_order'),
    path('receipt/<int:order_id>/', views.print_receipt, name='print_receipt'),
    path('pay/<int:order_id>/', views.send_request, name='request_payment'),
    path('verify/', views.verify, name='verify_payment'),
    path('pricing/', views.pricing_menu, name='pricing'),
    path('request-courier/', views.request_courier, name='request_courier'),
    path('place-order/', views.place_order, name='place_order'),
]