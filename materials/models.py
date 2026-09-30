from django.db import models


class MaterialCategory(models.Model):
	name = models.CharField(max_length=120, unique=True)
	description = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'material categories'

	def __str__(self):
		return self.name


class Trade(models.Model):
	name = models.CharField(max_length=120, unique=True)
	description = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class Brand(models.Model):
	name = models.CharField(max_length=120, unique=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class Material(models.Model):
	category = models.ForeignKey(MaterialCategory, on_delete=models.PROTECT, related_name='materials')
	name = models.CharField(max_length=180)
	code = models.CharField(max_length=60, blank=True, db_index=True)
	description = models.TextField(blank=True)
	unit = models.CharField(max_length=40, blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ['category__name', 'name']
		constraints = [models.UniqueConstraint(fields=['category', 'name'], name='uniq_material_name_category')]
		indexes = [models.Index(fields=['name', 'is_active'], name='material_name_active_idx')]

	def __str__(self):
		return self.name
