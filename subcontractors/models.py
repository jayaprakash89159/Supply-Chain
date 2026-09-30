from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

RATING_VALIDATORS = [MinValueValidator(0), MaxValueValidator(5)]


class DirectSubcontractor(models.Model):
	"""A labour or composite subcontractor, matching the "Labour & Composite" workbook columns."""

	class Status(models.TextChoices):
		ACTIVE = 'active', 'Active'
		ON_HOLD = 'on_hold', 'On hold'
		INACTIVE = 'inactive', 'Inactive'

	code = models.CharField(max_length=50, unique=True)
	name = models.CharField(max_length=255, db_index=True)
	service_type = models.CharField(max_length=100, blank=True, db_index=True)
	scope_of_work = models.TextField(blank=True)
	labour_strength = models.PositiveIntegerField(null=True, blank=True)
	labour_licence_number = models.CharField(max_length=60, blank=True)
	esi_registration_number = models.CharField(max_length=60, blank=True)
	pf_registration_number = models.CharField(max_length=60, blank=True)
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
	msme_category = models.CharField(max_length=50, blank=True)
	udyam_registration_number = models.CharField(max_length=40, blank=True)
	tds_section = models.CharField(max_length=30, blank=True)
	bank_account_holder_name = models.CharField(max_length=180, blank=True)
	bank_name = models.CharField(max_length=180, blank=True)
	bank_account_number = models.CharField(max_length=50, blank=True)
	ifsc = models.CharField(max_length=11, blank=True)
	bank_branch = models.CharField(max_length=180, blank=True)
	ifsc_check = models.BooleanField(null=True, blank=True)
	referred_by = models.CharField(max_length=180, blank=True)
	worked_with_vishwa_before = models.BooleanField(null=True, blank=True)
	quality_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, validators=RATING_VALIDATORS)
	timeliness_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, validators=RATING_VALIDATORS)
	safety_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, validators=RATING_VALIDATORS)
	overall_rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, validators=RATING_VALIDATORS)
	last_reviewed_on = models.DateField(null=True, blank=True)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
	remarks = models.TextField(blank=True)
	archived_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']
		verbose_name = 'labour & composite subcontractor'
		verbose_name_plural = 'labour & composite subcontractors'
		indexes = [models.Index(fields=['city', 'state'], name='direct_sub_city_state_idx')]

	def __str__(self):
		return f'{self.code} - {self.name}'
