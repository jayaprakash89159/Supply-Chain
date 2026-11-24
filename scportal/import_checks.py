"""Turn Excel cells into model values and explain every problem in terms of the sheet: row, vendor, column.

Both the supplier and the Labour & Composite uploads use check_row(), so they accept the same cell formats
and give the same messages.
"""
import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models
from openpyxl.utils.datetime import from_excel

from .excel import parse_boolean, parse_status

# Cells holding only one of these count as empty in number, date and yes/no columns.
BLANK_WORDS = {'', '-', '--', 'na', 'n/a', 'nil', 'none', 'null', '#n/a'}
DATE_FORMATS = ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d-%b-%Y', '%d %b %Y', '%d-%B-%Y', '%d %B %Y')
RATING_HINT = 'Enter a number from 0 to 5 (for example 4 or 4.5), or leave the cell empty.'
DATE_HINT = 'Use YYYY-MM-DD (for example 2026-09-01) or DD-MM-YYYY, or leave the cell empty.'


@dataclass
class Problem:
	row: int | None
	record: str
	column: str
	message: str

	@property
	def text(self):
		where = f'Row {self.row}' if self.row else 'File'
		if self.record:
			where += f' ({self.record})'
		if self.column:
			where += f', column “{self.column}”'
		return f'{where}: {self.message}'


class ImportProblems(ValidationError):
	"""Every problem found in a workbook. Behaves like a ValidationError whose messages are the problem texts."""

	def __init__(self, problems):
		self.problems = problems
		super().__init__([problem.text for problem in problems])


def _show(value):
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	text = str(value).strip()
	return '“”  (a blank-looking cell, e.g. only spaces)' if not text else f'“{text}”'


def _is_blank(value):
	return value is None or (isinstance(value, str) and value.strip().casefold() in BLANK_WORDS)


def _decimal(field, value):
	if _is_blank(value):
		return None
	if isinstance(value, bool):
		raise ValidationError(f'{_show(value)} is not a number. {RATING_HINT}')
	try:
		number = Decimal(str(value).strip().replace(',', '.'))
	except InvalidOperation:
		raise ValidationError(f'{_show(value)} is not a number. {RATING_HINT}')
	if not number.is_finite():
		raise ValidationError(f'{_show(value)} is not a number. {RATING_HINT}')
	if field.name.endswith('_rating') and not 0 <= number <= 5:
		raise ValidationError(f'{_show(value)} is outside the 0–5 rating scale. {RATING_HINT}')
	# Ratings are often formulas (e.g. 4.3333); keep the 2 decimals the portal stores.
	return number.quantize(Decimal(1).scaleb(-field.decimal_places), rounding=ROUND_HALF_UP)


def _whole_number(value):
	if _is_blank(value):
		return None
	hint = 'Enter a whole number such as 40, or leave the cell empty.'
	try:
		number = float(str(value).strip().replace(',', ''))
	except ValueError:
		raise ValidationError(f'{_show(value)} is not a number. {hint}')
	if not number.is_integer() or number < 0:
		raise ValidationError(f'{_show(value)} is not a whole number. {hint}')
	return int(number)


def _date(value):
	if _is_blank(value):
		return None
	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value
	if isinstance(value, (int, float)) and not isinstance(value, bool) and 20000 < value < 80000:
		return from_excel(value).date()  # an Excel date stored as a plain number
	text = str(value).strip()
	for date_format in DATE_FORMATS:
		try:
			return datetime.datetime.strptime(text, date_format).date()
		except ValueError:
			continue
	raise ValidationError(f'{_show(value)} is not a date. {DATE_HINT}')


def _boolean(value):
	if _is_blank(value):
		return None
	try:
		return parse_boolean(value)
	except ValidationError:
		raise ValidationError(f'{_show(value)} is not a yes/no value. Use Yes or No (OK or Not OK also work), or leave the cell empty.')


_DEFAULT = object()


def _status(field, value):
	if _is_blank(value):
		return _DEFAULT
	status = parse_status(value)
	if status not in dict(field.choices):
		labels = ', '.join(label for _, label in field.choices)
		raise ValidationError(f'{_show(value)} is not a status the portal knows. Use one of: {labels}.')
	return status


def convert_cell(field, value):
	"""Convert one cell for ``field``; returns _DEFAULT when the model default should be used."""
	if isinstance(field, models.BooleanField):
		return _boolean(value)
	if isinstance(field, models.DecimalField):
		return _decimal(field, value)
	if isinstance(field, (models.IntegerField,)):
		return _whole_number(value)
	if isinstance(field, models.DateField):
		return _date(value)
	if field.choices:
		return _status(field, value)
	return value


def _model_messages(model, exc, values):
	"""Rewrite Django's model validation errors into {field: [plain messages]}."""
	result = {}
	constraints = {constraint.name: constraint for constraint in model._meta.constraints}
	for field_name, errors in exc.error_dict.items():
		for error in errors:
			params = error.params or {}
			target, message = field_name, None
			if field_name == '__all__':
				name = next((name for name in constraints if name in str(error.message % params if params else error.message)), '')
				target = next((field.name for field in model._meta.fields if field.name in name), '__all__')
				message = f'The value is outside the allowed range. {RATING_HINT}' if target.endswith('_rating') else None
			elif error.code == 'unique':
				in_bin = model.objects.filter(**{field_name: values.get(field_name)}, archived_at__isnull=False).exists()
				message = (
					f'{_show(values.get(field_name, ""))} is in the Recycle bin (it was deleted). Restore it from Recycle bin, or delete it permanently there before uploading it again.'
					if in_bin else
					f'{_show(values.get(field_name, ""))} is already in the portal. Each vendor code can be uploaded only once — remove this row, or edit the existing record instead.'
				)
			elif error.code == 'blank':
				message = 'This cell is empty, but the column is required.'
			elif error.code == 'max_length':
				message = f'{_show(values.get(field_name, ""))} is too long ({params.get("show_value")} characters; the limit is {params.get("limit_value")}).'
			if message is None:
				message = ' '.join(ValidationError(error).messages)
			result.setdefault(target, []).append(message)
	return result


def record_label(values, code_field):
	code = str(values.get(code_field) or '').strip()
	name = str(values.get('name') or '').strip()
	return ' – '.join(part for part in (code, name) if part)


def check_row(model, values, row_number, columns, code_field):
	"""Convert and validate one sheet row.

	``values`` maps model field names to raw cell values; ``columns`` maps field names to the column headings
	used in the uploaded sheet. Returns (unsaved instance, list of Problem).
	"""
	record = record_label(values, code_field)
	problems = []
	for name in list(values):
		try:
			converted = convert_cell(model._meta.get_field(name), values[name])
		except ValidationError as exc:
			values.pop(name)
			problems.extend(Problem(row_number, record, columns.get(name, name), message) for message in exc.messages)
			continue
		if converted is _DEFAULT:
			values.pop(name)
		else:
			values[name] = converted
	instance = model(**values)
	try:
		instance.full_clean()
	except ValidationError as exc:
		for name, messages in _model_messages(model, exc, values).items():
			column = '' if name == '__all__' else columns.get(name, model._meta.get_field(name).verbose_name.capitalize())
			if any(problem.column == column and problem.row == row_number for problem in problems):
				continue  # already reported while converting the cell
			problems.extend(Problem(row_number, record, column, message) for message in messages)
	return instance, problems


def duplicate_problem(row_number, values, code_field, column, first_row):
	code = str(values.get(code_field) or '').strip()
	return Problem(
		row_number, record_label(values, code_field), column,
		f'Vendor code “{code}” is used again — it already appears on row {first_row} of this sheet. Each vendor needs its own code.',
	)


def read_error(exc):
	return ValidationError(
		'This file could not be opened as an Excel workbook. Save it in Excel as “Excel Workbook (*.xlsx)” and upload it again. '
		f'(Details: {exc})'
	)


def upload_summary(problems):
	rows = len({problem.row for problem in problems})
	return (
		f'Nothing was imported. Found {len(problems)} problem{"s" if len(problems) != 1 else ""} '
		f'in {rows} row{"s" if rows != 1 else ""}. Fix the cells listed below and upload the file again.'
	)
