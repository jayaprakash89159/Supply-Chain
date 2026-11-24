"""Email administrators a list of vendor documents that have expired or expire soon.

Run weekly, e.g. from Windows Task Scheduler:
    docker compose exec -T web python manage.py send_document_alerts
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand

from documents.models import WARNING_DAYS, expiring_queryset
from documents.views import attach_vendors


class Command(BaseCommand):
	help = 'Email administrators the vendor documents that are expired or expire within 30 days.'

	def add_arguments(self, parser):
		parser.add_argument('--dry-run', action='store_true', help='Print the email instead of sending it.')

	def handle(self, *args, dry_run=False, **options):
		documents = attach_vendors(expiring_queryset(WARNING_DAYS))
		if not documents:
			self.stdout.write('No expired or expiring documents; no email sent.')
			return
		recipients = list(
			get_user_model().objects.filter(is_superuser=True, is_active=True).exclude(email='').values_list('email', flat=True)
		)
		expired = [document for document in documents if document.status == 'expired']
		expiring = [document for document in documents if document.status != 'expired']
		lines = [f'Vendor documents needing renewal ({len(expired)} expired, {len(expiring)} expiring within {WARNING_DAYS} days):', '']
		for title, group in (('EXPIRED', expired), (f'EXPIRING WITHIN {WARNING_DAYS} DAYS', expiring)):
			if group:
				lines.append(title)
				for document in group:
					lines.append(
						f'- {document.vendor.name} ({document.get_kind_display()}): {document.get_doc_type_display()}'
						f'{" " + document.number if document.number else ""} – {document.status_label}'
					)
				lines.append('')
		lines.append('Open the portal → Documents to see and renew them.')
		body = '\n'.join(lines)
		subject = f'Vendor documents: {len(expired)} expired, {len(expiring)} expiring soon'
		if dry_run or not recipients:
			if not recipients:
				self.stdout.write('No administrator has an email address set (Users page); printing instead.')
			self.stdout.write(f'Subject: {subject}\n\n{body}')
			return
		EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, to=recipients).send()
		self.stdout.write(f'Sent to {", ".join(recipients)}.')
