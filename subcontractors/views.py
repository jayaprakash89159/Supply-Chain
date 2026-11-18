from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from relationships.models import SupplierDirectSubcontractor
from scportal.bulk_actions import delete_selected, set_status_selected
from scportal.excel import READ_ERRORS
from scportal.import_checks import read_error, upload_summary
from scportal.gstin import GstinFormMixin, inspect as inspect_gstin
from scportal import vendor_tools
from scportal.search import apply_search
from suppliers.links import join_names, split_names

from .importer import (
	FIELD_HEADERS, LINK_FIELDS, LINK_HEADERS, UPLOAD_COLUMNS, current_names, import_workbook, save_links,
	template_download,
)
from .models import DirectSubcontractor

SEARCH_FIELDS = (
	'code', 'name', 'service_type', 'scope_of_work', 'contact_person', 'mobile_number', 'alternate_number',
	'email', 'full_address', 'city', 'state', 'pin_code', 'gstin', 'pan', 'labour_licence_number',
	'esi_registration_number', 'pf_registration_number', 'udyam_registration_number', 'bank_account_number',
	'ifsc', 'referred_by', 'remarks', 'trade_links__trade__name', 'project_links__project__name',
)
PHONE_FIELDS = ('mobile_number', 'alternate_number')
FORM_HEADERS = {**FIELD_HEADERS, **LINK_HEADERS}
admin_required = user_passes_test(lambda user: user.is_superuser)


class SubcontractorForm(GstinFormMixin, forms.ModelForm):
	"""Subcontractor fields in the same order and with the same headings as the Excel upload."""

	trades = forms.CharField(required=False)
	projects = forms.CharField(required=False)

	field_order = [FORM_HEADERS[heading] for heading in UPLOAD_COLUMNS if heading in FORM_HEADERS]

	class Meta:
		model = DirectSubcontractor
		exclude = ('archived_at',)
		labels = {field: heading for heading, field in FIELD_HEADERS.items()}
		widgets = {
			'scope_of_work': forms.Textarea(attrs={'rows': 2}),
			'full_address': forms.Textarea(attrs={'rows': 2}),
			'remarks': forms.Textarea(attrs={'rows': 2}),
			'last_reviewed_on': forms.DateInput(attrs={'type': 'date'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for heading, field in LINK_HEADERS.items():
			self.fields[field].label = heading
			self.fields[field].help_text = 'Separate multiple names with commas.'
		if self.instance.pk:
			for field, names in current_names(self.instance).items():
				self.initial[field] = join_names(names)

	@transaction.atomic
	def save(self, commit=True):
		subcontractor = super().save()
		save_links(subcontractor, {field: split_names(self.cleaned_data.get(field)) for field in LINK_FIELDS})
		return subcontractor


class UploadForm(forms.Form):
	file = forms.FileField(label='Labour & Composite workbook (.xlsx)')


def _active():
	return DirectSubcontractor.objects.filter(archived_at__isnull=True)


KEY_FIELDS = [('service_type', 'Service type'), *vendor_tools.KEY_FIELDS]


def _filtered(request):
	"""Subcontractors matching the list page's search and filters (shared by the list and the Excel export)."""
	records = _active()
	search = request.GET.get('q', '').strip()
	records = apply_search(records, search, SEARCH_FIELDS, PHONE_FIELDS)
	for field in ('status', 'service_type', 'city'):
		value = request.GET.get(field, '').strip()
		if value:
			records = records.filter(**{field: value})
	trade = request.GET.get('trade', '').strip()
	if trade:
		records = records.filter(trade_links__trade__name=trade).distinct()
	missing = request.GET.get('missing', '').strip()
	if missing == 'any' or missing in dict(KEY_FIELDS):
		records = records.filter(vendor_tools.missing_filter(KEY_FIELDS, missing))
	if request.GET.get('duplicates') == '1':
		records = records.filter(pk__in=vendor_tools.duplicate_ids(_active()))
	return records, search


@login_required
def subcontractor_list(request):
	records, search = _filtered(request)
	page = Paginator(records.prefetch_related('trade_links__trade'), 25).get_page(request.GET.get('page'))
	vendor_tools.annotate_completeness(page.object_list, KEY_FIELDS)
	query = request.GET.copy()
	query.pop('page', None)
	active = _active()
	return render(request, 'subcontractors/list.html', {
		'page': page,
		'search': search,
		'query_string': query.urlencode(),
		'statuses': DirectSubcontractor.Status.choices,
		'missing_choices': KEY_FIELDS,
		'service_types': active.exclude(service_type='').values_list('service_type', flat=True).distinct().order_by('service_type'),
		'cities': active.exclude(city='').values_list('city', flat=True).distinct().order_by('city'),
		'trades': active.filter(trade_links__isnull=False).values_list('trade_links__trade__name', flat=True).distinct().order_by('trade_links__trade__name'),
	})


@login_required
def subcontractor_export(request):
	records, _ = _filtered(request)

	def row(sub):
		values = {heading: getattr(sub, field) for heading, field in FIELD_HEADERS.items()}
		values['Status'] = sub.get_status_display()
		values['GSTIN Check'] = vendor_tools.check_value(sub.gstin_check)
		values['IFSC Check'] = vendor_tools.check_value(sub.ifsc_check)
		values['Trade'] = join_names(link.trade.name for link in sub.trade_links.all())
		values['Project(s) Worked On'] = join_names(link.project.name for link in sub.project_links.all())
		return values

	return vendor_tools.export_response(
		records.prefetch_related('trade_links__trade', 'project_links__project'), UPLOAD_COLUMNS, row,
		'labour_composite_subcontractors', 'Labour & Composite',
	)


@login_required
def subcontractor_duplicates(request):
	return render(request, 'includes/duplicates.html', {
		'groups': vendor_tools.duplicate_groups(_active()),
		'kind': 'Labour & Composite subcontractors', 'list_url': 'subcontractors:list',
		'detail_url': 'subcontractors:detail', 'code_field': 'code',
	})


@login_required
def subcontractor_detail(request, pk):
	subcontractor = get_object_or_404(
		_active().prefetch_related('trade_links__trade', 'project_links__project', 'supplier_links__supplier'), pk=pk,
	)
	percent, missing = vendor_tools.completeness(subcontractor, KEY_FIELDS)
	return render(request, 'subcontractors/detail.html', {
		'subcontractor': subcontractor, 'gstin_info': inspect_gstin(subcontractor.gstin),
		'profile_percent': percent, 'profile_missing': missing,
		'duplicates': vendor_tools.duplicates_of(subcontractor, _active()),
	})


@login_required
def subcontractor_vcard(request, pk):
	subcontractor = get_object_or_404(_active(), pk=pk)
	return vendor_tools.vcard_response(subcontractor, subcontractor.code, 'Labour & Composite subcontractor')


@admin_required
def subcontractor_create(request):
	form = SubcontractorForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		subcontractor = form.save()
		messages.success(request, f'Subcontractor {subcontractor.code} was created.')
		return redirect('subcontractors:detail', subcontractor.pk)
	return render(request, 'subcontractors/form.html', {'form': form})


@admin_required
def subcontractor_edit(request, pk):
	subcontractor = get_object_or_404(_active(), pk=pk)
	form = SubcontractorForm(request.POST or None, instance=subcontractor)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, f'Subcontractor {subcontractor.code} was updated.')
		return redirect('subcontractors:detail', subcontractor.pk)
	return render(request, 'subcontractors/form.html', {'form': form, 'subcontractor': subcontractor})


@admin_required
def subcontractor_upload(request):
	form = UploadForm(request.POST or None, request.FILES or None)
	problems = []
	if request.method == 'POST' and form.is_valid():
		try:
			created_count = import_workbook(form.cleaned_data['file'])
		except READ_ERRORS as exc:
			form.add_error('file', read_error(exc).messages)
		except ValidationError as exc:
			problems = getattr(exc, 'problems', [])
			form.add_error('file', upload_summary(problems) if problems else exc.messages)
		else:
			messages.success(request, f'Imported {created_count} subcontractor(s).')
			return redirect('subcontractors:list')
	return render(request, 'subcontractors/upload.html', {'form': form, 'problems': problems})


@admin_required
def subcontractor_template(request):
	return template_download()


@require_POST
@admin_required
def subcontractor_delete(request):
	"""Permanently delete one or more subcontractors (ticked on the list, or from a profile page)."""
	def unlink_suppliers(records):
		# Supplier links protect subcontractors from deletion, so they are removed first.
		SupplierDirectSubcontractor.objects.filter(subcontractor__in=records).delete()

	return delete_selected(
		request, DirectSubcontractor.objects.all(), 'subcontractor', 'subcontractors:list', before_delete=unlink_suppliers,
	)


@require_POST
@admin_required
def subcontractor_set_status(request):
	"""Set the status of several subcontractors at once (ticked on the list)."""
	return set_status_selected(
		request, DirectSubcontractor.objects.all(), 'subcontractor', 'subcontractors:list', DirectSubcontractor.Status.choices,
	)
