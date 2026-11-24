from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .models import AccountSettings


class ForcePasswordChangeMiddleware:
	"""After an administrator resets a password, the user must choose their own before using the portal."""

	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		user = getattr(request, 'user', None)
		if user is not None and user.is_authenticated:
			allowed = (reverse('password_change'), reverse('logout'), '/static/', '/health/')
			if not request.path.startswith(allowed) and AccountSettings.objects.filter(user=user, must_change_password=True).exists():
				messages.warning(request, 'An administrator reset your password. Please choose your own password to continue.')
				return redirect('password_change')
		return self.get_response(request)
