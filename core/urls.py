from django.contrib import admin
from django.urls import path, include # کلمه include اینجا اضافه شد

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('orders.urls')), # این خط اضافه شد تا جنگو مسیرهای جدید را بشناسد
]