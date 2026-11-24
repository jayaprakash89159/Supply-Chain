import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone

WARNING_DAYS = 30  # "expiring soon" window used on badges, the dashboard and alerts


class VendorDocument(models.Model):
	"""A compliance document (certificate, licence, insurance) kept for a supplier or subcontractor."""

	class Kind(models.TextChoices):
		SUPPLIER = 'supplier', 'Supplier'
		SUBCONTRACTOR = 'subcontractor', 'Labour & Composite'

	class DocType(models.TextChoices):
		GST = 'gst', 'GST registration certificate'
		PAN = 'pan', 'PAN card'
		BANK = 'bank', 'Cancelled cheque / bank letter'
		MSME = 'msme', 'MSME / Udyam certificate'
		LABOUR_LICENCE = 'labour_licence', 'Labour licence'
		ESI = 'esi', 'ESI registration'
		PF = 'pf', 'PF registration'
		BOCW = 'bocw', 'BOCW registration'
		WC_INSURANCE = 'wc_insurance', 'Workmen compensation insurance'
		TRADE_LICENCE = 'trade_licence', 'Trade licence'
		ISO = 'iso', 'ISO / quality certificate'
		OTHER = 'other', 'Other'

	kind = models.CharField(max_length=20, choices=Kind.choices)
	vendor_id = models.PositiveIntegerField()
	doc_type = models.CharField('Document', max_length=30, choices=DocType.choices)
	number = models.CharField('Document / policy number', max_length=100, blank=True)
	issued_on = models.DateField('Issued on', null=True, blank=True)
	expires_on = models.DateField('Valid until', null=True, blank=True, db_index=True)
	file = models.FileField(upload_to='documents/%Y/%m/')
	notes = models.CharField(max_length=300, blank=True)
	uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
	uploaded_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['doc_type', '-uploaded_at']
		indexes = [models.Index(fields=['kind', 'vendor_id'], name='vendor_document_vendor_idx')]

	def __str__(self):
		return f'{self.get_doc_type_display()} ({self.kind} {self.vendor_id})'

	@property
	def file_name(self):
		return self.file.name.rsplit('/', 1)[-1]

	@property
	def days_left(self):
		return None if self.expires_on is None else (self.expires_on - timezone.localdate()).days

	@property
	def status(self):
		"""expired | expiring | valid | no_expiry"""
		days = self.days_left
		if days is None:
			return 'no_expiry'
		if days < 0:
			return 'expired'
		return 'expiring' if days <= WARNING_DAYS else 'valid'

	@property
	def status_label(self):
		days, status = self.days_left, self.status
		if status == 'no_expiry':
			return 'No expiry'
		if status == 'expired':
			return f'Expired {-days} day{"s" if days != -1 else ""} ago'
		if status == 'expiring':
			return 'Expires today' if days == 0 else f'Expires in {days} day{"s" if days != 1 else ""}'
		return f'Valid until {self.expires_on:%d %b %Y}'


# Documents with a validity period: an expiry date is required when uploading them.
EXPIRING_TYPES = {
	VendorDocument.DocType.LABOUR_LICENCE, VendorDocument.DocType.WC_INSURANCE,
	VendorDocument.DocType.TRADE_LICENCE, VendorDocument.DocType.ISO,
}

# Documents every vendor of that kind should have; shown as "missing" until uploaded.
REQUIRED_TYPES = {
	VendorDocument.Kind.SUPPLIER: [
		VendorDocument.DocType.GST, VendorDocument.DocType.PAN, VendorDocument.DocType.BANK,
	],
	VendorDocument.Kind.SUBCONTRACTOR: [
		VendorDocument.DocType.PAN, VendorDocument.DocType.BANK, VendorDocument.DocType.LABOUR_LICENCE,
		VendorDocument.DocType.WC_INSURANCE,
	],
}


def current_documents(documents):
	"""The newest document of each type: older uploads of the same type are kept as history."""
	latest = {}
	for document in sorted(documents, key=lambda d: d.uploaded_at, reverse=True):
		latest.setdefault(document.doc_type, document)
	return latest


def expiring_queryset(within_days=WARNING_DAYS):
	"""Documents already expired or expiring within ``within_days`` that are still the current one of their type."""
	limit = timezone.localdate() + datetime.timedelta(days=within_days)
	candidates = VendorDocument.objects.filter(expires_on__isnull=False, expires_on__lte=limit)
	# Ignore a document when a newer one of the same type was uploaded for the same vendor (it was renewed).
	newer = VendorDocument.objects.filter(
		kind=models.OuterRef('kind'), vendor_id=models.OuterRef('vendor_id'), doc_type=models.OuterRef('doc_type'),
		uploaded_at__gt=models.OuterRef('uploaded_at'),
	)
	return candidates.exclude(models.Exists(newer)).order_by('expires_on')
