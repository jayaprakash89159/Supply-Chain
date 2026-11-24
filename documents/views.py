from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import EXPIRING_TYPES, REQUIRED_TYPES, WARNING_DAYS, VendorDocument, current_documents, expiring_queryset

MAX_MB = 10
FILE_TYPES = ('.pdf', '.jpg', '.jpeg', '.png')
MODELS = {VendorDocument.Kind.SUPPLIER: Supplier, VendorDocument.Kind.SUBCONTRACTOR: DirectSubcontractor}
DETAIL_URLS = {VendorDocument.Kind.SUPPLIER: 'suppliers:detail', VendorDocument.Kind.SUBCONTRACTOR: 'subcontractors:detail'}
admin_required = user_passes_test(lambda user: user.is_superuser)


class DocumentForm(forms.ModelForm):
	class Meta:
		model = VendorDocument
		fields = ('doc_type', 'number', 'issued_on', 'expires_on', 'file', 'notes')
		widgets = {
			'issued_on': forms.DateInput(attrs={'type': 'date'}),
			'expires_on': forms.DateInput(attrs={'type': 'date'}),
		}
		help_texts = {'file': 'PDF or photo (JPG/PNG), up to 10 MB.', 'expires_on': 'Leave empty if the document never expires.'}

	def clean_file(self):
		file = self.cleaned_data.get('file')
		if file and hasattr(file, 'size'):
			if file.size > MAX_MB * 1024 * 1024:
				raise forms.ValidationError(f'This file is {file.size / 1024 / 1024:.1f} MB; the limit is {MAX_MB} MB.')
			if not file.name.lower().endswith(FILE_TYPES):
				raise forms.ValidationError('Upload a PDF or a photo (JPG or PNG).')
		return file

	def clean(self):
		data = super().clean()
		doc_type, issued, expires = data.get('doc_type'), data.get('issued_on'), data.get('expires_on')
		if doc_type in EXPIRING_TYPES and not expires:
			self.add_error('expires_on', f'A {VendorDocument.DocType(doc_type).label.lower()} has a validity period: enter the “Valid until” date.')
		if issued and expires and expires < issued:
			self.add_error('expires_on', '“Valid until” cannot be before “Issued on”.')
		return data


def vendor_or_404(kind, vendor_id):
	model = MODELS.get(kind)
	if model is None:
		raise Http404
	return get_object_or_404(model, pk=vendor_id, archived_at__isnull=True)


def profile_context(kind, vendor, form=None):
	"""Context for the Documents section of a supplier or subcontractor profile."""
	documents = list(VendorDocument.objects.filter(kind=kind, vendor_id=vendor.pk).select_related('uploaded_by'))
	current = current_documents(documents)
	current_ids = {document.pk for document in current.values()}
	required = REQUIRED_TYPES.get(kind, [])
	return {
		'documents': [document for document in documents if document.pk in current_ids],
		'older_documents': [document for document in documents if document.pk not in current_ids],
		'missing_documents': [VendorDocument.DocType(doc_type).label for doc_type in required if doc_type not in current],
		'document_form': form or DocumentForm(),
		'document_kind': kind,
	}


@require_POST
@admin_required
def upload(request, kind, vendor_id):
	vendor = vendor_or_404(kind, vendor_id)
	form = DocumentForm(request.POST, request.FILES)
	if form.is_valid():
		document = form.save(commit=False)
		document.kind, document.vendor_id, document.uploaded_by = kind, vendor.pk, request.user
		document.save()
		messages.success(request, f'{document.get_doc_type_display()} uploaded for {vendor.name}.')
		return redirect(f'{reverse(DETAIL_URLS[kind], args=[vendor.pk])}#documents')
	problems = '; '.join(f'{form.fields[field].label if field in form.fields else "Document"}: {" ".join(errors)}' for field, errors in form.errors.items())
	messages.error(request, f'The document was not uploaded. {problems}')
	return redirect(f'{reverse(DETAIL_URLS[kind], args=[vendor.pk])}#documents')


@login_required
def download(request, pk):
	document = get_object_or_404(VendorDocument, pk=pk)
	vendor_or_404(document.kind, document.vendor_id)
	return FileResponse(document.file.open('rb'), as_attachment=False, filename=document.file_name)


@require_POST
@admin_required
def delete(request, pk):
	document = get_object_or_404(VendorDocument, pk=pk)
	label = document.get_doc_type_display()
	document.file.delete(save=False)
	document.delete()
	messages.success(request, f'{label} deleted.')
	return redirect(f'{reverse(DETAIL_URLS[document.kind], args=[document.vendor_id])}#documents')


def attach_vendors(documents):
	"""Give each document .vendor (skipping vendors that were deleted)."""
	documents = list(documents)
	vendors = {}
	for kind, model in MODELS.items():
		ids = [document.vendor_id for document in documents if document.kind == kind]
		vendors[kind] = model.objects.filter(pk__in=ids, archived_at__isnull=True).in_bulk()
	result = []
	for document in documents:
		vendor = vendors[document.kind].get(document.vendor_id)
		if vendor is not None:
			document.vendor = vendor
			document.detail_url = reverse(DETAIL_URLS[document.kind], args=[vendor.pk])
			result.append(document)
	return result


def alert_counts():
	"""(expired, expiring within WARNING_DAYS) among current documents of active vendors."""
	documents = attach_vendors(expiring_queryset(WARNING_DAYS))
	expired = sum(1 for document in documents if document.status == 'expired')
	return expired, len(documents) - expired


WINDOWS = [('30', 'Expired or expiring in 30 days'), ('60', '… in 60 days'), ('90', '… in 90 days'), ('expired', 'Expired only')]


@login_required
def expiring(request):
	window = request.GET.get('within', '30')
	if window not in dict(WINDOWS):
		window = '30'
	documents = expiring_queryset(0 if window == 'expired' else int(window)).select_related('uploaded_by')
	kind = request.GET.get('kind', '')
	if kind in MODELS:
		documents = documents.filter(kind=kind)
	doc_type = request.GET.get('type', '')
	if doc_type in VendorDocument.DocType.values:
		documents = documents.filter(doc_type=doc_type)
	documents = attach_vendors(documents)
	if window == 'expired':
		documents = [document for document in documents if document.status == 'expired']
	return render(request, 'documents/expiring.html', {
		'documents': documents, 'windows': WINDOWS, 'window': window, 'kinds': VendorDocument.Kind.choices,
		'doc_types': VendorDocument.DocType.choices, 'warning_days': WARNING_DAYS,
	})
