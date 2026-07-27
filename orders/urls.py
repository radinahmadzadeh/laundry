from django.urls import path
from . import views

urlpatterns = [
    # با این خط، آدرس track به تابع ما متصل می‌شود
    path('track/', views.track_order, name='track'), 
]