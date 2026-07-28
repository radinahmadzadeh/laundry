from django.urls import path
from . import views

urlpatterns = [
    path('track/', views.track_order, name='track'), 
    # این خط جدید برای باز کردن صفحه فیش است
    path('receipt/<int:order_id>/', views.print_receipt, name='print_receipt'),
]