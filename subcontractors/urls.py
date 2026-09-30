from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'subcontractors'

urlpatterns = [
    path('', views.subcontractor_list, name='list'),
    path('add/', views.subcontractor_create, name='add'),
    path('upload/', views.subcontractor_upload, name='upload'),
    path('template.xlsx', views.subcontractor_template, name='template'),
    path('<int:pk>/', views.subcontractor_detail, name='detail'),
    path('<int:pk>/edit/', views.subcontractor_edit, name='edit'),
    # Old addresses from when there were separate direct and material/work lists.
    path('direct/', RedirectView.as_view(pattern_name='subcontractors:list', query_string=True), name='direct-list'),
    path('material-work/', RedirectView.as_view(pattern_name='subcontractors:list', query_string=True), name='work-list'),
    path('direct/<int:pk>/', RedirectView.as_view(pattern_name='subcontractors:detail'), name='direct-detail'),
]
