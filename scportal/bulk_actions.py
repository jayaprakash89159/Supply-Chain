"""Admin-only bulk actions on directory records (delete, set status), shared by suppliers and subcontractors."""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme


def delete_selected(request, queryset, label, list_url, before_delete=None):
	"""Delete the records whose ids were posted as ``ids`` and go back to the page the admin came from.

	``before_delete`` receives the records about to be deleted, for removing protected links first.
	"""
	ids = [value for value in request.POST.getlist('ids') if value.isdigit()]
	records = queryset.filter(pk__in=ids)
	names = [str(record) for record in records]
	if not names:
		messages.error(request, f'Select at least one {label} to delete.')
	else:
		with transaction.atomic():
			if before_delete:
				before_delete(records)
			records.delete()
		shown = ', '.join(names[:5]) + (f' and {len(names) - 5} more' if len(names) > 5 else '')
		messages.success(request, f'Deleted {len(names)} {label}{"" if len(names) == 1 else "s"}: {shown}.')

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
		count = records.update(status=status, updated_at=timezone.now())
		messages.success(request, f'Status set to {labels[status]} for {count} {label}{"" if count == 1 else "s"}.')

	next_url = request.POST.get('next', '')
	if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
		return redirect(next_url)
	return redirect(list_url)
