from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='panel_dashboard'),
    path('login/', views.panel_login, name='panel_login'),
    path('logout/', views.panel_logout, name='panel_logout'),

    path('orders/', views.orders_list, name='panel_orders'),
    path('orders/new/', views.order_create, name='panel_order_create'),
    path('orders/<int:order_id>/', views.order_detail, name='panel_order_detail'),
    path('orders/<int:order_id>/status/', views.order_update_status, name='panel_order_status'),
    path('orders/<int:order_id>/paid/', views.order_toggle_paid, name='panel_order_toggle_paid'),
    path('orders/<int:order_id>/delete/', views.order_delete, name='panel_order_delete'),
    path('orders/<int:order_id>/items/<int:item_id>/delete/', views.order_item_delete, name='panel_order_item_delete'),

    path('customers/', views.customers_list, name='panel_customers'),
    path('customers/<int:customer_id>/', views.customer_detail, name='panel_customer_detail'),

    path('pricing/', views.pricing_list, name='panel_pricing'),
    path('pricing/category/add/', views.price_category_create, name='panel_price_category_create'),
    path('pricing/category/<int:category_id>/delete/', views.price_category_delete, name='panel_price_category_delete'),
    path('pricing/item/add/', views.price_item_create, name='panel_price_item_create'),
    path('pricing/item/<int:item_id>/edit/', views.price_item_update, name='panel_price_item_update'),
    path('pricing/item/<int:item_id>/delete/', views.price_item_delete, name='panel_price_item_delete'),

    path('courier/', views.courier_requests, name='panel_courier'),
    path('courier/<int:order_id>/dispatch/', views.courier_mark_dispatched, name='panel_courier_dispatch'),

    path('settings/', views.shop_settings_view, name='panel_settings'),
]
