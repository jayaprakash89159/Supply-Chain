from django.db import models


class SupplierTrade(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='trade_links')
	trade = models.ForeignKey('materials.Trade', on_delete=models.PROTECT, related_name='supplier_links')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'trade'], name='uniq_supplier_trade')]


class SupplierMaterialCategory(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='material_category_links')
	category = models.ForeignKey('materials.MaterialCategory', on_delete=models.PROTECT, related_name='supplier_links')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'category'], name='uniq_supplier_material_category')]


class SupplierMaterial(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='material_links')
	material = models.ForeignKey('materials.Material', on_delete=models.PROTECT, related_name='supplier_links')
	unit_of_supply = models.CharField(max_length=100, blank=True)
	remarks = models.TextField(blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'material'], name='uniq_supplier_material')]


class SupplierBrand(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='brand_links')
	brand = models.ForeignKey('materials.Brand', on_delete=models.PROTECT, related_name='supplier_links')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'brand'], name='uniq_supplier_brand')]


class SupplierProject(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='project_links')
	project = models.ForeignKey('projects.Project', on_delete=models.PROTECT, related_name='supplier_links')
	remarks = models.TextField(blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'project'], name='uniq_supplier_project')]


class SupplierDirectSubcontractor(models.Model):
	supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.CASCADE, related_name='direct_subcontractor_links')
	subcontractor = models.ForeignKey('subcontractors.DirectSubcontractor', on_delete=models.PROTECT, related_name='supplier_links')
	remarks = models.TextField(blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['supplier', 'subcontractor'], name='uniq_supplier_direct_sub')]



class DirectSubcontractorProject(models.Model):
	subcontractor = models.ForeignKey('subcontractors.DirectSubcontractor', on_delete=models.CASCADE, related_name='project_links')
	project = models.ForeignKey('projects.Project', on_delete=models.PROTECT, related_name='direct_subcontractor_links')
	remarks = models.TextField(blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['subcontractor', 'project'], name='uniq_direct_sub_project')]


class DirectSubcontractorTrade(models.Model):
	subcontractor = models.ForeignKey('subcontractors.DirectSubcontractor', on_delete=models.CASCADE, related_name='trade_links')
	trade = models.ForeignKey('materials.Trade', on_delete=models.PROTECT, related_name='subcontractor_links')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['subcontractor', 'trade'], name='uniq_direct_sub_trade')]
