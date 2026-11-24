import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from scportal.excel import XLSX_CONTENT_TYPE

from . import comparison, mailer
from .models import QuoteItem, QuoteRecipient, QuoteRequest, VendorQuote, VendorQuoteLine

MAX_ATTACHMENT_MB = 10
MAX_ITEMS = 100
GST_CHOICES = ('0', '5', '12', '18', '28')
RESPONSE_FILE_TYPES = ('.pdf', '.xlsx', '.xls', '.csv', '.doc', '.docx', '.jpg', '.jpeg', '.png')


def _decimal(text):
	try:
		value = Decimal(str(text).strip().replace(',', ''))
	except InvalidOperation:
		return None
	return value if value.is_finite() else None


# ---------------------------------------------------------------- compose and send

class QuoteForm(forms.Form):
	subject = forms.CharField(max_length=255, initial=mailer.DEFAULT_SUBJECT)
	requirement = forms.CharField(
		required=False, label='Notes',
		widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'e.g. Delivery: Kollapur site by 15 December. IS 1786 certified material only.'}),
		help_text='Delivery place and date, specifications, anything else. Shown under the item list.',
	)
	due_date = forms.DateField(
		required=False, label='Last date for quotes', widget=forms.DateInput(attrs={'type': 'date'}),
		help_text='Vendors can submit or revise online until the end of this day.',
	)
	body = forms.CharField(label='Message', widget=forms.Textarea(attrs={'rows': 16}), initial=mailer.DEFAULT_BODY)
	attachment = forms.FileField(
		required=False, label='Attachment (optional)',
		help_text=f'One file, e.g. BOQ, drawing or specification. Up to {MAX_ATTACHMENT_MB} MB. Sent to every vendor.',
	)

	def __init__(self, *args, items=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.items = items or []
		self.item_errors = []

	def clean_attachment(self):
		attachment = self.cleaned_data.get('attachment')
		if attachment and attachment.size > MAX_ATTACHMENT_MB * 1024 * 1024:
			raise forms.ValidationError(f'This file is {attachment.size / 1024 / 1024:.1f} MB; the limit is {MAX_ATTACHMENT_MB} MB.')
		return attachment

	def clean_due_date(self):
		due = self.cleaned_data.get('due_date')
		if due and due < datetime.date.today():
			raise forms.ValidationError('The last date for quotes is already past. Choose today or a later date.')
		return due

	def clean(self):
		data = super().clean()
		unknown = mailer.unknown_placeholders(data.get('subject'), data.get('body'))
		if unknown:
			raise forms.ValidationError(
				f'Unknown placeholder(s): {", ".join(unknown)}. Use only: {", ".join(mailer.PLACEHOLDERS)}.'
			)
		if data.get('body') and '{requirement}' not in data['body']:
			self.add_error('body', 'Put {requirement} in the message where the requirement should appear.')
		if self.item_errors:
			raise forms.ValidationError(self.item_errors)
		if not self.items and not data.get('requirement', '').strip():
			raise forms.ValidationError('Add at least one item (description and quantity), or describe the requirement in Notes.')
		return data


def parse_items(post):
	"""Item rows typed on the compose page: ([{description, quantity, unit}], [error messages])."""
	rows = zip(post.getlist('item_description'), post.getlist('item_quantity'), post.getlist('item_unit'))
	items, errors = [], []
	for number, (description, quantity, unit) in enumerate(rows, start=1):
		description, quantity, unit = description.strip(), quantity.strip(), unit.strip()
		if not description and not quantity:
			continue
		value = _decimal(quantity)
		if not description:
			errors.append(f'Item row {number}: add a description for quantity “{quantity}”.')
		elif value is None or value <= 0:
			errors.append(f'Item row {number} (“{description}”): enter the quantity as a number above 0, e.g. 25 or 2.5.')
		items.append({'description': description[:300], 'quantity': value if value is not None else quantity, 'unit': unit[:30]})
	if len(items) > MAX_ITEMS:
		errors.append(f'Up to {MAX_ITEMS} items per request; this one has {len(items)}.')
	return items, errors


def _selection(request):
	"""Vendors posted from a list ('kind' + 'ids') or from the compose/search pages ('vendors')."""
	selection = list(request.POST.getlist('vendors'))
	kind = request.POST.get('kind', '')
	selection += [f'{kind}:{pk}' for pk in request.POST.getlist('ids')]
	return mailer.selected_vendors(selection)


@login_required
@require_POST
def compose(request):
	vendors = _selection(request)
	step = request.POST.get('step', 'select')
	back = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
	if not vendors:
		messages.error(request, 'Tick at least one vendor, then click “Request quotes”.')
		return redirect(back)
	if len(vendors) > mailer.MAX_VENDORS:
		messages.error(request, f'You selected {len(vendors)} vendors. Request quotes from at most {mailer.MAX_VENDORS} at a time.')
		return redirect(back)

	if step == 'select':
		items, form = [], QuoteForm()
	else:
		items, item_errors = parse_items(request.POST)
		form = QuoteForm(request.POST, request.FILES, items=items)
		form.item_errors = item_errors
	reply_to = request.user.email.strip()
	if step in ('send', 'test') and form.is_valid():
		quote = QuoteRequest(
			subject=form.cleaned_data['subject'], body=form.cleaned_data['body'],
			requirement=mailer.requirement_text(items, form.cleaned_data['requirement']),
			notes=form.cleaned_data['requirement'], due_date=form.cleaned_data['due_date'],
			reply_to=reply_to, sent_by=request.user,
		)
		if not mailer.email_configured():
			messages.error(request, 'Email sending is not set up on this portal yet. Ask the administrator to add the mail server details.')
		elif step == 'test':
			sample = next((vendor for vendor in vendors if vendor.email_addresses), vendors[0])
			if not reply_to:
				messages.error(request, 'Your account has no email address, so a test cannot be sent to you. Ask an administrator to add it on the Users page.')
			else:
				attachment = form.cleaned_data['attachment']
				file = (attachment.name, attachment.read()) if attachment else None
				try:
					mailer.build_message(sample, quote, request.user, to=[reply_to], attachment=file).send()
					messages.success(
						request,
						f'Test email sent to {reply_to}, filled in for {sample.name}. Check it, then click “Send”.'
						+ (' Choose the attachment again before sending — browsers clear file fields after a reload.' if file else ''),
					)
				except Exception as exc:
					messages.error(request, f'The test email could not be sent. {mailer.explain_mail_error(exc)}')
		else:
			with transaction.atomic():
				quote.save()
				for position, item in enumerate(items, start=1):
					QuoteItem.objects.create(request=quote, position=position, **item)
				if form.cleaned_data['attachment']:
					quote.attachment = form.cleaned_data['attachment']
					quote.save(update_fields=['attachment'])
			results = mailer.send_all(quote, vendors, request.user, mailer.public_base_url(request))
			sent = sum(result.status == QuoteRecipient.Status.SENT for result in results)
			problems = len(results) - sent
			level = messages.success if not problems else messages.warning
			level(request, f'Sent {sent} separate email{"s" if sent != 1 else ""}' + (f'; {problems} vendor(s) not emailed — see below.' if problems else '.'))
			return redirect('quotes:detail', quote.pk)

	return render(request, 'quotes/compose.html', {
		'form': form, 'vendors': vendors, 'placeholders': mailer.PLACEHOLDERS, 'reply_to': reply_to,
		'items': items or [{'description': '', 'quantity': '', 'unit': ''}],
		'emailable': sum(1 for vendor in vendors if vendor.email_addresses),
		'email_ready': mailer.email_configured(), 'back': back, 'your_name': mailer.sender_name(request.user),
		'public_link_ready': bool(mailer.settings.PORTAL_PUBLIC_URL),
	})


# ---------------------------------------------------------------- history and detail

def _quotes_for(user):
	quotes = QuoteRequest.objects.select_related('sent_by')
	return quotes if user.is_superuser else quotes.filter(sent_by=user)


@login_required
def history(request):
	quotes = _quotes_for(request.user).prefetch_related('recipients__response')
	page = Paginator(quotes, 25).get_page(request.GET.get('page'))
	return render(request, 'quotes/history.html', {'page': page})


@login_required
def detail(request, pk):
	quote = get_object_or_404(_quotes_for(request.user), pk=pk)
	recipients = quote.recipients.select_related('response', 'response__entered_by')
	for recipient in recipients:
		if not recipient.token:
			recipient.save()  # requests sent before online quotes existed get a link now
		recipient.link = mailer.quote_link(mailer.public_base_url(request), recipient.token)
	return render(request, 'quotes/detail.html', {
		'quote': quote, 'recipients': recipients, 'items': quote.items.all(),
		'received': sum(1 for recipient in recipients if hasattr(recipient, 'response')),
		'public_link_ready': bool(mailer.settings.PORTAL_PUBLIC_URL),
	})


# ---------------------------------------------------------------- vendor quote form (online and staff entry)

class VendorQuoteForm(forms.ModelForm):
	class Meta:
		model = VendorQuote
		fields = ('lump_sum', 'lump_sum_gst_percent', 'freight', 'delivery', 'payment_terms', 'validity', 'remarks', 'attachment')
		labels = {
			'lump_sum': 'Total amount (excluding GST)', 'lump_sum_gst_percent': 'GST %',
			'freight': 'Freight / transport to site (₹, excluding GST)', 'delivery': 'Delivery period',
			'payment_terms': 'Payment terms', 'validity': 'Offer valid for', 'remarks': 'Remarks',
			'attachment': 'Your quotation document (optional)',
		}
		widgets = {
			'delivery': forms.TextInput(attrs={'placeholder': 'e.g. 7 days from PO'}),
			'payment_terms': forms.TextInput(attrs={'placeholder': 'e.g. 30 days credit'}),
			'validity': forms.TextInput(attrs={'placeholder': 'e.g. 15 days'}),
			'remarks': forms.Textarea(attrs={'rows': 3}),
		}
		help_texts = {'freight': 'Leave empty if rates include delivery to site.', 'attachment': 'PDF, Excel, Word or image, up to 10 MB.'}

	def __init__(self, *args, has_items=True, **kwargs):
		super().__init__(*args, **kwargs)
		if has_items:
			del self.fields['lump_sum']
			del self.fields['lump_sum_gst_percent']
		else:
			self.fields['lump_sum'].required = True

	def clean_attachment(self):
		attachment = self.cleaned_data.get('attachment')
		if attachment and hasattr(attachment, 'size'):
			if attachment.size > MAX_ATTACHMENT_MB * 1024 * 1024:
				raise forms.ValidationError(f'This file is {attachment.size / 1024 / 1024:.1f} MB; the limit is {MAX_ATTACHMENT_MB} MB.')
			if not attachment.name.lower().endswith(RESPONSE_FILE_TYPES):
				raise forms.ValidationError('Upload a PDF, Excel, Word, CSV or image file.')
		return attachment

	def clean_lump_sum_gst_percent(self):
		return _check_gst(self.cleaned_data.get('lump_sum_gst_percent'))


def _check_gst(value):
	if value is not None and not 0 <= value <= 40:
		raise forms.ValidationError('GST must be between 0 and 40 %.')
	return value


def _line_inputs(post, items, existing):
	"""Per-item rate/GST/remark rows for the template, plus parsed values and errors."""
	rows, parsed, errors = [], {}, []
	for item in items:
		line = existing.get(item.pk)
		if post is None:
			rate = '' if line is None else f'{line.rate:f}'
			gst = '18' if line is None else f'{line.gst_percent.normalize():f}'
			remark = '' if line is None else line.remark
		else:
			rate, gst, remark = (post.get(f'{name}_{item.pk}', '').strip() for name in ('rate', 'gst', 'remark'))
			if rate:
				rate_value, gst_value = _decimal(rate), _decimal(gst or '0')
				if rate_value is None or rate_value < 0:
					errors.append(f'“{item.description}”: the rate “{rate}” is not a number. Enter the unit rate, e.g. 58500 or 58,500.50.')
				elif gst_value is None or not 0 <= gst_value <= 40:
					errors.append(f'“{item.description}”: GST “{gst}” must be a number between 0 and 40.')
				else:
					parsed[item.pk] = (rate_value, gst_value, remark[:200])
		rows.append({'item': item, 'rate': rate, 'gst': gst, 'remark': remark})
	return rows, parsed, errors


def _quote_page(request, recipient, staff):
	quote_request = recipient.request
	items = list(quote_request.items.all())
	existing_quote = getattr(recipient, 'response', None)
	existing_lines = {line.item_id: line for line in existing_quote.lines.all()} if existing_quote else {}
	closed = not staff and not quote_request.is_open
	post = request.POST if request.method == 'POST' and not closed else None
	form = VendorQuoteForm(post, request.FILES if post is not None else None, instance=existing_quote, has_items=bool(items))
	rows, parsed, line_errors = _line_inputs(post, items, existing_lines)
	if post is not None:
		if items and not parsed and not line_errors:
			line_errors.append('Enter a rate for at least one item. Leave a rate empty only for items you cannot supply.')
		if form.is_valid() and not line_errors:
			with transaction.atomic():
				response = form.save(commit=False)
				response.recipient = recipient
				response.entered_by = request.user if staff else None
				if existing_quote:
					response.revisions += 1
				response.save()
				response.lines.all().delete()
				for item_id, (rate, gst, remark) in parsed.items():
					VendorQuoteLine.objects.create(quote=response, item_id=item_id, rate=rate, gst_percent=gst, remark=remark)
			if staff:
				messages.success(request, f'Quote from {recipient.vendor_name} saved.')
				return redirect('quotes:detail', quote_request.pk)
			return render(request, 'quotes/respond_done.html', {'recipient': recipient, 'quote_request': quote_request, 'revised': bool(existing_quote)})
	return render(request, 'quotes/respond.html', {
		'recipient': recipient, 'quote_request': quote_request, 'form': form, 'rows': rows, 'line_errors': line_errors,
		'staff': staff, 'closed': closed, 'existing': existing_quote, 'has_items': bool(items),
		'gst_choices': GST_CHOICES,
	})


@never_cache
def respond(request, token):
	"""Public page (no login) where a vendor submits or revises their quote using the link from the email."""
	recipient = get_object_or_404(QuoteRecipient.objects.select_related('request'), token=token)
	response = _quote_page(request, recipient, staff=False)
	response['X-Robots-Tag'] = 'noindex, nofollow'
	response['Referrer-Policy'] = 'same-origin'  # link never leaks to other sites; 'no-referrer' would make browsers send Origin: null and fail the CSRF check
	return response


@login_required
def enter_quote(request, pk, recipient_pk):
	"""Staff type in a quote that arrived by email, WhatsApp or on paper."""
	quote_request = get_object_or_404(_quotes_for(request.user), pk=pk)
	recipient = get_object_or_404(quote_request.recipients.all(), pk=recipient_pk)
	return _quote_page(request, recipient, staff=True)


# ---------------------------------------------------------------- comparative statement

@login_required
def compare(request, pk):
	quote_request = get_object_or_404(_quotes_for(request.user), pk=pk)
	rows, columns = comparison.build(quote_request)
	return render(request, 'quotes/compare.html', {
		'quote': quote_request, 'rows': rows, 'columns': columns,
		'waiting': quote_request.recipients.filter(response__isnull=True, status=QuoteRecipient.Status.SENT).count(),
	})


@login_required
def compare_export(request, pk):
	quote_request = get_object_or_404(_quotes_for(request.user), pk=pk)
	rows, columns = comparison.build(quote_request)
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = 'Comparative statement'
	bold, head_fill, low_fill = Font(bold=True), PatternFill('solid', fgColor='DCE6F2'), PatternFill('solid', fgColor='D9F2E2')
	sheet.append(['Comparative statement'])
	sheet['A1'].font = Font(bold=True, size=14)
	sheet.append([quote_request.title])
	sheet.append([f'Requested {quote_request.created_at:%d %b %Y} by {quote_request.sent_by or "—"}'
	              + (f' · last date {quote_request.due_date:%d %b %Y}' if quote_request.due_date else '')])
	sheet.append([])
	vendor_head = ['Sl', 'Item', 'Qty', 'Unit']
	for column in columns:
		vendor_head += [f'{column.recipient.vendor_name} ({column.rank or "incomplete"})', '', '']
	sheet.append(vendor_head)
	sheet.append(['', '', '', ''] + ['Rate', 'GST %', 'Amount'] * len(columns))
	for row in sheet.iter_rows(min_row=5, max_row=6):
		for cell in row:
			cell.font, cell.fill = bold, head_fill
	for number, row in enumerate(rows, start=1):
		values = [number, row.item.description, float(row.item.quantity), row.item.unit]
		for cell in row.cells:
			values += [float(cell['rate']), float(cell['gst']), float(cell['amount'])] if cell else ['not quoted', '', '']
		sheet.append(values)
		for index, cell in enumerate(row.cells):
			if cell and cell['lowest']:
				sheet.cell(row=sheet.max_row, column=5 + index * 3).fill = low_fill
	for label, attr in (('Total before GST', 'basic'), ('GST', 'gst'), ('Freight', 'freight'), ('Landed total', 'landed')):
		values = ['', label, '', '']
		for column in columns:
			values += ['', '', float(getattr(column, attr))]
		sheet.append(values)
		sheet.cell(row=sheet.max_row, column=2).font = bold
	for label, attr in (('Rank', 'rank'), ('Delivery', 'delivery'), ('Payment terms', 'payment_terms'), ('Validity', 'validity'), ('Remarks', 'remarks')):
		values = ['', label, '', '']
		for column in columns:
			value = column.rank or 'incomplete' if attr == 'rank' else getattr(column.quote, attr)
			values += [value, '', '']
		sheet.append(values)
		sheet.cell(row=sheet.max_row, column=2).font = bold
	sheet.column_dimensions['B'].width = 42
	for index in range(len(columns) * 3):
		sheet.column_dimensions[sheet.cell(row=6, column=5 + index).column_letter].width = 14
	output = BytesIO()
	workbook.save(output)
	response = HttpResponse(output.getvalue(), content_type=XLSX_CONTENT_TYPE)
	name = slugify(quote_request.title)[:40] or 'quotes'
	response['Content-Disposition'] = f'attachment; filename="comparative_statement_{name}.xlsx"'
	return response


@login_required
def response_file(request, pk, recipient_pk):
	"""A vendor's uploaded quotation document, for signed-in staff who can see the request."""
	quote_request = get_object_or_404(_quotes_for(request.user), pk=pk)
	recipient = get_object_or_404(quote_request.recipients.select_related('response'), pk=recipient_pk)
	response = getattr(recipient, 'response', None)
	if response is None or not response.attachment:
		raise Http404('No document uploaded.')
	return FileResponse(response.attachment.open('rb'), as_attachment=False, filename=response.attachment.name.rsplit('/', 1)[-1])
