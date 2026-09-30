from django.db import models
from django.db.models import Q


class Supplier(models.Model):
	class Status(models.TextChoices):
		ACTIVE = 'active', 'Active'
		ON_HOLD = 'on_hold', 'On hold'
		INACTIVE = 'inactive', 'Inactive'

	vendor_code = models.CharField(max_length=50, unique=True)
	name = models.CharField(max_length=255, db_index=True)
	supplier_type = models.CharField(max_length=100, blank=True, db_index=True)
	unit_of_supply = models.CharField(max_length=100, blank=True)
	contact_person = models.CharField(max_length=180, blank=True)
	mobile_number = models.CharField(max_length=30, blank=True)
	alternate_number = models.CharField(max_length=30, blank=True)
	email = models.EmailField(blank=True)
	full_address = models.TextField(blank=True)
	city = models.CharField(max_length=100, blank=True, db_index=True)
	state = models.CharField(max_length=100, blank=True, db_index=True)
	pin_code = models.CharField(max_length=12, blank=True)
	gst_registration_type = models.CharField(max_length=80, blank=True)
	gstin = models.CharField(max_length=15, blank=True, db_index=True)
	gst_state_code = models.CharField(max_length=2, blank=True)
	pan = models.CharField(max_length=10, blank=True, db_index=True)
	gstin_check = models.BooleanField(null=True, blank=True)
	msme_category = models.CharField(max_length=50, blank=True, db_index=True)
	udyam_registration_number = models.CharField(max_length=40, blank=True)
	tds_section = models.CharField(max_length=30, blank=True)
	bank_account_holder_name = models.CharField(max_length=180, blank=True)
	bank_name = models.CharField(max_length=180, blank=True)
	bank_account_number = models.CharField(max_length=50, blank=True)
	ifsc = models.CharField(max_length=11, blank=True)
	bank_branch = models.CharField(max_length=180, blank=True)
	ifsc_check = models.BooleanField(null=True, blank=True)
	referred_by = models.CharField(max_length=180, blank=True)
	worked_with_vishwa_before = models.BooleanField(null=True, blank=True, db_index=True)
	quality_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
	delivery_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
	price_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
	overall_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, db_index=True)
	last_reviewed_on = models.DateField(null=True, blank=True)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
	remarks = models.TextField(blank=True)
	archived_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']
		indexes = [
			models.Index(fields=['city', 'state'], name='supplier_city_state_idx'),
			models.Index(fields=['status', 'name'], name='supplier_status_name_idx'),
		]
		constraints = [
			models.CheckConstraint(condition=Q(quality_rating__isnull=True) | Q(quality_rating__gte=0, quality_rating__lte=5), name='supplier_quality_rating_range'),
			models.CheckConstraint(condition=Q(delivery_rating__isnull=True) | Q(delivery_rating__gte=0, delivery_rating__lte=5), name='supplier_delivery_rating_range'),
			models.CheckConstraint(condition=Q(price_rating__isnull=True) | Q(price_rating__gte=0, price_rating__lte=5), name='supplier_price_rating_range'),
			models.CheckConstraint(condition=Q(overall_rating__isnull=True) | Q(overall_rating__gte=0, overall_rating__lte=5), name='supplier_overall_rating_range'),
		]

	def __str__(self):
		return f'{self.vendor_code} - {self.name}'
