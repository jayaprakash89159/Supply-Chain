from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from accounts.views import dashboard, global_search


def health(request):
    return JsonResponse({'status': 'ok'})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('suppliers/', include('suppliers.urls')),
    path('subcontractors/', include('subcontractors.urls')),
    path('search/', global_search, name='search'),
    path('health/', health, name='health'),
    path('', dashboard, name='dashboard'),
]
