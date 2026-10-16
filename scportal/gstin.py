"""Offline GSTIN checks: format, check digit, and the state and PAN encoded in the number.

The official GST portal (services.gst.gov.in) sits behind bot protection and a captcha, so
taxpayer details (legal name, status, address) are checked there by the user; see
GST_PORTAL_SEARCH_URL. Everything here works without contacting the portal.
"""
import re

from django.core.exceptions import ValidationError

GST_PORTAL_SEARCH_URL = 'https://services.gst.gov.in/services/searchtp'

GSTIN_PATTERN = re.compile(r'^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')
CHECK_CHARACTERS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'

STATE_CODES = {
	'01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab', '04': 'Chandigarh',
	'05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi', '08': 'Rajasthan', '09': 'Uttar Pradesh',
	'10': 'Bihar', '11': 'Sikkim', '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur',
	'15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya', '18': 'Assam', '19': 'West Bengal',
	'20': 'Jharkhand', '21': 'Odisha', '22': 'Chhattisgarh', '23': 'Madhya Pradesh', '24': 'Gujarat',
	'25': 'Daman and Diu', '26': 'Dadra and Nagar Haveli and Daman and Diu', '27': 'Maharashtra',
	'28': 'Andhra Pradesh (before 2014)', '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep',
	'32': 'Kerala', '33': 'Tamil Nadu', '34': 'Puducherry', '35': 'Andaman and Nicobar Islands',
	'36': 'Telangana', '37': 'Andhra Pradesh', '38': 'Ladakh', '97': 'Other Territory',
	'99': 'Centre Jurisdiction',
}


def normalise(value):
	return re.sub(r'\s', '', str(value or '')).upper()


def check_character(gstin):
	total = 0
	for index, character in enumerate(gstin[:14]):
		product = CHECK_CHARACTERS.index(character) * (1 if index % 2 == 0 else 2)
		total += product // 36 + product % 36
	return CHECK_CHARACTERS[(36 - total % 36) % 36]


def inspect(value):
	"""Describe a GSTIN. 'status' is 'empty', 'invalid_format', 'check_mismatch' or 'ok'."""
	gstin = normalise(value)
	if not gstin:
		return {'status': 'empty', 'gstin': ''}
	if not GSTIN_PATTERN.match(gstin):
		return {'status': 'invalid_format', 'gstin': gstin, 'message': 'Not a valid GSTIN format (15 characters: 2-digit state code, PAN, entity number, Z, check character).'}
	info = {
		'gstin': gstin,
		'state_code': gstin[:2],
		'state': STATE_CODES.get(gstin[:2], ''),
		'pan': gstin[2:12],
		'expected_check': check_character(gstin),
	}
	if info['expected_check'] != gstin[14]:
		info.update(status='check_mismatch', message=f'Check character should be {info["expected_check"]!r}, not {gstin[14]!r} - possible typo.')
	elif not info['state']:
		info.update(status='invalid_format', message=f'Unknown GST state code {gstin[:2]}.')
	else:
		info.update(status='ok', message='Format and check character are valid.')
	return info


class GstinFormMixin:
	"""For ModelForms with gstin/pan fields: tidy both and reject a malformed GSTIN.

	A check-character mismatch is allowed (shown as a warning) because the GST portal is the final word.
	"""

	def clean_gstin(self):
		info = inspect(self.cleaned_data.get('gstin'))
		if info['status'] == 'invalid_format':
			raise ValidationError(info['message'])
		return info['gstin']

	def clean_pan(self):
		return normalise(self.cleaned_data.get('pan'))
