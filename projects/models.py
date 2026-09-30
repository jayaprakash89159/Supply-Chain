from django.db import models


class Project(models.Model):
	class Status(models.TextChoices):
		PLANNING = 'planning', 'Planning'
		ACTIVE = 'active', 'Active'
		ON_HOLD = 'on_hold', 'On hold'
		COMPLETE = 'complete', 'Complete'
		CANCELLED = 'cancelled', 'Cancelled'

	code = models.CharField(max_length=50, unique=True)
	name = models.CharField(max_length=200, db_index=True)
	client = models.CharField(max_length=200, blank=True)
	city = models.CharField(max_length=100, blank=True, db_index=True)
	state = models.CharField(max_length=100, blank=True, db_index=True)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
	start_date = models.DateField(null=True, blank=True)
	end_date = models.DateField(null=True, blank=True)
	remarks = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return f'{self.code} - {self.name}'
