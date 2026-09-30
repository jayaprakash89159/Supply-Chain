from django.contrib import admin

from .models import Brand, Material, MaterialCategory, Trade


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'code', 'unit', 'is_active')
	list_filter = ('category', 'is_active')
	search_fields = ('name', 'code', 'category__name')


admin.site.register((MaterialCategory, Trade, Brand))
