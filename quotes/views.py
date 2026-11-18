from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import mailer
from .models import QuoteRecipient, QuoteRequest

MAX_ATTACHMENT_MB = 10


class QuoteForm(forms.Form):
	subject = forms.CharField(max_length=255, initial=mailer.DEFAULT_SUBJECT)
	requirement = forms.CharField(
		widget=forms.Textarea(attrs={'rows': 6, 'placeholder': 'e.g.\nTMT bars Fe 500D, 12 mm – 25 MT\nTMT bars Fe 500D, 16 mm – 18 MT\nDelivery: Kollapur site, by 15 December'}),
		help_text='Items, sizes, quantities, delivery place and date. Goes where {requirement} is in the message.',
	)
	body = forms.CharField(label='Message', widget=forms.Textarea(attrs={'rows': 16}), initial=mailer.DEFAULT_BODY)
	attachment = forms.FileField(
		required=False, label='Attachment (optional)',
		help_text=f'One file, e.g. BOQ, drawing or specification. Up to {MAX_ATTACHMENT_MB} MB. Sent to every vendor.',
	)

	def clean_attachment(self):
		attachment = self.cleaned_data.get('attachment')
		if attachment and attachment.size > MAX_ATTACHMENT_MB * 1024 * 1024:
			raise forms.ValidationError(f'This file is {attachment.size / 1024 / 1024:.1f} MB; the limit is {MAX_ATTACHMENT_MB} MB.')
		return attachment

	def clean(self):
		data = super().clean()
		unknown = mailer.unknown_placeholders(data.get('subject'), data.get('body'))
		if unknown:
			raise forms.ValidationError(
				f'Unknown placeholder(s): {", ".join(unknown)}. Use only: {", ".join(mailer.PLACEHOLDERS)}.'
			)
		if data.get('body') and '{requirement}' not in data['body']:
			self.add_error('body', 'Put {requirement} in the message where the requirement should appear.')
		return data


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

	form = QuoteForm() if step == 'select' else QuoteForm(request.POST, request.FILES)
	reply_to = request.user.email.strip()
	if step in ('send', 'test') and form.is_valid():
		quote = QuoteRequest(
			subject=form.cleaned_data['subject'], body=form.cleaned_data['body'],
			requirement=form.cleaned_data['requirement'], reply_to=reply_to, sent_by=request.user,
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
			quote.save()
			if form.cleaned_data['attachment']:
				quote.attachment = form.cleaned_data['attachment']
				quote.save(update_fields=['attachment'])
			results = mailer.send_all(quote, vendors, request.user)
			sent = sum(result.status == QuoteRecipient.Status.SENT for result in results)
			problems = len(results) - sent
			level = messages.success if not problems else messages.warning
			level(request, f'Sent {sent} separate email{"s" if sent != 1 else ""}' + (f'; {problems} vendor(s) not emailed — see below.' if problems else '.'))
			return redirect('quotes:detail', quote.pk)

	return render(request, 'quotes/compose.html', {
		'form': form, 'vendors': vendors, 'placeholders': mailer.PLACEHOLDERS, 'reply_to': reply_to,
		'emailable': sum(1 for vendor in vendors if vendor.email_addresses),
		'email_ready': mailer.email_configured(), 'back': back, 'your_name': mailer.sender_name(request.user),
	})


@login_required
def history(request):
	quotes = QuoteRequest.objects.select_related('sent_by').prefetch_related('recipients')
	if not request.user.is_superuser:
		quotes = quotes.filter(sent_by=request.user)
	page = Paginator(quotes, 25).get_page(request.GET.get('page'))
	return render(request, 'quotes/history.html', {'page': page})


@login_required
def detail(request, pk):
	quotes = QuoteRequest.objects.select_related('sent_by')
	if not request.user.is_superuser:
		quotes = quotes.filter(sent_by=request.user)
	quote = get_object_or_404(quotes, pk=pk)
	return render(request, 'quotes/detail.html', {'quote': quote, 'recipients': quote.recipients.all()})
