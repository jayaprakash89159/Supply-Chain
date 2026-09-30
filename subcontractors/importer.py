"""Excel template, upload and linked names for Labour & Composite subcontractors."""
from django.core.exceptions import ValidationError
from django.db import transaction

from materials.models import Trade
from relationships.models import DirectSubcontractorProject, DirectSubcontractorTrade
from scportal.excel import header_key, numbers_as_text, open_sheet, parse_boolean, parse_status, template_response
from suppliers.links import named_record, project_record, split_names

from .models import DirectSubcontractor

SHEET_TITLE = 'Labour & Composite'

UPLOAD_COLUMNS = [
	'Sl No', 'Vendor Code', 'Vendor / Firm Name', 'Trade', 'Service Type', 'Scope of Work',
	'Labour Strength Available (Nos)', 'Labour Licence No.', 'ESI Reg. No.', 'PF Reg. No.',
	'Contact Person', 'Mobile No.', 'Alternate No.', 'Email', 'Full Address', 'City', 'State',
	'PIN Code', 'GST Registration Type', 'GSTIN', 'GST State Code', 'PAN', 'GSTIN Check',
	'MSME Category', 'Udyam Reg. No.', 'TDS Section', 'Bank A/c Holder Name', 'Bank Name',
	'Bank A/c No.', 'IFSC', 'Branch', 'IFSC Check', 'Referred By', 'Worked with VISHWA Before?',
	'Project(s) Worked On', 'Quality (1-5)', 'Timeliness (1-5)', 'Safety (1-5)', 'Overall Rating',
	'Last Reviewed On', 'Status', 'Remarks',
]

FIELD_HEADERS = {
	'Vendor Code': 'code',
	'Vendor / Firm Name': 'name',
	'Service Type': 'service_type',
	'Scope of Work': 'scope_of_work',
	'Labour Strength Available (Nos)': 'labour_strength',
	'Labour Licence No.': 'labour_licence_number',
	'ESI Reg. No.': 'esi_registration_number',
	'PF Reg. No.': 'pf_registration_number',
	'Contact Person': 'contact_person',
	'Mobile No.': 'mobile_number',
	'Alternate No.': 'alternate_number',
	'Email': 'email',
	'Full Address': 'full_address',
	'City': 'city',
	'State': 'state',
	'PIN Code': 'pin_code',
	'GST Registration Type': 'gst_registration_type',
	'GSTIN': 'gstin',
	'GST State Code': 'gst_state_code',
	'PAN': 'pan',
	'GSTIN Check': 'gstin_check',
	'MSME Category': 'msme_category',
	'Udyam Reg. No.': 'udyam_registration_number',
	'TDS Section': 'tds_section',
	'Bank A/c Holder Name': 'bank_account_holder_name',
	'Bank Name': 'bank_name',
	'Bank A/c No.': 'bank_account_number',
	'IFSC': 'ifsc',
	'Branch': 'bank_branch',
	'IFSC Check': 'ifsc_check',
	'Referred By': 'referred_by',
	'Worked with VISHWA Before?': 'worked_with_vishwa_before',
	'Quality (1-5)': 'quality_rating',
	'Timeliness (1-5)': 'timeliness_rating',
	'Safety (1-5)': 'safety_rating',
	'Overall Rating': 'overall_rating',
	'Last Reviewed On': 'last_reviewed_on',
	'Status': 'status',
	'Remarks': 'remarks',
}
LINK_HEADERS = {'Trade': 'trades', 'Project(s) Worked On': 'projects'}
LINK_FIELDS = tuple(LINK_HEADERS.values())
HEADER_ALIASES = {'Labour Strength Available': 'labour_strength', 'Labour Strength': 'labour_strength'}
BOOLEAN_FIELDS = ('gstin_check', 'ifsc_check', 'worked_with_vishwa_before')
NUMBER_TEXT_FIELDS = ('pin_code', 'mobile_number', 'alternate_number', 'bank_account_number', 'gst_state_code')
NON_TEXT_COLUMNS = {
	'Sl No', 'Labour Strength Available (Nos)', 'GSTIN Check', 'IFSC Check', 'Worked with VISHWA Before?',
	'Quality (1-5)', 'Timeliness (1-5)', 'Safety (1-5)', 'Overall Rating', 'Last Reviewed On',
}
SAMPLE_ROWS = [
	[
		1, 'SC0001', 'Sri Sai Labour Contractors', 'Civil', 'Labour', 'Shuttering and concreting labour',
		40, 'LL/HYD/2024/118', '52000123450001001', 'APHYD1234567000', 'Ramesh Kumar', '9876543210', '',
		'ramesh@example.com', 'Plot 12, Kukatpally', 'Hyderabad', 'Telangana', '500072', 'Regular',
		'36ABCPK1234F1Z5', '36', 'ABCPK1234F', 'OK', 'Micro', 'UDYAM-TS-02-0012345', '194C',
		'Sri Sai Labour Contractors', 'State Bank of India', '12345678901', 'SBIN0001234', 'Kukatpally',
		'OK', '', 'Yes', '', 4, 4, 5, 4.3, '2026-09-01', 'Active', 'Example row - replace or delete',
	],
]
INSTRUCTIONS = [
	'Labour & Composite subcontractor upload template',
	'Use the Labour & Composite sheet with these columns. The example row (SC0001) can be uploaded as a test; delete it before a real upload.',
	'Required columns: Vendor Code and Vendor / Firm Name. Existing vendor codes cannot be uploaded again.',
	'Trade and Project(s) Worked On accept any names; separate several with commas. New names are added automatically.',
	'Labour Strength Available (Nos) is a whole number. Ratings are 0 to 5. Dates use YYYY-MM-DD.',
	'Status: Active, On hold or Inactive. Checks accept OK/Not OK or Yes/No.',
]


def template_download():
	return template_response(
		'labour_composite_subcontractor_template.xlsx', SHEET_TITLE, UPLOAD_COLUMNS,
		SAMPLE_ROWS, NON_TEXT_COLUMNS, INSTRUCTIONS,
	)


def save_links(subcontractor, names):
	subcontractor.trade_links.all().delete()
	subcontractor.project_links.all().delete()
	for trade in dict.fromkeys(named_record(Trade, name) for name in names.get('trades', [])):
		DirectSubcontractorTrade.objects.create(subcontractor=subcontractor, trade=trade)
	for project in dict.fromkeys(project_record(name) for name in names.get('projects', [])):
		DirectSubcontractorProject.objects.create(subcontractor=subcontractor, project=project)


def current_names(subcontractor):
	return {
		'trades': [link.trade.name for link in subcontractor.trade_links.select_related('trade').order_by('pk')],
		'projects': [link.project.name for link in subcontractor.project_links.select_related('project').order_by('pk')],
	}


def _field_map():
	field_map = {header_key(heading): field for heading, field in {**FIELD_HEADERS, **LINK_HEADERS, **HEADER_ALIASES}.items()}
	field_map[header_key('Sl No')] = None
	return field_map


def _integer(value):
	if value in (None, ''):
		return None
	try:
		number = float(value)
	except (TypeError, ValueError):
		raise ValidationError(f'Use a whole number, not {value!r}.')
	if number != int(number) or number < 0:
		raise ValidationError(f'Use a whole number, not {value!r}.')
	return int(number)


def import_workbook(uploaded_file):
	"""Validate every row, then create all subcontractors in one transaction. Returns the count."""
	header_names, rows = open_sheet(uploaded_file, (SHEET_TITLE, 'Labour and Composite', 'Subcontractors'))
	field_map = _field_map()
	unknown = [name for name in header_names if name and header_key(name) not in field_map]
	if unknown:
		raise ValidationError(f'Unknown column(s): {", ".join(unknown)}.')
	present = {field_map[header_key(name)] for name in header_names if name}
	missing = [heading for heading, field in (('Vendor Code', 'code'), ('Vendor / Firm Name', 'name')) if field not in present]
	if missing:
		raise ValidationError(f'Missing required column(s): {", ".join(missing)}.')

	import_rows, row_errors, seen_codes = [], [], set()
	for row_number, row in enumerate(rows, start=2):
		if not any(value is not None and str(value).strip() for value in row):
			continue
		values, link_names = {}, {field: [] for field in LINK_FIELDS}
		for header, value in zip(header_names, row):
			if not header or value is None:
				continue
			field = field_map[header_key(header)]
			if field is None:
				continue
			if field in link_names:
				link_names[field] = split_names(value)
			else:
				values[field] = value.strip() if isinstance(value, str) else value
		error_count = len(row_errors)
		for field in BOOLEAN_FIELDS:
			if field in values:
				try:
					values[field] = parse_boolean(values[field])
				except ValidationError as exc:
					values.pop(field)
					row_errors.extend(f'Row {row_number}, {field}: {error}' for error in exc.messages)
		if 'labour_strength' in values:
			try:
				values['labour_strength'] = _integer(values['labour_strength'])
			except ValidationError as exc:
				values.pop('labour_strength')
				row_errors.extend(f'Row {row_number}, labour_strength: {error}' for error in exc.messages)
		numbers_as_text(values, NUMBER_TEXT_FIELDS)
		if 'status' in values:
			values['status'] = parse_status(values['status'])
		code = str(values.get('code', '')).strip()
		if code in seen_codes:
			row_errors.append(f'Row {row_number}: duplicate Vendor Code {code!r} in this workbook.')
			continue
		seen_codes.add(code)
		subcontractor = DirectSubcontractor(**values)
		try:
			subcontractor.full_clean()
		except ValidationError as exc:
			messages_by_field = getattr(exc, 'message_dict', {'row': exc.messages})
			row_errors.extend(f'Row {row_number}, {field}: {", ".join(errors)}' for field, errors in messages_by_field.items())
		if len(row_errors) == error_count:
			import_rows.append((subcontractor, link_names))

	if row_errors:
		raise ValidationError(row_errors)
	if not import_rows:
		raise ValidationError('The sheet contains no subcontractor rows to import.')
	with transaction.atomic():
		for subcontractor, link_names in import_rows:
			subcontractor.save()
			save_links(subcontractor, link_names)
	return len(import_rows)
