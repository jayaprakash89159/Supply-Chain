from django import forms
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.apps import apps
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from scportal.search import apply_search, matched_fields
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
	return render(request, 'accounts/dashboard.html', {
		'supplier_count': apps.get_model('suppliers', 'Supplier').objects.filter(archived_at__isnull=True).count(),
		'subcontractor_count': apps.get_model('subcontractors', 'DirectSubcontractor').objects.filter(archived_at__isnull=True).count(),
		'material_count': apps.get_model('materials', 'Material').objects.filter(is_active=True).count(),
		'project_count': apps.get_model('projects', 'Project').objects.count(),
	})


# Fields shown as "Matched on" in search results, in the order they are checked.
MATCH_LABELS = {
	'mobile_number': 'Mobile No.', 'alternate_number': 'Alternate No.', 'email': 'Email',
	'name': 'Name', 'contact_person': 'Contact person', 'gstin': 'GSTIN', 'pan': 'PAN',
	'city': 'City', 'state': 'State', 'pin_code': 'PIN code', 'full_address': 'Address',
	'bank_account_number': 'Bank A/c No.', 'ifsc': 'IFSC', 'referred_by': 'Referred by', 'remarks': 'Remarks',
}
SEARCH_RESULT_LIMIT = 50


@login_required
def global_search(request):
	"""Search suppliers and Labour & Composite subcontractors together from the dashboard."""
	search = request.GET.get('q', '').strip()
	suppliers = subcontractors = []
	supplier_total = subcontractor_total = 0
	if search:
		supplier_qs = apply_search(
			apps.get_model('suppliers', 'Supplier').objects.filter(archived_at__isnull=True),
			search, SUP_SEARCH_FIELDS, SUP_PHONE_FIELDS,
		)
		subcontractor_qs = apply_search(
			apps.get_model('subcontractors', 'DirectSubcontractor').objects.filter(archived_at__isnull=True),
			search, SUB_SEARCH_FIELDS, SUB_PHONE_FIELDS,
		)
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
