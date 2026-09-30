from django.urls import path

from .views import admin_users, login_view, logout_view

urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('users/', admin_users, name='admin_users'),
]
