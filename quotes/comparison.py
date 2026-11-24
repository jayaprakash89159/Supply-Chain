"""Comparative statement: every vendor's rates side by side, landed totals and L1/L2/L3 ranking.

Shared by the on-screen statement and its Excel export so both always show the same numbers.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal('0.01')


def money(value):
	return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class VendorColumn:
	recipient: object
	quote: object
	lines: dict = field(default_factory=dict)       # item id -> VendorQuoteLine
	basic: Decimal = Decimal('0')                   # total before GST
	gst: Decimal = Decimal('0')
	freight: Decimal = Decimal('0')
	missing: int = 0                                # items this vendor did not price
	rank: str = ''

	@property
	def landed(self):
		return money(self.basic + self.gst + self.freight)

	@property
	def complete(self):
		return self.missing == 0


@dataclass
class ItemRow:
	item: object
	cells: list                                     # per vendor: dict(rate, gst, amount, lowest, remark) or None
	lowest_rate: Decimal | None


def build(quote_request):
	"""(item rows, vendor columns) for one quote request. Columns are ordered by rank."""
	items = list(quote_request.items.all())
	columns = []
	for recipient in quote_request.recipients.select_related('response').prefetch_related('response__lines'):
		response = getattr(recipient, 'response', None)
		if response is None:
			continue
		column = VendorColumn(recipient, response, {line.item_id: line for line in response.lines.all()})
		column.freight = response.freight or Decimal('0')
		if items:
			for item in items:
				line = column.lines.get(item.pk)
				if line is None:
					column.missing += 1
					continue
				amount = item.quantity * line.rate
				column.basic += amount
				column.gst += amount * line.gst_percent / 100
		elif response.lump_sum is not None:
			column.basic = response.lump_sum
			column.gst = response.lump_sum * (response.lump_sum_gst_percent or 0) / 100
		else:
			column.missing = 1
		column.basic, column.gst = money(column.basic), money(column.gst)
		columns.append(column)

	# Complete quotes first, cheapest landed total first; incomplete ones after, unranked.
	columns.sort(key=lambda c: (not c.complete, c.landed, c.recipient.vendor_name.casefold()))
	position = 0
	for column in columns:
		if column.complete:
			position += 1
			column.rank = f'L{position}'

	rows = []
	for item in items:
		rates = [c.lines[item.pk].rate for c in columns if item.pk in c.lines]
		lowest = min(rates) if rates else None
		cells = []
		for column in columns:
			line = column.lines.get(item.pk)
			if line is None:
				cells.append(None)
				continue
			cells.append({
				'rate': line.rate, 'gst': line.gst_percent, 'amount': money(item.quantity * line.rate),
				'lowest': lowest is not None and line.rate == lowest and len(rates) > 1, 'remark': line.remark,
			})
		rows.append(ItemRow(item, cells, lowest))
	return rows, columns
