"""Tools shared by the supplier and Labour & Composite directories.

- Profile completeness: which key details a vendor record is missing.
- Duplicate check: vendors sharing a GSTIN, PAN, phone number or bank account number.
- Excel export in the upload-template layout.
- vCard (phone contact) download and click-to-call / WhatsApp links.
"""
import datetime
import re
from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from django.db.models import Q
from django.http import HttpResponse
from django.utils.text import slugify
from openpyxl import Workbook

from .emails import split_emails
from .excel import XLSX_CONTENT_TYPE

# Key details every vendor should have; the directory adds its own type field.
KEY_FIELDS = [
	('contact_person', 'Contact person'),
	('mobile_number', 'Mobile'),
	('email', 'Email'),
	('full_address', 'Address'),
	('city', 'City'),
	('state', 'State'),
	('pin_code', 'PIN code'),
	('gstin', 'GSTIN'),
	('pan', 'PAN'),
	('bank_name', 'Bank name'),
	('bank_account_number', 'Bank A/c no.'),
	('ifsc', 'IFSC'),
]


# ---------------------------------------------------------------- completeness

def completeness(record, key_fields):
	"""(percent complete, [labels of missing details])"""
	missing = [label for field, label in key_fields if not str(getattr(record, field, '') or '').strip()]
	percent = round(100 * (len(key_fields) - len(missing)) / len(key_fields))
	return percent, missing


def missing_filter(key_fields, field):
	"""Q for records missing ``field``, or missing any key detail when field is 'any'."""
	fields = [name for name, _ in key_fields] if field == 'any' else [field]
	condition = Q()
	for name in fields:
		condition |= Q(**{name: ''}) | Q(**{f'{name}__isnull': True})
	return condition


def annotate_completeness(records, key_fields):
	for record in records:
		record.profile_percent, record.profile_missing = completeness(record, key_fields)
	return records


# ---------------------------------------------------------------- duplicates

def _phone_keys(record):
	keys = []
	for field in ('mobile_number', 'alternate_number'):
		for part in re.split(r'[/,;]+', str(getattr(record, field, '') or '')):
			digits = re.sub(r'\D', '', part)
			if len(digits) >= 10:
				keys.append(digits[-10:])
	return keys


def _text_key(value):
	return re.sub(r'[^0-9A-Z]', '', str(value or '').upper())


DUPLICATE_CHECKS = [
	('bank_account_number', 'Bank account number', lambda record: [_text_key(record.bank_account_number)]),
	('gstin', 'GSTIN', lambda record: [_text_key(record.gstin)]),
	('pan', 'PAN', lambda record: [_text_key(record.pan)]),
	('phone', 'Mobile / alternate number', _phone_keys),
]


def duplicate_groups(queryset):
	"""Groups of 2+ records sharing a value: [{'field', 'label', 'value', 'records'}], bank accounts first."""
	buckets = defaultdict(dict)
	for record in queryset:
		for field, _, keys in DUPLICATE_CHECKS:
			for key in keys(record):
				if len(key) >= 5:
					buckets[(field, key)][record.pk] = record
	labels = {field: label for field, label, _ in DUPLICATE_CHECKS}
	order = {field: index for index, (field, _, _) in enumerate(DUPLICATE_CHECKS)}
	groups = [
		{'field': field, 'label': labels[field], 'value': key, 'records': sorted(records.values(), key=lambda r: r.name.casefold())}
		for (field, key), records in buckets.items() if len(records) > 1
	]
	return sorted(groups, key=lambda group: (order[group['field']], group['value']))


def duplicates_of(record, queryset):
	"""The groups that include ``record``, each listing only the other records."""
	result = []
	for group in duplicate_groups(queryset):
		if any(other.pk == record.pk for other in group['records']):
			others = [other for other in group['records'] if other.pk != record.pk]
			result.append({**group, 'records': others})
	return result


def duplicate_ids(queryset):
	return {record.pk for group in duplicate_groups(queryset) for record in group['records']}


# ---------------------------------------------------------------- Excel export

def _cell(value):
	if isinstance(value, bool):
		return 'Yes' if value else 'No'
	if isinstance(value, Decimal):
		return float(value)
	if isinstance(value, (datetime.date, int, float, str)) or value is None:
		return value
	return str(value)


def _fill_sheet(sheet, columns, records, row_values):
	sheet.append(columns)
	for number, record in enumerate(records, start=1):
		values = row_values(record)
		values['Sl No'] = number
		sheet.append([_cell(values.get(heading)) for heading in columns])
	for cell in sheet[1]:
		cell.font = cell.font.copy(bold=True, color='FFFFFF')
		cell.fill = cell.fill.copy(fill_type='solid', fgColor='203B67')
		cell.alignment = cell.alignment.copy(wrap_text=True, vertical='center')
	sheet.row_dimensions[1].height = 42
	sheet.freeze_panes = 'C2'
	sheet.auto_filter.ref = sheet.dimensions
	for column in sheet.columns:
		width = max(len(str(cell.value or '')) for cell in column)
		sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 40)
		for cell in column[1:]:
			if isinstance(cell.value, datetime.date):
				cell.number_format = 'yyyy-mm-dd'


def workbook_response(filename, sheets):
	"""An .xlsx with one sheet per (title, columns, records, row_values); ``row_values(record)`` gives {heading: value}."""
	workbook = Workbook()
	workbook.remove(workbook.active)
	for title, columns, records, row_values in sheets:
		_fill_sheet(workbook.create_sheet(title), columns, records, row_values)
	output = BytesIO()
	workbook.save(output)
	response = HttpResponse(output.getvalue(), content_type=XLSX_CONTENT_TYPE)
	response['Content-Disposition'] = f'attachment; filename="{filename}_{datetime.date.today():%Y-%m-%d}.xlsx"'
	return response


def export_response(records, columns, row_values, filename, sheet_title):
	"""An .xlsx in the upload-template columns, so an export can be edited and checked against the template."""
	return workbook_response(filename, [(sheet_title, columns, records, row_values)])


def check_value(value):
	return '' if value is None else ('OK' if value else 'Not OK')


# ---------------------------------------------------------------- phones and vCard

def phone_numbers(*values):
	"""Each phone number found in the given fields, as (shown text, +91 dial string, WhatsApp digits)."""
	numbers, seen = [], set()
	for value in values:
		for part in re.split(r'[/,;]+', str(value or '')):
			shown = part.strip()
			digits = re.sub(r'\D', '', shown)
			if len(digits) < 6:
				continue
			if len(digits) == 10:
				dial, whatsapp = f'+91{digits}', f'91{digits}'
			elif len(digits) == 12 and digits.startswith('91'):
				dial, whatsapp = f'+{digits}', digits
			elif len(digits) == 11 and digits.startswith('0'):
				dial, whatsapp = f'+91{digits[1:]}', (f'91{digits[1:]}' if digits[1] in '6789' else '')
			else:
				dial, whatsapp = digits, ''
			# Only Indian mobile numbers (starting 6-9) can be on WhatsApp; landlines get call links only.
			if whatsapp and whatsapp[2] not in '6789':
				whatsapp = ''
			if dial in seen:  # the same number written twice, e.g. "98765 43210" and "+91 98765-43210"
				continue
			seen.add(dial)
			numbers.append({'shown': shown, 'dial': dial, 'whatsapp': whatsapp})
	return numbers


def _vcard_text(value):
	return str(value or '').replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '').replace(',', '\\,').replace(';', '\\;')


def vcard_response(record, code, kind):
	person = record.contact_person.strip()
	lines = [
		'BEGIN:VCARD', 'VERSION:3.0',
		f'FN:{_vcard_text(person or record.name)}',
		f'N:{_vcard_text(person or record.name)};;;;',
		f'ORG:{_vcard_text(record.name)}',
	]
	for index, number in enumerate(phone_numbers(record.mobile_number, record.alternate_number)):
		lines.append(f'TEL;TYPE={"CELL" if index == 0 else "VOICE"}:{number["dial"]}')
	lines.extend(f'EMAIL;TYPE=WORK:{email}' for email in split_emails(record.email))
	if record.full_address or record.city:
		lines.append(
			f'ADR;TYPE=WORK:;;{_vcard_text(record.full_address)};{_vcard_text(record.city)};'
			f'{_vcard_text(record.state)};{_vcard_text(record.pin_code)};India'
		)
	note = [f'{kind} {code}']
	if record.gstin:
		note.append(f'GSTIN {record.gstin}')
	lines.append(f'NOTE:{_vcard_text(" · ".join(note))}')
	lines.append('END:VCARD')
	response = HttpResponse('\r\n'.join(lines) + '\r\n', content_type='text/vcard; charset=utf-8')
	response['Content-Disposition'] = f'attachment; filename="{slugify(record.name) or code}.vcf"'
	return response
