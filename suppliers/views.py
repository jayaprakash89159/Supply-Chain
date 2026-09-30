from zipfile import BadZipFile

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from openpyxl.utils.exceptions import InvalidFileException

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


@login_required
def supplier_list(request):
	suppliers = Supplier.objects.filter(archived_at__isnull=True).prefetch_related(
		'material_links__material__category', 'trade_links__trade'
	)
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

	page = Paginator(suppliers, 25).get_page(request.GET.get('page'))
	return render(request, 'suppliers/list.html', {
		'page': page,
		'search': search,
		'statuses': Supplier.Status.choices,
		'selected_status': request.GET.get('status', ''),
		'supplier_types': Supplier.objects.filter(archived_at__isnull=True).exclude(supplier_type='').values_list('supplier_type', flat=True).distinct().order_by('supplier_type'),
		'cities': Supplier.objects.filter(archived_at__isnull=True).exclude(city='').values_list('city', flat=True).distinct().order_by('city'),
	})


@login_required
def supplier_detail(request, pk):
	supplier = get_object_or_404(
		Supplier.objects.filter(archived_at__isnull=True).prefetch_related(
			'material_links__material__category', 'trade_links__trade', 'brand_links__brand', 'material_category_links__category',
			'project_links__project', 'direct_subcontractor_links__subcontractor',
		),
		pk=pk,
	)
	return render(request, 'suppliers/detail.html', {'supplier': supplier})


def _supplier_admin():
	return admin.site._registry[Supplier]


@user_passes_test(lambda user: user.is_superuser)
def supplier_upload(request):
	form = SupplierUploadForm(request.POST or None, request.FILES or None)
	if request.method == 'POST' and form.is_valid():
		try:
			created_count = _supplier_admin()._import_workbook(form.cleaned_data['file'])
		except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
			form.add_error('file', f'Could not read this Excel workbook: {exc}')
		except ValidationError as exc:
			form.add_error('file', exc.messages)
		else:
			messages.success(request, f'Imported {created_count} supplier(s).')
			return redirect('suppliers:list')
	return render(request, 'suppliers/upload.html', {'form': form})


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


class SupplierForm(forms.ModelForm):
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
	supplier = get_object_or_404(Supplier, pk=pk, archived_at__isnull=True)
	form = SupplierForm(request.POST or None, instance=supplier)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, f'Supplier {supplier.vendor_code} was updated.')
		return redirect('suppliers:detail', supplier.pk)
	return render(request, 'suppliers/form.html', {'form': form, 'supplier': supplier})
