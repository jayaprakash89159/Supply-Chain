from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from projects.models import Project
from quotes import comparison, mailer
from quotes.models import QuoteRequest
from scportal.gstin import STATE_CODES
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from . import pdf
from .models import ApprovalLevel, POApproval, PurchaseOrder, PurchaseOrderLine, PurchaseSettings
from .numbers import next_po_number, rupees_in_words

admin_required = user_passes_test(lambda user: user.is_superuser)
VENDOR_MODELS = {'supplier': Supplier, 'subcontractor': DirectSubcontractor}
STATE_CHOICES = [('', '— same as company —')] + sorted(((code, f'{name} ({code})') for code, name in STATE_CODES.items()), key=lambda c: c[1])


def _decimal(text):
	try:
		value = Decimal(str(text).strip().replace(',', ''))
	except InvalidOperation:
		return None
	return value if value.is_finite() else None


# ---------------------------------------------------------------- permissions

def is_approver(user):
	return user.is_authenticated and ApprovalLevel.objects.filter(is_active=True, approvers=user).exists()


def can_view(user, order):
	return user.is_superuser or order.created_by_id == user.pk or is_approver(user)


def can_approve(user, order):
	"""(allowed, reason) for the PO's current approval step."""
	if order.status != PurchaseOrder.Status.PENDING:
		return False, 'This PO is not waiting for approval.'
	level = order.next_level()
	if level is None:
		return False, 'No approval step is waiting.'
	if not level.approvers.filter(pk=user.pk).exists():
		return False, f'Waiting for {level.name}.'
	if order.created_by_id == user.pk and not PurchaseSettings.load().allow_self_approval:
		return False, 'You created this PO, so someone else must approve it (maker-checker).'
	return True, ''


def _order_or_404(request, pk):
	order = get_object_or_404(PurchaseOrder.objects.select_related('created_by', 'quote_request', 'project'), pk=pk)
	if not can_view(request.user, order):
		raise Http404
	return order


# ---------------------------------------------------------------- award from the comparative statement

def _vendor_snapshot(kind, vendor_id):
	vendor = VENDOR_MODELS[kind].objects.filter(pk=vendor_id).first()
	if vendor is None:
		return {}
	address = ', '.join(part for part in (vendor.full_address, vendor.city, vendor.state, vendor.pin_code) if part)
	state_code = (vendor.gstin or '')[:2] if (vendor.gstin or '')[:2].isdigit() else (vendor.gst_state_code or '')
	return {
		'vendor_address': address, 'vendor_gstin': vendor.gstin or '', 'vendor_state_code': state_code,
		'vendor_contact': vendor.contact_person or '', 'vendor_phone': vendor.mobile_number or '', 'vendor_email': vendor.email or '',
	}


@admin_required
def award(request, quote_pk):
	quote_request = get_object_or_404(QuoteRequest, pk=quote_pk)
	rows, columns = comparison.build(quote_request)
	if not rows or not columns:
		messages.error(request, 'Awarding needs an item list and at least one quote. Enter quotes first.')
		return redirect('quotes:compare', quote_request.pk)
	active_orders = quote_request.purchase_orders.exclude(status=PurchaseOrder.Status.CANCELLED)
	ordered_items = set(PurchaseOrderLine.objects.filter(order__in=active_orders).values_list('quote_item_id', flat=True))
	recipients = {column.recipient.pk: column for column in columns}

	choices = []
	for row in rows:
		options = []
		for column, cell in zip(columns, row.cells):
			if cell:
				options.append({'recipient': column.recipient, 'rate': cell['rate'], 'gst': cell['gst'], 'amount': cell['amount'], 'lowest': cell['rate'] == row.lowest_rate, 'rank': column.rank})
		lowest = next((option['recipient'].pk for option in options if option['lowest']), None)
		choices.append({'item': row.item, 'options': options, 'lowest': lowest, 'ordered': row.item.pk in ordered_items,
		                'chosen': str(request.POST.get(f'award_{row.item.pk}', lowest or '')) if request.method == 'POST' else str(lowest or '')})

	errors = []
	if request.method == 'POST':
		picks, not_lowest = {}, []
		for choice in choices:
			if choice['ordered']:
				continue
			value = request.POST.get(f'award_{choice["item"].pk}', '')
			if not value:
				continue
			if not value.isdigit() or int(value) not in recipients or not any(o['recipient'].pk == int(value) for o in choice['options']):
				errors.append(f'“{choice["item"].description}”: choose one of the vendors who quoted it.')
				continue
			picks.setdefault(int(value), []).append(choice['item'])
			if int(value) != choice['lowest']:
				not_lowest.append(choice['item'].description)
		reason = request.POST.get('reason', '').strip()
		if not picks and not errors:
			errors.append('Choose a vendor for at least one item.')
		if not_lowest and not reason:
			errors.append(f'You chose a vendor other than the lowest rate for: {", ".join(not_lowest)}. Give the reason (e.g. delivery time, quality, credit terms).')
		if not errors:
			settings_row = PurchaseSettings.load()
			created = []
			with transaction.atomic():
				for recipient_pk, items in picks.items():
					column = recipients[recipient_pk]
					recipient, response = column.recipient, column.quote
					order = PurchaseOrder.objects.create(
						quote_request=quote_request, recipient=recipient, vendor_kind=recipient.kind, vendor_id=recipient.vendor_id,
						vendor_code=recipient.vendor_code, vendor_name=recipient.vendor_name, **_vendor_snapshot(recipient.kind, recipient.vendor_id),
						delivery_address=quote_request.notes, payment_terms=response.payment_terms, freight=response.freight or 0,
						terms=settings_row.default_terms, award_reason=reason if not_lowest else '', created_by=request.user,
						place_of_supply=settings_row.company_state_code,
					)
					for position, item in enumerate(items, start=1):
						line = column.lines[item.pk]
						PurchaseOrderLine.objects.create(
							order=order, position=position, quote_item=item, description=item.description, quantity=item.quantity,
							unit=item.unit, rate=line.rate, gst_percent=line.gst_percent, remark=line.remark,
						)
					created.append(order)
			messages.success(request, f'Created {len(created)} draft PO{"s" if len(created) != 1 else ""}. Check delivery details and terms, then submit each for approval.')
			return redirect('purchase:detail', created[0].pk) if len(created) == 1 else redirect(f'{reverse("purchase:list")}?rfq={quote_request.pk}')

	return render(request, 'purchase/award.html', {
		'quote': quote_request, 'choices': choices, 'columns': columns, 'errors': errors,
		'reason': request.POST.get('reason', ''), 'active_orders': active_orders,
	})


# ---------------------------------------------------------------- list

@login_required
def order_list(request):
	if not (request.user.is_superuser or is_approver(request.user)):
		orders = PurchaseOrder.objects.filter(created_by=request.user)
	else:
		orders = PurchaseOrder.objects.all()
	orders = orders.select_related('created_by').prefetch_related('lines', 'approvals')
	status = request.GET.get('status', '')
	if status in PurchaseOrder.Status.values:
		orders = orders.filter(status=status)
	rfq = request.GET.get('rfq', '')
	if rfq.isdigit():
		orders = orders.filter(quote_request_id=int(rfq))
	q = request.GET.get('q', '').strip()
	if q:
		orders = orders.filter(Q(number__icontains=q) | Q(vendor_name__icontains=q) | Q(vendor_code__icontains=q) | Q(lines__description__icontains=q)).distinct()
	mine = request.GET.get('mine') == '1'
	page_orders = list(orders)
	for order in page_orders:
		order.next = order.next_level() if order.status == PurchaseOrder.Status.PENDING else None
		order.my_turn = can_approve(request.user, order)[0] if order.next else False
	if mine:
		page_orders = [order for order in page_orders if order.my_turn]
	page = Paginator(page_orders, 25).get_page(request.GET.get('page'))
	query = request.GET.copy()
	query.pop('page', None)
	return render(request, 'purchase/list.html', {
		'page': page, 'statuses': PurchaseOrder.Status.choices, 'status': status, 'q': q, 'mine': mine,
		'query_string': query.urlencode(), 'rfq': rfq,
	})


# ---------------------------------------------------------------- one PO

class OrderForm(forms.ModelForm):
	place_of_supply = forms.ChoiceField(choices=STATE_CHOICES, required=False, label='Place of supply (delivery state)')

	class Meta:
		model = PurchaseOrder
		fields = ('project', 'delivery_address', 'place_of_supply', 'delivery_date', 'payment_terms', 'freight', 'freight_gst_percent', 'notes', 'terms')
		widgets = {
			'delivery_address': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Site name, full address, site contact and phone'}),
			'delivery_date': forms.DateInput(attrs={'type': 'date'}),
			'notes': forms.Textarea(attrs={'rows': 3}), 'terms': forms.Textarea(attrs={'rows': 8}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['project'].queryset = Project.objects.exclude(status__in=['complete', 'cancelled'])
		self.fields['project'].required = False


def _save_lines(order, post):
	errors = []
	for line in order.lines.all():
		quantity, rate, gst = (_decimal(post.get(f'{name}_{line.pk}', '')) for name in ('qty', 'rate', 'gst'))
		if quantity is None or quantity <= 0:
			errors.append(f'“{line.description}”: quantity must be a number above 0.')
		elif rate is None or rate < 0:
			errors.append(f'“{line.description}”: rate must be a number.')
		elif gst is None or not 0 <= gst <= 40:
			errors.append(f'“{line.description}”: GST must be between 0 and 40.')
		else:
			line.quantity, line.rate, line.gst_percent = quantity, rate, gst
			line.save(update_fields=['quantity', 'rate', 'gst_percent'])
	return errors


def _notify_approvers(request, order):
	level = order.next_level()
	if level is None or not mailer.email_configured():
		return
	emails = [user.email for user in level.approvers.all() if user.email and user.pk != request.user.pk]
	if not emails:
		return
	link = request.build_absolute_uri(reverse('purchase:detail', args=[order.pk]))
	total = order.totals()['grand']
	from quotes.templatetags.humanize_inr import inr
	try:
		EmailMessage(
			f'PO for approval: {order.vendor_name} – Rs. {inr(total)}',
			f'A purchase order is waiting for your approval ({level.name}).\n\nVendor: {order.vendor_name}\nTotal: Rs. {inr(total)}\n'
			f'Created by: {order.created_by}\n\nOpen it: {link}\n',
			to=emails,
		).send()
	except Exception:
		messages.warning(request, 'The approvers could not be emailed (mail server problem); they will still see it under Purchase orders.')


@login_required
def detail(request, pk):
	order = _order_or_404(request, pk)
	editable = order.editable and request.user.is_superuser
	form = OrderForm(request.POST or None, instance=order) if editable else None
	line_errors = []
	if request.method == 'POST' and editable:
		line_errors = _save_lines(order, request.POST)
		if form.is_valid() and not line_errors:
			form.save()
			messages.success(request, 'PO saved.')
			return redirect('purchase:detail', order.pk)
	allowed, reason = can_approve(request.user, order)
	levels = order.required_levels()
	approved = order.approved_level_ids()
	return render(request, 'purchase/detail.html', {
		'order': order, 'form': form, 'line_errors': line_errors, 'lines': order.lines.all(), 'totals': order.totals(),
		'in_words': rupees_in_words(order.totals()['grand']), 'can_approve': allowed, 'approve_reason': reason,
		'steps': [{'level': level, 'done': level.pk in approved} for level in levels],
		'trail': order.approvals.select_related('by'), 'editable': editable,
		'place_name': STATE_CODES.get(order.place_of_supply or PurchaseSettings.load().company_state_code, ''),
		'no_levels': not ApprovalLevel.objects.filter(is_active=True).exists(),
	})


@require_POST
@admin_required
def submit(request, pk):
	order = _order_or_404(request, pk)
	if not order.editable:
		messages.error(request, 'Only draft or returned POs can be submitted.')
		return redirect('purchase:detail', order.pk)
	problems = []
	if not order.lines.exists():
		problems.append('the PO has no items')
	if not order.delivery_address.strip():
		problems.append('“Deliver to” is empty')
	if not order.delivery_date:
		problems.append('the delivery date is missing')
	levels = order.required_levels()
	if not ApprovalLevel.objects.filter(is_active=True).exists():
		problems.append('no approval levels are set up (Purchase orders → Approval settings)')
	elif any(not level.approvers.exists() for level in levels):
		problems.append('an approval level has no approvers')
	if problems:
		messages.error(request, 'Fix this before submitting: ' + '; '.join(problems) + '.')
		return redirect('purchase:detail', order.pk)
	with transaction.atomic():
		order.status, order.submitted_at = PurchaseOrder.Status.PENDING, timezone.now()
		order.save(update_fields=['status', 'submitted_at', 'updated_at'])
		POApproval.objects.create(order=order, decision=POApproval.Decision.SUBMITTED, round=order.approval_round + 1, by=request.user)
	_advance(request, order)
	return redirect('purchase:detail', order.pk)


def _advance(request, order):
	"""Finish approval when no level is left; otherwise tell the next approvers."""
	if order.next_level() is None:
		order.status, order.approved_at = PurchaseOrder.Status.APPROVED, timezone.now()
		order.number = order.number or next_po_number(PurchaseSettings.load().po_prefix)
		order.save(update_fields=['status', 'approved_at', 'number', 'updated_at'])
		messages.success(request, f'PO approved and numbered {order.number}. Download the PDF or send it to the vendor.')
	else:
		_notify_approvers(request, order)
		messages.success(request, f'Waiting for approval: {order.next_level().name}.')


@require_POST
@login_required
def decide(request, pk):
	order = _order_or_404(request, pk)
	allowed, reason = can_approve(request.user, order)
	if not allowed:
		messages.error(request, reason)
		return redirect('purchase:detail', order.pk)
	level = order.next_level()
	decision = request.POST.get('decision')
	comment = request.POST.get('comment', '').strip()
	if decision == 'reject' and not comment:
		messages.error(request, 'Say what needs to change when returning a PO.')
		return redirect('purchase:detail', order.pk)
	with transaction.atomic():
		POApproval.objects.create(
			order=order, level=level, level_name=level.name, round=order.approval_round, by=request.user, comment=comment,
			decision=POApproval.Decision.APPROVED if decision == 'approve' else POApproval.Decision.REJECTED,
		)
		if decision == 'approve':
			_advance(request, order)
		else:
			order.status = PurchaseOrder.Status.REJECTED
			order.save(update_fields=['status', 'updated_at'])
			messages.success(request, 'PO returned for changes.')
	return redirect('purchase:detail', order.pk)


@login_required
def order_pdf(request, pk):
	order = _order_or_404(request, pk)
	response = HttpResponse(pdf.render(order), content_type='application/pdf')
	name = (order.number or f'DRAFT-{order.pk}').replace('/', '-')
	response['Content-Disposition'] = f'inline; filename="PO-{name}.pdf"'
	return response


@require_POST
@admin_required
def send(request, pk):
	order = _order_or_404(request, pk)
	if order.status not in (PurchaseOrder.Status.APPROVED, PurchaseOrder.Status.SENT):
		messages.error(request, 'Only fully approved POs can be sent.')
		return redirect('purchase:detail', order.pk)
	how = request.POST.get('how')
	if how == 'email':
		emails = mailer.split_emails(order.vendor_email)
		if not emails:
			messages.error(request, 'The vendor has no email address. Download the PDF and send it another way, then click “Mark as sent”.')
			return redirect('purchase:detail', order.pk)
		if not mailer.email_configured():
			messages.error(request, 'Email sending is not set up yet. Download the PDF and use “Mark as sent”.')
			return redirect('purchase:detail', order.pk)
		from quotes.templatetags.humanize_inr import inr
		message = EmailMessage(
			f'Purchase Order {order.number} – {PurchaseSettings.load().company_name}',
			f'Dear {order.vendor_contact or "Sir/Madam"},\n\nPlease find attached our Purchase Order {order.number} '
			f'for Rs. {inr(order.totals()["grand"])}.\n\nKindly acknowledge receipt and confirm the delivery date.\n\n'
			f'Regards,\n{mailer.sender_name(request.user)}\n{PurchaseSettings.load().company_name}\n',
			to=emails, reply_to=[request.user.email] if request.user.email else None,
		)
		message.attach(f'PO-{order.number.replace("/", "-")}.pdf', pdf.render(order), 'application/pdf')
		try:
			message.send()
		except Exception as exc:
			messages.error(request, f'The PO could not be emailed. {mailer.explain_mail_error(exc)}')
			return redirect('purchase:detail', order.pk)
		note = f'Emailed to {", ".join(emails)}'
	else:
		note = 'Marked as sent (PDF shared outside the portal)'
	order.status, order.sent_at, order.sent_by = PurchaseOrder.Status.SENT, timezone.now(), request.user
	order.save(update_fields=['status', 'sent_at', 'sent_by', 'updated_at'])
	POApproval.objects.create(order=order, decision=POApproval.Decision.SENT, round=order.approval_round, by=request.user, comment=note)
	messages.success(request, f'{order.number}: {note}.')
	return redirect('purchase:detail', order.pk)


@require_POST
@admin_required
def cancel(request, pk):
	order = _order_or_404(request, pk)
	reason = request.POST.get('reason', '').strip()
	if order.status == PurchaseOrder.Status.CANCELLED:
		return redirect('purchase:detail', order.pk)
	if not reason:
		messages.error(request, 'Give a reason for cancelling the PO.')
		return redirect('purchase:detail', order.pk)
	order.status = PurchaseOrder.Status.CANCELLED
	order.save(update_fields=['status', 'updated_at'])
	POApproval.objects.create(order=order, decision=POApproval.Decision.CANCELLED, round=order.approval_round, by=request.user, comment=reason)
	messages.success(request, f'{order.display_number} cancelled. Its items can be awarded again.')
	return redirect('purchase:detail', order.pk)


# ---------------------------------------------------------------- settings

class SettingsForm(forms.ModelForm):
	class Meta:
		model = PurchaseSettings
		fields = ('company_name', 'company_address', 'company_gstin', 'company_state_code', 'company_phone', 'company_email', 'po_prefix', 'allow_self_approval', 'default_terms')
		widgets = {'company_address': forms.Textarea(attrs={'rows': 2}), 'default_terms': forms.Textarea(attrs={'rows': 8})}


@admin_required
def approval_settings(request):
	settings_row = PurchaseSettings.load()
	users = get_user_model().objects.filter(is_active=True).order_by('username')
	form = SettingsForm(request.POST if request.POST.get('action') == 'settings' else None, instance=settings_row)
	action = request.POST.get('action')
	if request.method == 'POST':
		if action == 'settings' and form.is_valid():
			form.save()
			messages.success(request, 'Purchase settings saved.')
			return redirect('purchase:settings')
		if action == 'save_level':
			level_id = request.POST.get('level_id', '')
			level = ApprovalLevel.objects.filter(pk=level_id).first() if level_id.isdigit() else ApprovalLevel()
			name = request.POST.get('name', '').strip()
			order_no = request.POST.get('order', '').strip()
			amount = _decimal(request.POST.get('min_amount', '0') or '0')
			approver_ids = [int(v) for v in request.POST.getlist('approvers') if v.isdigit()]
			problems = []
			if not name:
				problems.append('give the level a name')
			if not order_no.isdigit() or int(order_no) < 1:
				problems.append('the step number must be 1 or more')
			elif ApprovalLevel.objects.filter(order=int(order_no)).exclude(pk=level.pk).exists():
				problems.append(f'step {order_no} is already used')
			if amount is None or amount < 0:
				problems.append('the amount must be 0 or more')
			if not approver_ids:
				problems.append('choose at least one approver')
			if problems:
				messages.error(request, 'Approval level not saved: ' + '; '.join(problems) + '.')
			else:
				level.name, level.order, level.min_amount = name, int(order_no), amount
				level.is_active = request.POST.get('is_active') == 'on'
				level.save()
				level.approvers.set(users.filter(pk__in=approver_ids))
				messages.success(request, f'Approval level “{name}” saved.')
			return redirect('purchase:settings')
		if action == 'delete_level':
			ApprovalLevel.objects.filter(pk=request.POST.get('level_id')).delete()
			messages.success(request, 'Approval level removed. POs already approved keep their trail.')
			return redirect('purchase:settings')
	levels = ApprovalLevel.objects.prefetch_related('approvers')
	return render(request, 'purchase/settings.html', {
		'form': form, 'levels': levels, 'users': users, 'next_order': (max((l.order for l in levels), default=0) + 1),
	})
