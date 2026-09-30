"""Directory search that also matches phone numbers typed with spaces, dashes or +91."""
import re

from django.db.models import Q, Value
from django.db.models.functions import Replace


def _digits_only(field_name):
	expression = Replace(field_name, Value(' '), Value(''))
	for character in ('-', '+', '(', ')', '.', '/'):
		expression = Replace(expression, Value(character), Value(''))
	return expression


def phone_digits(search):
	"""Digits to look for when the search looks like a phone number, else ''."""
	digits = re.sub(r'\D', '', search)
	if len(digits) < 4 or len(digits) < len(re.sub(r'[\s()+\-./]', '', search)):
		return ''
	if len(digits) > 10 and digits.startswith(('91', '0')):
		digits = digits[-10:]
	return digits


def apply_search(queryset, search, text_fields, phone_fields=()):
	"""Filter to records where any field contains the search text (phone fields ignore punctuation)."""
	search = search.strip()
	if not search:
		return queryset
	condition = Q()
	for field in text_fields:
		condition |= Q(**{f'{field}__icontains': search})
	digits = phone_digits(search)
	if digits:
		annotations = {f'_digits_{field}': _digits_only(field) for field in phone_fields}
		queryset = queryset.annotate(**annotations)
		for name in annotations:
			condition |= Q(**{f'{name}__contains': digits})
	return queryset.filter(condition).distinct()


def matched_fields(record, search, labels):
	"""Names of the fields whose value contains the search, for showing why a record matched."""
	needle = search.strip().casefold()
	digits = phone_digits(search)
	matches = []
	for field, label in labels.items():
		value = str(getattr(record, field, '') or '')
		if needle and needle in value.casefold():
			matches.append(label)
		elif digits and digits in re.sub(r'\D', '', value):
			matches.append(label)
	return matches
