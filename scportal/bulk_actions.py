"""Admin-only bulk actions on directory records (delete, set status), shared by suppliers and subcontractors."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme


def delete_selected(request, queryset, label, list_url):
	"""Move the records whose ids were posted as ``ids`` to the recycle bin, then go back to the page the admin came from.

	Records stay in the bin (hidden everywhere else) until an admin restores them or deletes them permanently.
	"""
	ids = [value for value in request.POST.getlist('ids') if value.isdigit()]
	records = list(queryset.filter(pk__in=ids, archived_at__isnull=True))
	if not records:
		messages.error(request, f'Select at least one {label} to delete.')
	else:
		now = timezone.now()
		with transaction.atomic():
			for record in records:
				record.archived_at, record.archived_by = now, request.user
				record.save(update_fields=['archived_at', 'archived_by', 'updated_at'])
		names = [str(record) for record in records]
		shown = ', '.join(names[:5]) + (f' and {len(names) - 5} more' if len(names) > 5 else '')
		messages.success(
			request,
			f'Moved {len(names)} {label}{"" if len(names) == 1 else "s"} to the recycle bin: {shown}. '
			'An administrator can restore them from Recycle bin.',
		)

	next_url = request.POST.get('next', '')
	if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
		return redirect(next_url)
	return redirect(list_url)


def set_status_selected(request, queryset, label, list_url, statuses):
	"""Set the posted ``status`` on every record whose id was posted as ``ids``."""
	ids = [value for value in request.POST.getlist('ids') if value.isdigit()]
	status = request.POST.get('status', '')
	labels = dict(statuses)
	records = queryset.filter(pk__in=ids)
	if status not in labels:
		messages.error(request, 'Choose the new status first, then click “Set status”.')
	elif not records.exists():
		messages.error(request, f'Select at least one {label} to change.')
	else:
		from audit.models import AuditEntry
		from audit.recorder import kind_of, label_of, record

		changed = [r for r in records if r.status != status]
		count = records.update(status=status, updated_at=timezone.now())
		for item in changed:
			old = dict(statuses).get(item.status, item.status)
			record(kind_of(item), item.pk, label_of(item), AuditEntry.Action.STATUS,
			       [{'field': 'Status', 'old': old, 'new': labels[status]}], note='Bulk status change', user=request.user)
		messages.success(request, f'Status set to {labels[status]} for {count} {label}{"" if count == 1 else "s"}.')

	next_url = request.POST.get('next', '')
	if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
		return redirect(next_url)
	return redirect(list_url)
