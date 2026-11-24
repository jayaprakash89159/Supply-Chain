import re
import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


def new_token():
	return secrets.token_urlsafe(32)


class QuoteRequest(models.Model):
	"""One request for quotation, sent as a separate email to each selected vendor."""

	subject = models.CharField(max_length=255)
	body = models.TextField(help_text='Message with placeholders such as {vendor_name}.')
	requirement = models.TextField(blank=True, help_text='The requirement as emailed: item list plus any notes.')
	notes = models.TextField(blank=True, help_text='Notes typed under the item list (delivery place, specifications).')
	due_date = models.DateField(null=True, blank=True, help_text='Last date for vendors to submit quotes online.')
	attachment = models.FileField(upload_to='quotes/%Y/%m/', blank=True)
	sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='quote_requests')
	reply_to = models.CharField(max_length=254, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return f'{self.subject} ({self.created_at:%Y-%m-%d})'

	@property
	def title(self):
		"""The subject without per-vendor placeholders, for page titles: 'RFQ – {vendor_name}' -> 'RFQ'."""
		return re.sub(r'\s*[–—:-]?\s*\{[a-z_]+\}', '', self.subject).strip(' –—:-') or self.subject

	def counts(self):
		result = {'sent': 0, 'failed': 0, 'skipped': 0}
		for recipient in self.recipients.all():
			result[recipient.status] += 1
		return result

	@property
	def is_open(self):
		"""Vendors can submit or revise online until the end of the due date (no due date = always open)."""
		return self.due_date is None or timezone.localdate() <= self.due_date

	def responses(self):
		return [recipient for recipient in self.recipients.all() if hasattr(recipient, 'response')]


class QuoteItem(models.Model):
	"""One line of the requirement that vendors price, e.g. 'TMT Fe 500D 12 mm – 25 MT'."""

	request = models.ForeignKey(QuoteRequest, on_delete=models.CASCADE, related_name='items')
	position = models.PositiveIntegerField()
	description = models.CharField(max_length=300)
	quantity = models.DecimalField(max_digits=14, decimal_places=3)
	unit = models.CharField(max_length=30, blank=True)

	class Meta:
		ordering = ['position']

	def __str__(self):
		return self.description


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
	# Secret for the vendor's own quote link (no login). Older requests have none until first needed.
	token = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)

	class Meta:
		ordering = ['vendor_name']

	def __str__(self):
		return f'{self.vendor_code} – {self.get_status_display()}'

	def save(self, *args, **kwargs):
		if not self.token:
			self.token = new_token()
		super().save(*args, **kwargs)


class VendorQuote(models.Model):
	"""A vendor's answer to a quote request: submitted online by the vendor, or entered by staff."""

	recipient = models.OneToOneField(QuoteRecipient, on_delete=models.CASCADE, related_name='response')
	freight = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	lump_sum = models.DecimalField(
		max_digits=16, decimal_places=2, null=True, blank=True,
		help_text='Total amount excluding GST, for requests without an item list.',
	)
	lump_sum_gst_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	delivery = models.CharField(max_length=200, blank=True)
	payment_terms = models.CharField(max_length=200, blank=True)
	validity = models.CharField(max_length=100, blank=True)
	remarks = models.TextField(blank=True)
	attachment = models.FileField(upload_to='quotes/responses/%Y/%m/', blank=True)
	entered_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
		help_text='Empty when the vendor submitted online.',
	)
	submitted_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	revisions = models.PositiveIntegerField(default=0)

	def __str__(self):
		return f'Quote from {self.recipient.vendor_name}'


class VendorQuoteLine(models.Model):
	quote = models.ForeignKey(VendorQuote, on_delete=models.CASCADE, related_name='lines')
	item = models.ForeignKey(QuoteItem, on_delete=models.CASCADE, related_name='quoted')
	rate = models.DecimalField(max_digits=14, decimal_places=2, help_text='Unit rate excluding GST.')
	gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('18'))
	remark = models.CharField(max_length=200, blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['quote', 'item'], name='uniq_vendor_quote_item')]
