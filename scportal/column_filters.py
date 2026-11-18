"""Excel-style column filters and sorting for the directory lists.

Each column heading gets a dropdown listing the values in that column (with counts), like Excel's AutoFilter.
Choices travel in the URL as ``f_<column>=value`` (repeatable), so they combine with the search box,
survive paging and are applied by the Excel export too. ``sort=<column>`` / ``sort=-<column>`` sorts.
"""
from dataclasses import dataclass, field

from django.db.models import Count, Q

from . import vendor_tools

BLANK = '__blank__'
BLANK_LABEL = '(Blanks)'
PROFILE_BUCKETS = [('complete', '100% complete'), ('partial', '60–99%'), ('low', 'Below 60%')]


@dataclass
class Column:
	key: str
	label: str
	lookups: tuple = ()          # model lookups whose values are listed; several are merged (materials + trades)
	kind: str = 'text'           # text | number | choice | profile
	sort: str = ''               # model field to sort by; empty = not sortable
	choices: dict = field(default_factory=dict)
	css: str = ''

	@property
	def param(self):
		return f'f_{self.key}'


def _selected(request, column):
	return [value for value in request.GET.getlist(column.param) if value != '']


def _profile_bucket(percent):
	return 'complete' if percent == 100 else 'partial' if percent >= 60 else 'low'


def _blank_q(column):
	condition = Q()
	for lookup in column.lookups:
		part = Q(**{f'{lookup}__isnull': True})
		if column.kind != 'number':
			part |= Q(**{lookup: ''})
		condition &= part
	return condition


def _filter(queryset, column, values, key_fields):
	if column.kind == 'profile':
		ids = [
			record.pk for record in queryset
			if _profile_bucket(vendor_tools.completeness(record, key_fields)[0]) in values
		]
		return queryset.filter(pk__in=ids)
	condition = Q()
	real = [value for value in values if value != BLANK]
	for lookup in column.lookups:
		if real:
			condition |= Q(**{f'{lookup}__in': real})
	if BLANK in values:
		condition |= _blank_q(column)
	return queryset.filter(condition).distinct()


def apply(queryset, request, columns, key_fields, skip=None):
	"""Apply every column filter from the URL (except ``skip``), then the requested sort."""
	for column in columns:
		values = _selected(request, column)
		if values and column.key != skip:
			queryset = _filter(queryset, column, values, key_fields)
	if skip is None:
		sort = request.GET.get('sort', '')
		by_key = {column.key: column for column in columns if column.sort}
		column = by_key.get(sort.lstrip('-'))
		if column:
			descending = sort.startswith('-')
			queryset = queryset.order_by(f'{"-" if descending else ""}{column.sort}', 'name', 'pk')
	return queryset


def _number_label(value):
	text = f'{value:f}' if hasattr(value, 'as_tuple') else str(value)
	return text.rstrip('0').rstrip('.') if '.' in text else text


def _values(queryset, column, key_fields):
	"""[(value, label, count)] for one column, blanks last."""
	if column.kind == 'profile':
		counts = {}
		for record in queryset:
			bucket = _profile_bucket(vendor_tools.completeness(record, key_fields)[0])
			counts[bucket] = counts.get(bucket, 0) + 1
		return [(value, label, counts[value]) for value, label in PROFILE_BUCKETS if value in counts]
	counts = {}
	for lookup in column.lookups:
		rows = queryset.order_by().values(lookup).annotate(n=Count('pk', distinct=True))
		for row in rows:
			value = row[lookup]
			if value in (None, ''):
				continue
			counts[value] = counts.get(value, 0) + row['n']
	blank_count = queryset.filter(_blank_q(column)).count()
	if column.kind == 'number':
		items = [(str(value), _number_label(value), n) for value, n in sorted(counts.items())]
	elif column.kind == 'choice':
		order = list(column.choices)
		items = [(value, column.choices.get(value, value), n) for value, n in sorted(counts.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)]
	else:
		items = [(value, value, n) for value, n in sorted(counts.items(), key=lambda kv: str(kv[0]).casefold())]
	if blank_count:
		items.append((BLANK, BLANK_LABEL, blank_count))
	return items


def headings(base_queryset, request, columns, key_fields):
	"""Data for the heading dropdowns: values come from the rows left by the *other* filters (as in Excel)."""
	sort = request.GET.get('sort', '')
	result, menus = [], {}
	for column in columns:
		selected = set(_selected(request, column))
		heading = {
			'key': column.key, 'label': column.label, 'css': column.css, 'filterable': bool(column.lookups) or column.kind == 'profile',
			'sortable': bool(column.sort), 'active': bool(selected),
			'sorted': 'asc' if sort == column.key else 'desc' if sort == f'-{column.key}' else '',
		}
		result.append(heading)
		if heading['filterable']:
			values = _values(apply(base_queryset, request, columns, key_fields, skip=column.key), column, key_fields)
			menus[column.key] = {
				'param': column.param, 'sortable': heading['sortable'], 'number': column.kind == 'number',
				'values': [{'v': value, 'l': str(label), 'n': n, 'on': not selected or value in selected} for value, label, n in values],
			}
	return result, menus


def any_active(request, columns):
	return any(_selected(request, column) for column in columns)
