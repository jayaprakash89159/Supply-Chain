from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'client', 'city', 'state', 'status')
	list_filter = ('status', 'city', 'state')
	search_fields = ('code', 'name', 'client')
