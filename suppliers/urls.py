from django.urls import path

from . import views

app_name = 'suppliers'

urlpatterns = [
    path('', views.supplier_list, name='list'),
    path('add/', views.supplier_create, name='add'),
    path('upload/', views.supplier_upload, name='upload'),
    path('delete/', views.supplier_delete, name='delete'),
    path('set-status/', views.supplier_set_status, name='set-status'),
    path('export.xlsx', views.supplier_export, name='export'),
    path('duplicates/', views.supplier_duplicates, name='duplicates'),
    path('template.xlsx', views.supplier_template, name='template'),
    path('<int:pk>/', views.supplier_detail, name='detail'),
    path('<int:pk>/edit/', views.supplier_edit, name='edit'),
    path('<int:pk>/contact.vcf', views.supplier_vcard, name='vcard'),
]
