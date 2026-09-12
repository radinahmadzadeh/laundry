from django.urls import path
from . import views

urlpatterns = [
    path('track/', views.track_order, name='track'), 
    path('receipt/<int:order_id>/', views.print_receipt, name='print_receipt'),

    path('pay/<int:order_id>/', views.send_request, name='request_payment'),
    path('verify/', views.verify, name='verify_payment'),
    path('pricing/', views.pricing_menu, name='pricing'),
    path('request-courier/', views.request_courier, name='request_courier'),
]