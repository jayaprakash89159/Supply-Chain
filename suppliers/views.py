from zipfile import BadZipFile

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from openpyxl.utils.exceptions import InvalidFileException

from scportal.bulk_actions import delete_selected, set_status_selected
from scportal.import_checks import read_error, upload_summary
from scportal.gstin import GstinFormMixin, inspect as inspect_gstin
from scportal import vendor_tools
from scportal.search import apply_search

from .admin import FIELD_HEADERS, UPLOAD_COLUMNS, SupplierUploadForm
from .links import LINK_FIELDS, current_names, join_names, save_links, split_names
from .models import Supplier

SEARCH_FIELDS = (
	'vendor_code', 'name', 'supplier_type', 'contact_person', 'mobile_number', 'alternate_number', 'email',
	'full_address', 'city', 'state', 'pin_code', 'gstin', 'pan', 'udyam_registration_number',
	'bank_account_number', 'ifsc', 'referred_by', 'remarks', 'material_links__material__name',
	'material_category_links__category__name', 'trade_links__trade__name', 'brand_links__brand__name',
	'project_links__project__name',
)
PHONE_FIELDS = ('mobile_number', 'alternate_number')


KEY_FIELDS = [('supplier_type', 'Supplier type'), *vendor_tools.KEY_FIELDS]
EXPORT_PREFETCH = (
	'trade_links__trade', 'material_category_links__category', 'material_links__material', 'brand_links__brand',
	'project_links__project',
)


def _active():
	return Supplier.objects.filter(archived_at__isnull=True)


def _filtered(request):
	"""Suppliers matching the list page's search and filters (shared by the list and the Excel export)."""
	suppliers = _active()
	search = request.GET.get('q', '').strip()
	suppliers = apply_search(suppliers, search, SEARCH_FIELDS, PHONE_FIELDS)
	for field in ('status', 'supplier_type', 'city', 'state', 'msme_category'):
		value = request.GET.get(field, '').strip()
		if value:
			suppliers = suppliers.filter(**{field: value})
	rating = request.GET.get('min_rating', '').strip()
	if rating:
		try:
			suppliers = suppliers.filter(overall_rating__gte=float(rating))
		except ValueError:
			pass
	missing = request.GET.get('missing', '').strip()
	if missing == 'any' or missing in dict(KEY_FIELDS):
		suppliers = suppliers.filter(vendor_tools.missing_filter(KEY_FIELDS, missing))
	if request.GET.get('duplicates') == '1':
		suppliers = suppliers.filter(pk__in=vendor_tools.duplicate_ids(_active()))
	return suppliers, search


@login_required
def supplier_list(request):
	suppliers, search = _filtered(request)
	suppliers = suppliers.prefetch_related('material_links__material__category', 'trade_links__trade')
	page = Paginator(suppliers, 25).get_page(request.GET.get('page'))
	vendor_tools.annotate_completeness(page.object_list, KEY_FIELDS)
	query = request.GET.copy()
	query.pop('page', None)
	return render(request, 'suppliers/list.html', {
		'page': page,
		'search': search,
		'query_string': query.urlencode(),
		'statuses': Supplier.Status.choices,
		'selected_status': request.GET.get('status', ''),
		'missing_choices': KEY_FIELDS,
		'supplier_types': _active().exclude(supplier_type='').values_list('supplier_type', flat=True).distinct().order_by('supplier_type'),
		'cities': _active().exclude(city='').values_list('city', flat=True).distinct().order_by('city'),
	})


@login_required
def supplier_export(request):
	suppliers, _ = _filtered(request)

	def row(supplier):
		values = {heading: getattr(supplier, field) for heading, field in FIELD_HEADERS.items()}
		values['Status'] = supplier.get_status_display()
		values['GSTIN Check'] = vendor_tools.check_value(supplier.gstin_check)
		values['IFSC Check'] = vendor_tools.check_value(supplier.ifsc_check)
		values['Trade'] = join_names(link.trade.name for link in supplier.trade_links.all())
		values['Material Category'] = join_names(link.category.name for link in supplier.material_category_links.all())
		values['Key Materials Supplied'] = join_names(link.material.name for link in supplier.material_links.all())
		values['Brands Dealt'] = join_names(link.brand.name for link in supplier.brand_links.all())
		values['Project(s) Worked On'] = join_names(link.project.name for link in supplier.project_links.all())
		return values

	return vendor_tools.export_response(
		suppliers.prefetch_related(*EXPORT_PREFETCH), UPLOAD_COLUMNS, row, 'suppliers', 'Suppliers',
	)


@login_required
def supplier_duplicates(request):
	return render(request, 'includes/duplicates.html', {
		'groups': vendor_tools.duplicate_groups(_active()),
		'kind': 'Suppliers', 'list_url': 'suppliers:list', 'detail_url': 'suppliers:detail', 'code_field': 'vendor_code',
	})


@login_required
def supplier_detail(request, pk):
	supplier = get_object_or_404(
		_active().prefetch_related(
			'material_links__material__category', 'trade_links__trade', 'brand_links__brand', 'material_category_links__category',
			'project_links__project', 'direct_subcontractor_links__subcontractor',
		),
		pk=pk,
	)
	percent, missing = vendor_tools.completeness(supplier, KEY_FIELDS)
	return render(request, 'suppliers/detail.html', {
		'supplier': supplier, 'gstin_info': inspect_gstin(supplier.gstin),
		'profile_percent': percent, 'profile_missing': missing,
		'duplicates': vendor_tools.duplicates_of(supplier, _active()),
	})


@login_required
def supplier_vcard(request, pk):
	supplier = get_object_or_404(_active(), pk=pk)
	return vendor_tools.vcard_response(supplier, supplier.vendor_code, 'Supplier')


def _supplier_admin():
	return admin.site._registry[Supplier]


@user_passes_test(lambda user: user.is_superuser)
def supplier_upload(request):
	form = SupplierUploadForm(request.POST or None, request.FILES or None)
	problems = []
	if request.method == 'POST' and form.is_valid():
		try:
			created_count = _supplier_admin()._import_workbook(form.cleaned_data['file'])
		except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
			form.add_error('file', read_error(exc).messages)
		except ValidationError as exc:
			problems = getattr(exc, 'problems', [])
			form.add_error('file', upload_summary(problems) if problems else exc.messages)
		else:
			messages.success(request, f'Imported {created_count} supplier(s).')
			return redirect('suppliers:list')
	return render(request, 'suppliers/upload.html', {'form': form, 'problems': problems})


@user_passes_test(lambda user: user.is_superuser)
def supplier_template(request):
	return _supplier_admin().template_download(request)


LINK_HEADERS = {
	'Trade': 'trades',
	'Material Category': 'material_categories',
	'Key Materials Supplied': 'materials',
	'Brands Dealt': 'brands',
	'Project(s) Worked On': 'projects',
}
FORM_HEADERS = {**FIELD_HEADERS, **LINK_HEADERS}


class SupplierForm(GstinFormMixin, forms.ModelForm):
	"""Supplier fields in the same order and with the same headings as the Excel upload."""

	trades = forms.CharField(required=False)
	material_categories = forms.CharField(required=False)
	materials = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))
	brands = forms.CharField(required=False)
	projects = forms.CharField(required=False)

	field_order = [FORM_HEADERS[heading] for heading in UPLOAD_COLUMNS if heading in FORM_HEADERS]

	class Meta:
		model = Supplier
		exclude = ('archived_at',)
		labels = {field: heading for heading, field in FIELD_HEADERS.items()}
		widgets = {
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
		supplier = super().save()
		save_links(supplier, {field: split_names(self.cleaned_data.get(field)) for field in LINK_FIELDS})
		return supplier


@user_passes_test(lambda user: user.is_superuser)
def supplier_create(request):
	form = SupplierForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		supplier = form.save()
		messages.success(request, f'Supplier {supplier.vendor_code} was created.')
		return redirect('suppliers:detail', supplier.pk)
	return render(request, 'suppliers/form.html', {'form': form})


@user_passes_test(lambda user: user.is_superuser)
def supplier_edit(request, pk):
	supplier = get_object_or_404(_active(), pk=pk)
	form = SupplierForm(request.POST or None, instance=supplier)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, f'Supplier {supplier.vendor_code} was updated.')
		return redirect('suppliers:detail', supplier.pk)
	return render(request, 'suppliers/form.html', {'form': form, 'supplier': supplier})


@require_POST
@user_passes_test(lambda user: user.is_superuser)
def supplier_delete(request):
	"""Permanently delete one or more suppliers (ticked on the list, or from a profile page)."""
	return delete_selected(request, Supplier.objects.all(), 'supplier', 'suppliers:list')


@require_POST
@user_passes_test(lambda user: user.is_superuser)
def supplier_set_status(request):
	"""Set the status of several suppliers at once (ticked on the list)."""
	return set_status_selected(request, Supplier.objects.all(), 'supplier', 'suppliers:list', Supplier.Status.choices)
