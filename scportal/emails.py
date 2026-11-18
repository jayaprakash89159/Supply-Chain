"""A text field holding one or more email addresses, written "a@x.com; b@y.com"."""
import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models

SEPARATOR = '; '
# ";" is the documented separator; commas, new lines and spaces also work, since addresses cannot contain them.
SPLIT_PATTERN = re.compile(r'[;,\s]+')
ORDINALS = ('1st', '2nd', '3rd')


def split_emails(value):
	"""Addresses in the order written, without blanks or repeats (repeats compared ignoring case)."""
	emails, seen = [], set()
	for email in SPLIT_PATTERN.split(str(value or '')):
		email = email.strip().strip('<>').rstrip('.')
		if email and email.casefold() not in seen:
			seen.add(email.casefold())
			emails.append(email)
	return emails


def join_emails(value):
	return SEPARATOR.join(split_emails(value))


def validate_email_list(value):
	emails = split_emails(value)
	errors = []
	for position, email in enumerate(emails, start=1):
		try:
			validate_email(email)
		except ValidationError:
			which = f' ({ORDINALS[position - 1] if position <= 3 else f"{position}th"} email)' if len(emails) > 1 else ''
			errors.append(ValidationError(
				f'“{email}”{which} is not a valid email address. Write each address like name@example.com '
				'and separate several with “;”, e.g. accounts@abc.com; sales@abc.com.',
				code='invalid_email',
			))
	if errors:
		raise ValidationError(errors)


class MultipleEmailFormField(forms.CharField):
	def to_python(self, value):
		return join_emails(super().to_python(value))


class MultipleEmailField(models.CharField):
	"""Stores several email addresses separated by "; " and validates each one."""

	default_validators = [validate_email_list]
	description = 'One or more email addresses separated by semicolons'

	def __init__(self, *args, **kwargs):
		kwargs.setdefault('max_length', 500)
		super().__init__(*args, **kwargs)

	def to_python(self, value):
		return join_emails(super().to_python(value))

	def formfield(self, **kwargs):
		kwargs.setdefault('form_class', MultipleEmailFormField)
		kwargs.setdefault('help_text', 'Several addresses? Separate them with “;”, e.g. accounts@abc.com; sales@abc.com')
		return super().formfield(**kwargs)
