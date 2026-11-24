from django import forms
from django.contrib import messages
import secrets
import string

from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from scportal import vendor_tools
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from scportal.search import apply_search, matched_fields

from .models import AccountSettings
from subcontractors.views import PHONE_FIELDS as SUB_PHONE_FIELDS, SEARCH_FIELDS as SUB_SEARCH_FIELDS
from suppliers.views import PHONE_FIELDS as SUP_PHONE_FIELDS, SEARCH_FIELDS as SUP_SEARCH_FIELDS


def login_view(request):
	if request.user.is_authenticated:
		return redirect('dashboard')

	form = AuthenticationForm(request, data=request.POST or None)
	if request.method == 'POST' and form.is_valid():
		login(request, form.get_user())
		destination = request.POST.get('next') or request.GET.get('next', '')
		if not url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
			destination = 'dashboard'
		return redirect(destination)

	return render(request, 'accounts/login.html', {'form': form})


@require_POST
@login_required
def logout_view(request):
	logout(request)
	return redirect('login')


@login_required
def dashboard(request):
	from documents.views import alert_counts

	expired_documents, expiring_documents = alert_counts()
	return render(request, 'accounts/dashboard.html', {
		'supplier_count': apps.get_model('suppliers', 'Supplier').objects.filter(archived_at__isnull=True).count(),
		'subcontractor_count': apps.get_model('subcontractors', 'DirectSubcontractor').objects.filter(archived_at__isnull=True).count(),
		'material_count': apps.get_model('materials', 'Material').objects.filter(is_active=True).count(),
		'project_count': apps.get_model('projects', 'Project').objects.count(),
		'documents_expired': expired_documents,
		'documents_expiring': expiring_documents,
	})


# Fields shown as "Matched on" in search results, in the order they are checked.
MATCH_LABELS = {
	'mobile_number': 'Mobile No.', 'alternate_number': 'Alternate No.', 'email': 'Email',
	'name': 'Name', 'contact_person': 'Contact person', 'gstin': 'GSTIN', 'pan': 'PAN',
	'city': 'City', 'state': 'State', 'pin_code': 'PIN code', 'full_address': 'Address',
	'bank_account_number': 'Bank A/c No.', 'ifsc': 'IFSC', 'referred_by': 'Referred by', 'remarks': 'Remarks',
}
SEARCH_RESULT_LIMIT = 50


def _search_querysets(search):
	supplier_qs = apply_search(
		apps.get_model('suppliers', 'Supplier').objects.filter(archived_at__isnull=True),
		search, SUP_SEARCH_FIELDS, SUP_PHONE_FIELDS,
	)
	subcontractor_qs = apply_search(
		apps.get_model('subcontractors', 'DirectSubcontractor').objects.filter(archived_at__isnull=True),
		search, SUB_SEARCH_FIELDS, SUB_PHONE_FIELDS,
	)
	return supplier_qs, subcontractor_qs


@login_required
def search_export(request):
	"""Every search result (not just the first page) as Excel: a Suppliers sheet and a Labour & Composite sheet."""
	from subcontractors import views as subcontractor_views
	from subcontractors.importer import UPLOAD_COLUMNS as SUB_COLUMNS
	from suppliers import views as supplier_views
	from suppliers.admin import UPLOAD_COLUMNS as SUP_COLUMNS

	search = request.GET.get('q', '').strip()
	if not search:
		return redirect('search')
	supplier_qs, subcontractor_qs = _search_querysets(search)
	return vendor_tools.workbook_response(f'search_{slugify(search)[:40] or "results"}', [
		('Suppliers', SUP_COLUMNS, supplier_qs.prefetch_related(*supplier_views.EXPORT_PREFETCH), supplier_views.export_row),
		('Labour & Composite', SUB_COLUMNS, subcontractor_qs.prefetch_related(*subcontractor_views.EXPORT_PREFETCH), subcontractor_views.export_row),
	])


@login_required
def global_search(request):
	"""Search suppliers and Labour & Composite subcontractors together from the dashboard."""
	search = request.GET.get('q', '').strip()
	suppliers = subcontractors = []
	supplier_total = subcontractor_total = 0
	if search:
		supplier_qs, subcontractor_qs = _search_querysets(search)
		supplier_total, subcontractor_total = supplier_qs.count(), subcontractor_qs.count()
		labels = {**MATCH_LABELS, 'vendor_code': 'Vendor code', 'supplier_type': 'Supplier type'}
		suppliers = [(record, matched_fields(record, search, labels)) for record in supplier_qs[:SEARCH_RESULT_LIMIT]]
		labels = {**MATCH_LABELS, 'code': 'Vendor code', 'service_type': 'Service type', 'scope_of_work': 'Scope of work'}
		subcontractors = [(record, matched_fields(record, search, labels)) for record in subcontractor_qs[:SEARCH_RESULT_LIMIT]]
	return render(request, 'accounts/search.html', {
		'search': search,
		'suppliers': suppliers,
		'subcontractors': subcontractors,
		'supplier_total': supplier_total,
		'subcontractor_total': subcontractor_total,
		'limit': SEARCH_RESULT_LIMIT,
	})


ACCESS_CHOICES = [('read_only', 'Read only'), ('admin', 'Administrator')]


class PortalUserCreationForm(UserCreationForm):
	access = forms.ChoiceField(
		choices=ACCESS_CHOICES,
		initial='read_only',
		help_text='Read only users can search and view records. Administrators can also add, edit and upload data, and manage users.',
	)


def _set_access(user, access):
	user.is_superuser = user.is_staff = access == 'admin'


@user_passes_test(lambda user: user.is_superuser)
def admin_users(request):
	form = PortalUserCreationForm(request.POST or None)
	action = request.POST.get('action')
	if request.method == 'POST' and action == 'create' and form.is_valid():
		user = form.save(commit=False)
		_set_access(user, form.cleaned_data['access'])
		user.save()
		label = dict(ACCESS_CHOICES)[form.cleaned_data['access']].lower()
		messages.success(request, f'User {user.username} was created with {label} access.')
		return redirect('admin_users')

	if request.method == 'POST' and action == 'set_email':
		user = get_object_or_404(User, pk=request.POST.get('user_id'))
		email = request.POST.get('email', '').strip()
		try:
			if email:
				validate_email(email)
		except ValidationError:
			messages.error(request, f'“{email}” is not a valid email address, e.g. name@vishwainfra.in.')
		else:
			user.email = email
			user.save(update_fields=['email'])
			messages.success(request, f'Email for {user.username} {"set to " + email if email else "removed"}. Vendors’ replies to this user’s quote requests go there.')
		return redirect('admin_users')

	if request.method == 'POST' and action in {'set_access', 'deactivate', 'activate'}:
		user = get_object_or_404(User, pk=request.POST.get('user_id'))
		if user.pk == request.user.pk:
			messages.error(request, 'You cannot change your own access or status.')
		elif action == 'set_access':
			access = request.POST.get('access')
			if access not in dict(ACCESS_CHOICES):
				messages.error(request, 'Choose a valid access level.')
			else:
				_set_access(user, access)
				user.save(update_fields=['is_superuser', 'is_staff'])
				messages.success(request, f'{user.username} now has {dict(ACCESS_CHOICES)[access].lower()} access.')
		else:
			user.is_active = action == 'activate'
			user.save(update_fields=['is_active'])
			messages.success(request, f'User {user.username} was {"activated" if user.is_active else "deactivated"}.')
		return redirect('admin_users')

	return render(request, 'accounts/users.html', {
		'form': form,
		'users': User.objects.order_by('username'),
		'access_choices': ACCESS_CHOICES,
	})


# ---------------------------------------------------------------- passwords

def _record_password_change(user, changed_by, must_change):
	settings_row = AccountSettings.for_user(user)
	settings_row.must_change_password = must_change
	settings_row.password_changed_at = timezone.now()
	settings_row.password_changed_by = changed_by
	settings_row.save()


@never_cache
@login_required
def password_change(request):
	"""Any signed-in user changes their own password; the current password is required."""
	form = PasswordChangeForm(request.user, request.POST or None)
	if request.method == 'POST' and form.is_valid():
		user = form.save()
		update_session_auth_hash(request, user)  # stay signed in on this browser; other sessions are signed out
		_record_password_change(user, user, must_change=False)
		messages.success(request, 'Your password was changed.')
		return redirect('dashboard')
	forced = AccountSettings.objects.filter(user=request.user, must_change_password=True).exists()
	return render(request, 'accounts/password_change.html', {'form': form, 'forced': forced})


def temporary_password(length=12):
	"""A random password that is easy to read out: no 0/O, 1/l/I."""
	alphabet = ''.join(ch for ch in string.ascii_letters + string.digits if ch not in '0O1lI')
	while True:
		password = ''.join(secrets.choice(alphabet) for _ in range(length))
		if any(ch.isdigit() for ch in password) and any(ch.isalpha() for ch in password):
			return password


class AdminPasswordResetForm(SetPasswordForm):
	"""An administrator sets a user's password without knowing the old one."""

	generate = forms.BooleanField(required=False, label='Generate a temporary password for me')
	must_change = forms.BooleanField(
		required=False, initial=True, label='Ask the user to choose their own password at next sign-in',
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['new_password1'].required = False
		self.fields['new_password2'].required = False

	def clean(self):
		if self.data.get('generate'):
			password = temporary_password()
			self.cleaned_data['new_password1'] = self.cleaned_data['new_password2'] = password
			self.generated = password
			return self.cleaned_data
		self.generated = None
		if not self.cleaned_data.get('new_password1'):
			self.add_error('new_password1', 'Type a new password, or tick “Generate a temporary password for me”.')
		elif not self.cleaned_data.get('new_password2'):
			self.add_error('new_password2', 'Type the new password again to confirm it.')
		return super().clean()


@never_cache
@user_passes_test(lambda user: user.is_superuser)
def admin_reset_password(request, pk):
	user = get_object_or_404(User, pk=pk)
	if user.pk == request.user.pk:
		messages.info(request, 'To change your own password, enter your current password here.')
		return redirect('password_change')
	form = AdminPasswordResetForm(user, request.POST if request.method == 'POST' else None)
	if request.method == 'POST' and form.is_valid():
		form.save()  # changing the password also signs the user out everywhere
		_record_password_change(user, request.user, must_change=form.cleaned_data['must_change'])
		return render(request, 'accounts/password_reset_done.html', {
			'target': user, 'generated': form.generated, 'must_change': form.cleaned_data['must_change'],
		})
	return render(request, 'accounts/password_reset.html', {'form': form, 'target': user})
