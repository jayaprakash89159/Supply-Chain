from django.urls import path

from . import views

app_name = 'suppliers'

urlpatterns = [
    path('', views.supplier_list, name='list'),
    path('add/', views.supplier_create, name='add'),
    path('upload/', views.supplier_upload, name='upload'),
    path('template.xlsx', views.supplier_template, name='template'),
    path('<int:pk>/', views.supplier_detail, name='detail'),
    path('<int:pk>/edit/', views.supplier_edit, name='edit'),
]
