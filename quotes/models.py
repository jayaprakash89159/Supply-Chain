from django.conf import settings
from django.db import models


class QuoteRequest(models.Model):
	"""One request for quotation, sent as a separate email to each selected vendor."""

	subject = models.CharField(max_length=255)
	body = models.TextField(help_text='Message with placeholders such as {vendor_name}.')
	requirement = models.TextField(blank=True)
	attachment = models.FileField(upload_to='quotes/%Y/%m/', blank=True)
	sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='quote_requests')
	reply_to = models.CharField(max_length=254, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f'{self.subject} ({self.created_at:%Y-%m-%d})'

	def counts(self):
		result = {'sent': 0, 'failed': 0, 'skipped': 0}
		for recipient in self.recipients.all():
			result[recipient.status] += 1
		return result


class QuoteRecipient(models.Model):
	class Status(models.TextChoices):
		SENT = 'sent', 'Sent'
		FAILED = 'failed', 'Failed'
		SKIPPED = 'skipped', 'Skipped (no email)'

	class Kind(models.TextChoices):
		SUPPLIER = 'supplier', 'Supplier'
		SUBCONTRACTOR = 'subcontractor', 'Labour & Composite'

	request = models.ForeignKey(QuoteRequest, on_delete=models.CASCADE, related_name='recipients')
	kind = models.CharField(max_length=20, choices=Kind.choices)
	vendor_id = models.PositiveIntegerField()
	vendor_code = models.CharField(max_length=50)
	vendor_name = models.CharField(max_length=255)
	emails = models.CharField(max_length=500, blank=True)
	status = models.CharField(max_length=10, choices=Status.choices)
	error = models.TextField(blank=True)
	sent_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ['vendor_name']

	def __str__(self):
		return f'{self.vendor_code} – {self.get_status_display()}'
