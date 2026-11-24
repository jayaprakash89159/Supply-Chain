from django.urls import path

from . import views

app_name = 'quotes'

urlpatterns = [
    path('', views.history, name='history'),
    path('new/', views.compose, name='compose'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/compare/', views.compare, name='compare'),
    path('<int:pk>/compare.xlsx', views.compare_export, name='compare-export'),
    path('<int:pk>/enter/<int:recipient_pk>/', views.enter_quote, name='enter'),
    path('<int:pk>/file/<int:recipient_pk>/', views.response_file, name='response-file'),
    path('respond/<str:token>/', views.respond, name='respond'),
]
