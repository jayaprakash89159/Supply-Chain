from django.urls import path

from .views import admin_reset_password, admin_users, login_view, logout_view, password_change

urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('users/', admin_users, name='admin_users'),
    path('users/<int:pk>/password/', admin_reset_password, name='admin_reset_password'),
    path('password/', password_change, name='password_change'),
]
