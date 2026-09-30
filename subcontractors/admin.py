from django.contrib import admin

from .models import DirectSubcontractor


@admin.register(DirectSubcontractor)
class SubcontractorAdmin(admin.ModelAdmin):
	list_display = ('code', 'name', 'service_type', 'contact_person', 'mobile_number', 'city', 'status', 'overall_rating')
	list_filter = ('status', 'service_type', 'city', 'state')
	search_fields = ('code', 'name', 'contact_person', 'mobile_number', 'gstin', 'pan', 'city', 'state')
	readonly_fields = ('created_at', 'updated_at')
	list_per_page = 50
