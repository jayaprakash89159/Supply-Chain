from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from documents.models import VendorDocument
from relationships.models import SupplierDirectSubcontractor
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import AuditEntry
from .recorder import label_of, record

admin_required = user_passes_test(lambda user: user.is_superuser)
MODELS = {'supplier': Supplier, 'subcontractor': DirectSubcontractor}
DETAIL_URLS = {'supplier': 'suppliers:detail', 'subcontractor': 'subcontractors:detail'}
BIN_DAYS = 30  # shown to admins as the suggested clean-up age; nothing is removed automatically


def history_for(kind, object_id, limit=50):
	return list(AuditEntry.objects.filter(kind=kind, object_id=object_id).select_related('user')[:limit])


@admin_required
def activity(request):
	entries = AuditEntry.objects.select_related('user')
	filters = {
		'action': request.GET.get('action', ''), 'kind': request.GET.get('kind', ''),
		'user': request.GET.get('user', ''), 'q': request.GET.get('q', '').strip(),
	}
	if filters['action'] in AuditEntry.Action.values:
		entries = entries.filter(action=filters['action'])
	if filters['kind'] in AuditEntry.Kind.values:
		entries = entries.filter(kind=filters['kind'])
	if filters['user'].isdigit():
		entries = entries.filter(user_id=int(filters['user']))
	if filters['q']:
		entries = entries.filter(object_label__icontains=filters['q'])
	page = Paginator(entries, 50).get_page(request.GET.get('page'))
	live = {kind: set(model.objects.filter(archived_at__isnull=True).values_list('pk', flat=True)) for kind, model in MODELS.items()}
	for entry in page.object_list:
		entry.url = reverse(DETAIL_URLS[entry.kind], args=[entry.object_id]) if entry.object_id in live[entry.kind] else ''
	query = request.GET.copy()
	query.pop('page', None)
	return render(request, 'audit/activity.html', {
		'page': page, 'filters': filters, 'actions': AuditEntry.Action.choices, 'kinds': AuditEntry.Kind.choices,
		'users': get_user_model().objects.order_by('username'), 'query_string': query.urlencode(),
	})


@admin_required
def recycle_bin(request):
	now = timezone.now()
	rows = []
	for kind, model in MODELS.items():
		for vendor in model.objects.filter(archived_at__isnull=False).select_related('archived_by'):
			rows.append({
				'key': f'{kind}:{vendor.pk}', 'kind': kind, 'kind_label': AuditEntry.Kind(kind).label,
				'vendor': vendor, 'code': vendor.vendor_code if kind == 'supplier' else vendor.code,
				'days': (now - vendor.archived_at).days,
			})
	rows.sort(key=lambda row: row['vendor'].archived_at, reverse=True)
	return render(request, 'audit/recycle_bin.html', {'rows': rows, 'bin_days': BIN_DAYS})


def _selected(request):
	chosen = {'supplier': [], 'subcontractor': []}
	for item in request.POST.getlist('items'):
		kind, _, pk = item.partition(':')
		if kind in chosen and pk.isdigit():
			chosen[kind].append(int(pk))
	return {kind: MODELS[kind].objects.filter(pk__in=ids, archived_at__isnull=False) for kind, ids in chosen.items()}


@require_POST
@admin_required
def restore(request):
	restored = []
	with transaction.atomic():
		for records in _selected(request).values():
			for vendor in records:
				vendor.archived_at = vendor.archived_by = None
				vendor.save(update_fields=['archived_at', 'archived_by', 'updated_at'])
				restored.append(vendor.name)
	if restored:
		messages.success(request, f'Restored {len(restored)}: {", ".join(restored[:5])}{" and more" if len(restored) > 5 else ""}. They are back in their directory.')
	else:
		messages.error(request, 'Tick at least one record to restore.')
	return redirect('audit:recycle-bin')


@require_POST
@admin_required
def purge(request):
	removed = []
	with transaction.atomic():
		for kind, records in _selected(request).items():
			for vendor in records:
				label = label_of(vendor)
				for document in VendorDocument.objects.filter(kind=kind, vendor_id=vendor.pk):
					document.file.delete(save=False)
					document.delete()
				if kind == 'subcontractor':
					# Supplier links protect subcontractors from deletion, so they are removed first.
					SupplierDirectSubcontractor.objects.filter(subcontractor=vendor).delete()
				vendor_pk = vendor.pk
				vendor.delete()
				record(kind, vendor_pk, label, AuditEntry.Action.PURGED, user=request.user)
				removed.append(vendor.name)
	if removed:
		messages.success(request, f'Permanently deleted {len(removed)}: {", ".join(removed[:5])}{" and more" if len(removed) > 5 else ""}. Their history stays in Activity.')
	else:
		messages.error(request, 'Tick at least one record to delete permanently.')
	return redirect('audit:recycle-bin')
