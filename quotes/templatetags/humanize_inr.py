"""{{ value|inr }}: Indian digit grouping with two decimals, e.g. 1234567.5 -> 12,34,567.50."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def inr(value):
	try:
		number = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
	except (InvalidOperation, TypeError, ValueError):
		return value
	sign = '-' if number < 0 else ''
	whole, fraction = f'{abs(number):.2f}'.split('.')
	if len(whole) > 3:
		head, tail = whole[:-3], whole[-3:]
		groups = []
		while len(head) > 2:
			groups.insert(0, head[-2:])
			head = head[:-2]
		if head:
			groups.insert(0, head)
		whole = ','.join(groups + [tail])
	return f'{sign}{whole}.{fraction}'
