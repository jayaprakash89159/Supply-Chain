from django.conf import settings
from django.db import models


class AccountSettings(models.Model):
	"""Per-user account flags that Django's user model does not have."""

	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_settings')
	must_change_password = models.BooleanField(
		default=False, help_text='Set when an administrator resets the password; cleared when the user picks their own.',
	)
	password_changed_at = models.DateTimeField(null=True, blank=True)
	password_changed_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
	)

	class Meta:
		verbose_name = 'account settings'
		verbose_name_plural = 'account settings'

	def __str__(self):
		return f'Settings for {self.user}'

	@classmethod
	def for_user(cls, user):
		return cls.objects.get_or_create(user=user)[0]
