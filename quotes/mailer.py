"""Fill the quote-request template for each vendor and send one separate email per vendor.

Each vendor gets its own message addressed only to that vendor's email address(es): no CC and no BCC,
so vendors never see who else was asked to quote.
"""
import re
import smtplib

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from scportal.emails import split_emails
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import QuoteRecipient

PLACEHOLDERS = {
	'{vendor_name}': 'Vendor / firm name',
	'{contact_person}': 'Contact person (or “Sir/Madam” when not recorded)',
	'{vendor_code}': 'Vendor code',
	'{city}': 'Vendor city',
	'{requirement}': 'The requirement you type below',
	'{your_name}': 'Your name',
}
PLACEHOLDER_PATTERN = re.compile(r'\{[^{}\s]{1,40}\}')
MAX_VENDORS = 100

DEFAULT_SUBJECT = 'Request for quotation – VISHWA Infrastructures – {vendor_name}'
DEFAULT_BODY = """Dear {contact_person},

Greetings from VISHWA Infrastructures & Services Pvt. Ltd.

We request your best quotation for the following requirement:

{requirement}

Please include unit rates, GST, delivery period to site, payment terms and the validity of your offer.

Kindly send your quotation by reply to this email.

Regards,
{your_name}
VISHWA Infrastructures & Services Pvt. Ltd.
"""


def unknown_placeholders(*texts):
	found = {token for text in texts for token in PLACEHOLDER_PATTERN.findall(text or '')}
	return sorted(found - set(PLACEHOLDERS))


def sender_name(user):
	return (user.get_full_name() or user.get_username()).strip()


def fill(text, vendor, requirement, user):
	values = {
		'{vendor_name}': vendor.name,
		'{contact_person}': (vendor.contact_person or '').strip() or 'Sir/Madam',
		'{vendor_code}': vendor.code_value,
		'{city}': vendor.city or '',
		'{requirement}': requirement.strip(),
		'{your_name}': sender_name(user),
	}
	for token, value in values.items():
		text = text.replace(token, value)
	return text


def selected_vendors(selection):
	"""Vendors from 'supplier:12' / 'subcontractor:5' strings, in the order given, without repeats."""
	wanted, seen = [], set()
	for item in selection:
		kind, _, pk = str(item).partition(':')
		if kind in (QuoteRecipient.Kind.SUPPLIER, QuoteRecipient.Kind.SUBCONTRACTOR) and pk.isdigit() and (kind, int(pk)) not in seen:
			seen.add((kind, int(pk)))
			wanted.append((kind, int(pk)))
	suppliers = Supplier.objects.filter(archived_at__isnull=True, pk__in=[pk for kind, pk in wanted if kind == 'supplier']).in_bulk()
	subcontractors = DirectSubcontractor.objects.filter(
		archived_at__isnull=True, pk__in=[pk for kind, pk in wanted if kind == 'subcontractor'],
	).in_bulk()
	vendors = []
	for kind, pk in wanted:
		vendor = (suppliers if kind == 'supplier' else subcontractors).get(pk)
		if vendor is None:
			continue
		vendor.kind = kind
		vendor.kind_label = QuoteRecipient.Kind(kind).label
		vendor.code_value = vendor.vendor_code if kind == 'supplier' else vendor.code
		vendor.selection_key = f'{kind}:{pk}'
		vendor.email_addresses = split_emails(vendor.email)
		vendors.append(vendor)
	return vendors


def build_message(vendor, quote, user, to=None, attachment=None):
	message = EmailMessage(
		subject=fill(quote.subject, vendor, quote.requirement, user),
		body=fill(quote.body, vendor, quote.requirement, user),
		from_email=settings.DEFAULT_FROM_EMAIL,
		to=to or vendor.email_addresses,
		reply_to=[quote.reply_to] if quote.reply_to else None,
	)
	if attachment:
		message.attach(*attachment)
	return message


def read_attachment(quote):
	if not quote.attachment:
		return None
	quote.attachment.open('rb')
	try:
		content = quote.attachment.read()
	finally:
		quote.attachment.close()
	return (quote.attachment.name.rsplit('/', 1)[-1], content)


def explain_mail_error(exc):
	"""A plain-language reason for a mail server error, for the people sending quotes."""
	text = str(exc)
	login_refused = (
		isinstance(exc, smtplib.SMTPAuthenticationError)
		or (isinstance(exc, smtplib.SMTPServerDisconnected) and 'unexpectedly closed' in text)
	)
	if login_refused:
		hint = (
			' Gmail and Google Workspace need an app password (myaccount.google.com/apppasswords), not the normal password.'
			if 'gmail' in settings.EMAIL_HOST.lower() else ''
		)
		return f'The mail server refused to sign in to {settings.EMAIL_HOST_USER}: the email password in the portal settings (.env) is wrong or not allowed.{hint} Ask the portal administrator to fix it.'
	if isinstance(exc, (TimeoutError, OSError)) and not isinstance(exc, smtplib.SMTPException):
		return f'Could not reach the mail server {settings.EMAIL_HOST}:{settings.EMAIL_PORT} ({text}). The network may be blocking it.'
	return f'The mail server reported an error: {text}'


def send_all(quote, vendors, user):
	"""Send one email per vendor and record the outcome for each. Returns the QuoteRecipient rows."""
	attachment = read_attachment(quote)
	results = []
	connection = get_connection(fail_silently=False)
	try:
		connection.open()
	except Exception as exc:  # Server unreachable or login refused: record it against every vendor.
		connection = None
		open_error = explain_mail_error(exc)
	for vendor in vendors:
		recipient = QuoteRecipient(
			request=quote, kind=vendor.kind, vendor_id=vendor.pk, vendor_code=vendor.code_value,
			vendor_name=vendor.name, emails='; '.join(vendor.email_addresses),
		)
		if not vendor.email_addresses:
			recipient.status = QuoteRecipient.Status.SKIPPED
		elif connection is None:
			recipient.status, recipient.error = QuoteRecipient.Status.FAILED, open_error
		else:
			try:
				message = build_message(vendor, quote, user, attachment=attachment)
				message.connection = connection
				message.send()
				recipient.status, recipient.sent_at = QuoteRecipient.Status.SENT, timezone.now()
			except Exception as exc:
				recipient.status, recipient.error = QuoteRecipient.Status.FAILED, explain_mail_error(exc)[:1000]
		recipient.save()
		results.append(recipient)
	if connection is not None:
		connection.close()
	return results


def email_configured():
	return bool(getattr(settings, 'EMAIL_HOST', '')) or settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend'
