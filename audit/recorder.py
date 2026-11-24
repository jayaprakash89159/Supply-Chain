"""Record changes to suppliers, subcontractors and their documents in the audit log.

Saves through the model (forms, Excel upload, admin) are recorded automatically by signals. Bulk
``queryset.update()`` calls skip signals, so the code doing them calls ``record()`` itself.
"""
import contextvars
import datetime
from decimal import Decimal

from django.db.models.signals import post_delete, post_save, pre_save

from .models import AuditEntry

_current_user = contextvars.ContextVar('audit_user', default=None)
SKIP_FIELDS = {'id', 'created_at', 'updated_at', 'archived_at', 'archived_by'}


class CurrentUserMiddleware:
	"""Remember who is signed in, so changes saved during this request are credited to them."""

	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		user = getattr(request, 'user', None)
		token = _current_user.set(user if user is not None and user.is_authenticated else None)
		try:
			return self.get_response(request)
		finally:
			_current_user.reset(token)


def current_user():
	return _current_user.get()


def kind_of(instance):
	return {'Supplier': 'supplier', 'DirectSubcontractor': 'subcontractor'}.get(type(instance).__name__)


def label_of(instance):
	code = getattr(instance, 'vendor_code', None) or getattr(instance, 'code', '')
	return f'{code} – {instance.name}'[:300]


def show(field, value):
	if value is None or value == '':
		return '—'
	if field.choices:
		return str(dict(field.flatchoices).get(value, value))
	if isinstance(value, bool):
		return 'Yes' if value else 'No'
	if isinstance(value, Decimal):
		return format(value.normalize(), 'f')
	if isinstance(value, datetime.date):
		return value.strftime('%d %b %Y')
	return str(value)[:500]


def differences(old, new):
	changes = []
	for field in new._meta.concrete_fields:
		if field.name in SKIP_FIELDS:
			continue
		before, after = getattr(old, field.attname), getattr(new, field.attname)
		if before != after and not (before in (None, '') and after in (None, '')):
			changes.append({'field': str(field.verbose_name).capitalize(), 'old': show(field, before), 'new': show(field, after)})
	return changes


def record(kind, object_id, label, action, changes=None, note='', user=None):
	return AuditEntry.objects.create(
		kind=kind, object_id=object_id, object_label=label, action=action, changes=changes or [], note=note[:300],
		user=user if user is not None else current_user(),
	)


def _remember_old(sender, instance, **kwargs):
	instance._audit_old = type(instance).objects.filter(pk=instance.pk).first() if instance.pk else None


def _vendor_saved(sender, instance, created, **kwargs):
	kind = kind_of(instance)
	if created:
		record(kind, instance.pk, label_of(instance), AuditEntry.Action.CREATED)
		return
	old = getattr(instance, '_audit_old', None)
	if old is None:
		return
	if old.archived_at is None and instance.archived_at is not None:
		record(kind, instance.pk, label_of(instance), AuditEntry.Action.DELETED)
	elif old.archived_at is not None and instance.archived_at is None:
		record(kind, instance.pk, label_of(instance), AuditEntry.Action.RESTORED)
	changes = differences(old, instance)
	if changes:
		record(kind, instance.pk, label_of(instance), AuditEntry.Action.UPDATED, changes)


def _document_saved(sender, instance, created, **kwargs):
	if created:
		record(instance.kind, instance.vendor_id, _vendor_label(instance), AuditEntry.Action.DOCUMENT_ADDED,
		       note=_document_note(instance), user=instance.uploaded_by)


def _document_deleted(sender, instance, **kwargs):
	record(instance.kind, instance.vendor_id, _vendor_label(instance), AuditEntry.Action.DOCUMENT_REMOVED, note=_document_note(instance))


def _document_note(document):
	note = document.get_doc_type_display()
	if document.number:
		note += f' {document.number}'
	if document.expires_on:
		note += f', valid until {document.expires_on:%d %b %Y}'
	return note


def _vendor_label(document):
	from subcontractors.models import DirectSubcontractor
	from suppliers.models import Supplier

	model = Supplier if document.kind == 'supplier' else DirectSubcontractor
	vendor = model.objects.filter(pk=document.vendor_id).first()
	return label_of(vendor) if vendor else f'{document.kind} {document.vendor_id}'


def connect():
	from documents.models import VendorDocument
	from subcontractors.models import DirectSubcontractor
	from suppliers.models import Supplier

	for model in (Supplier, DirectSubcontractor):
		pre_save.connect(_remember_old, sender=model, dispatch_uid=f'audit_old_{model.__name__}')
		post_save.connect(_vendor_saved, sender=model, dispatch_uid=f'audit_saved_{model.__name__}')
	post_save.connect(_document_saved, sender=VendorDocument, dispatch_uid='audit_document_saved')
	post_delete.connect(_document_deleted, sender=VendorDocument, dispatch_uid='audit_document_deleted')
