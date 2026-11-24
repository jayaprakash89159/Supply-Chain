from django.urls import path

from . import views

app_name = 'audit'

urlpatterns = [
    path('activity/', views.activity, name='activity'),
    path('recycle-bin/', views.recycle_bin, name='recycle-bin'),
    path('recycle-bin/restore/', views.restore, name='restore'),
    path('recycle-bin/purge/', views.purge, name='purge'),
]
