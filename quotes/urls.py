from django.urls import path

from . import views

app_name = 'quotes'

urlpatterns = [
    path('', views.history, name='history'),
    path('new/', views.compose, name='compose'),
    path('<int:pk>/', views.detail, name='detail'),
]
