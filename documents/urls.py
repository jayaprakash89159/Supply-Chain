from django.urls import path

from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.expiring, name='expiring'),
    path('upload/<str:kind>/<int:vendor_id>/', views.upload, name='upload'),
    path('<int:pk>/file/', views.download, name='download'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
