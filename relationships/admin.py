from django.contrib import admin

from .models import (
	DirectSubcontractorProject,
	DirectSubcontractorTrade,
	SupplierBrand,
	SupplierDirectSubcontractor,
	SupplierMaterial,
	SupplierMaterialCategory,
	SupplierProject,
	SupplierTrade,
)


admin.site.register((
	SupplierTrade,
	SupplierMaterial,
	SupplierMaterialCategory,
	SupplierBrand,
	SupplierProject,
	SupplierDirectSubcontractor,
	DirectSubcontractorProject,
	DirectSubcontractorTrade,
))
