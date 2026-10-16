from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from scportal.excel import READ_ERRORS
from scportal.gstin import GstinFormMixin, inspect as inspect_gstin
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


@login_required
def subcontractor_list(request):
	records = _active().prefetch_related('trade_links__trade')
	search = request.GET.get('q', '').strip()
	records = apply_search(records, search, SEARCH_FIELDS, PHONE_FIELDS)
	for field in ('status', 'service_type', 'city'):
		value = request.GET.get(field, '').strip()
		if value:
			records = records.filter(**{field: value})
	trade = request.GET.get('trade', '').strip()
	if trade:
		records = records.filter(trade_links__trade__name=trade).distinct()
	page = Paginator(records, 25).get_page(request.GET.get('page'))
	active = _active()
	return render(request, 'subcontractors/list.html', {
		'page': page,
		'search': search,
		'statuses': DirectSubcontractor.Status.choices,
		'service_types': active.exclude(service_type='').values_list('service_type', flat=True).distinct().order_by('service_type'),
		'cities': active.exclude(city='').values_list('city', flat=True).distinct().order_by('city'),
		'trades': active.filter(trade_links__isnull=False).values_list('trade_links__trade__name', flat=True).distinct().order_by('trade_links__trade__name'),
	})


@login_required
def subcontractor_detail(request, pk):
	subcontractor = get_object_or_404(
		_active().prefetch_related('trade_links__trade', 'project_links__project', 'supplier_links__supplier'), pk=pk,
	)
	return render(request, 'subcontractors/detail.html', {'subcontractor': subcontractor, 'gstin_info': inspect_gstin(subcontractor.gstin)})


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
	if request.method == 'POST' and form.is_valid():
		try:
			created_count = import_workbook(form.cleaned_data['file'])
		except READ_ERRORS as exc:
			form.add_error('file', f'Could not read this Excel workbook: {exc}')
		except ValidationError as exc:
			form.add_error('file', exc.messages)
		else:
			messages.success(request, f'Imported {created_count} subcontractor(s).')
			return redirect('subcontractors:list')
	return render(request, 'subcontractors/upload.html', {'form': form})


@admin_required
def subcontractor_template(request):
	return template_download()
