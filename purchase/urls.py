from django.urls import path

from . import views

app_name = 'purchase'

urlpatterns = [
    path('', views.order_list, name='list'),
    path('settings/', views.approval_settings, name='settings'),
    path('award/<int:quote_pk>/', views.award, name='award'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/submit/', views.submit, name='submit'),
    path('<int:pk>/decide/', views.decide, name='decide'),
    path('<int:pk>/send/', views.send, name='send'),
    path('<int:pk>/cancel/', views.cancel, name='cancel'),
    path('<int:pk>/pdf/', views.order_pdf, name='pdf'),
]
