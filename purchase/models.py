from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

CENT = Decimal('0.01')

DEFAULT_TERMS = """1. Material must conform to the specifications and relevant IS codes; test certificates to accompany each supply.
2. Delivery to the site address above during working hours; the site engineer's acknowledgement is required on every delivery challan.
3. Quote this PO number on all invoices, delivery challans and correspondence.
4. Tax invoice must show our GSTIN; payment as per the payment terms after receipt of material and invoice.
5. Rejected or short-supplied material will be returned or deducted at the vendor's cost.
6. VISHWA reserves the right to cancel this order, in full or in part, if delivery is not made by the delivery date."""


def money(value):
	return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class PurchaseSettings(models.Model):
	"""One row of company-wide purchase settings, edited by admins."""

	company_name = models.CharField(max_length=200, default='VISHWA Infrastructures & Services Pvt. Ltd.')
	company_address = models.TextField(default='1-11-256/C/24, Plot No:24, Gagan Vihar Colony, Begumpet, Hyderabad, Telangana, India.')
	company_gstin = models.CharField('Company GSTIN', max_length=15, blank=True)
	company_state_code = models.CharField(
		'Company GST state code', max_length=2, default='36', help_text='Used as the default place of supply. 36 = Telangana.',
	)
	company_phone = models.CharField(max_length=60, blank=True, default='+91 40 27763835')
	company_email = models.CharField(max_length=120, blank=True, default='info@vishwainfra.in')
	po_prefix = models.CharField('PO number prefix', max_length=30, default='VISPL/PO')
	default_terms = models.TextField('Standard terms and conditions', default=DEFAULT_TERMS)
	allow_self_approval = models.BooleanField(
		'Allow the person who created a PO to approve it', default=False,
		help_text='Off = maker-checker: someone else must approve. Turn on only if one person handles purchasing alone.',
	)

	class Meta:
		verbose_name_plural = 'purchase settings'

	def __str__(self):
		return 'Purchase settings'

	@classmethod
	def load(cls):
		return cls.objects.get_or_create(pk=1)[0]


class ApprovalLevel(models.Model):
	"""An approval step. A PO needs every active level whose minimum amount it reaches, lowest order first."""

	order = models.PositiveIntegerField(unique=True, help_text='1 approves first, then 2, and so on.')
	name = models.CharField(max_length=80, help_text='e.g. Procurement in-charge, Purchase head, Managing Director')
	min_amount = models.DecimalField(
		'Applies from PO total (₹)', max_digits=16, decimal_places=2, default=0,
		help_text='0 = every PO. 500000 = only POs of ₹5 lakh and above (grand total including GST).',
	)
	approvers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='approval_levels', blank=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ['order']

	def __str__(self):
		return f'Level {self.order}: {self.name}'


class PurchaseOrder(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'draft', 'Draft'
		PENDING = 'pending', 'Pending approval'
		REJECTED = 'rejected', 'Returned for changes'
		APPROVED = 'approved', 'Approved – ready to send'
		SENT = 'sent', 'Sent to vendor'
		CANCELLED = 'cancelled', 'Cancelled'

	number = models.CharField(max_length=60, unique=True, null=True, blank=True, help_text='Given when the PO is fully approved.')
	status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
	quote_request = models.ForeignKey('quotes.QuoteRequest', null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_orders')
	recipient = models.ForeignKey('quotes.QuoteRecipient', null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_orders')
	# Vendor details are copied in, so the PO keeps what was ordered even if the vendor record changes later.
	vendor_kind = models.CharField(max_length=20)
	vendor_id = models.PositiveIntegerField()
	vendor_code = models.CharField(max_length=50)
	vendor_name = models.CharField(max_length=255)
	vendor_address = models.TextField(blank=True)
	vendor_gstin = models.CharField(max_length=15, blank=True)
	vendor_state_code = models.CharField(max_length=2, blank=True)
	vendor_contact = models.CharField(max_length=180, blank=True)
	vendor_phone = models.CharField(max_length=60, blank=True)
	vendor_email = models.CharField(max_length=500, blank=True)
	project = models.ForeignKey('projects.Project', null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_orders')
	delivery_address = models.TextField('Deliver to', blank=True)
	place_of_supply = models.CharField('Place of supply (GST state code)', max_length=2, blank=True)
	delivery_date = models.DateField(null=True, blank=True)
	payment_terms = models.CharField(max_length=200, blank=True)
	freight = models.DecimalField('Freight (₹, excluding GST)', max_digits=14, decimal_places=2, default=0)
	freight_gst_percent = models.DecimalField('GST on freight %', max_digits=5, decimal_places=2, default=18)
	terms = models.TextField('Terms and conditions', blank=True)
	notes = models.TextField('Notes to vendor', blank=True)
	award_reason = models.TextField(blank=True, help_text='Why a vendor other than the lowest was chosen, if so.')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	submitted_at = models.DateTimeField(null=True, blank=True)
	approved_at = models.DateTimeField(null=True, blank=True)
	sent_at = models.DateTimeField(null=True, blank=True)
	sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.number or f'Draft PO #{self.pk}'

	@property
	def display_number(self):
		return self.number or f'DRAFT-{self.pk}'

	@property
	def editable(self):
		return self.status in (self.Status.DRAFT, self.Status.REJECTED)

	@property
	def interstate(self):
		"""IGST when the vendor's state differs from the place of supply; CGST + SGST otherwise."""
		supply = self.place_of_supply or PurchaseSettings.load().company_state_code
		return bool(self.vendor_state_code and supply and self.vendor_state_code != supply)

	def totals(self):
		lines = list(self.lines.all())
		basic = sum((line.amount for line in lines), Decimal('0'))
		gst = sum((line.gst_amount for line in lines), Decimal('0'))
		freight = money(self.freight or 0)
		freight_gst = money(freight * (self.freight_gst_percent or 0) / 100)
		tax = money(gst + freight_gst)
		grand = money(basic + freight + tax)
		half = money(tax / 2)
		return {
			'basic': money(basic), 'freight': freight, 'tax': tax, 'grand': grand,
			'igst': tax if self.interstate else Decimal('0'),
			'cgst': Decimal('0') if self.interstate else half,
			'sgst': Decimal('0') if self.interstate else tax - half,
		}

	def required_levels(self):
		grand = self.totals()['grand']
		return [level for level in ApprovalLevel.objects.filter(is_active=True).prefetch_related('approvers') if grand >= level.min_amount]

	def approved_level_ids(self):
		return set(self.approvals.filter(decision=POApproval.Decision.APPROVED, round=self.approval_round).values_list('level_id', flat=True))

	def next_level(self):
		done = self.approved_level_ids()
		return next((level for level in self.required_levels() if level.pk not in done), None)

	@property
	def approval_round(self):
		"""Each submission starts a new round; approvals from earlier (rejected) rounds no longer count."""
		return self.approvals.filter(decision=POApproval.Decision.SUBMITTED).count()


class PurchaseOrderLine(models.Model):
	order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
	position = models.PositiveIntegerField()
	quote_item = models.ForeignKey('quotes.QuoteItem', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
	description = models.CharField(max_length=300)
	quantity = models.DecimalField(max_digits=14, decimal_places=3)
	unit = models.CharField(max_length=30, blank=True)
	rate = models.DecimalField(max_digits=14, decimal_places=2)
	gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=18)
	remark = models.CharField(max_length=200, blank=True)

	class Meta:
		ordering = ['position']

	@property
	def amount(self):
		return money(self.quantity * self.rate)

	@property
	def gst_amount(self):
		return money(self.amount * self.gst_percent / 100)


class POApproval(models.Model):
	"""Every step of the approval trail: submitted, approved or returned, by whom and when."""

	class Decision(models.TextChoices):
		SUBMITTED = 'submitted', 'Submitted for approval'
		APPROVED = 'approved', 'Approved'
		REJECTED = 'rejected', 'Returned for changes'
		SENT = 'sent', 'Sent to vendor'
		CANCELLED = 'cancelled', 'Cancelled'

	order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='approvals')
	level = models.ForeignKey(ApprovalLevel, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
	level_name = models.CharField(max_length=80, blank=True)
	round = models.PositiveIntegerField(default=1)
	decision = models.CharField(max_length=10, choices=Decision.choices)
	comment = models.TextField(blank=True)
	by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
	at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['at', 'pk']
