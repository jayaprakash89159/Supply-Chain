"""PO numbers (per financial year) and amounts in words, Indian style."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve',
        'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def financial_year(day=None):
	"""'2026-27' for any date from 1 April 2026 to 31 March 2027."""
	day = day or timezone.localdate()
	start = day.year if day.month >= 4 else day.year - 1
	return f'{start}-{str(start + 1)[-2:]}'


def next_po_number(prefix, day=None):
	"""Next number in this financial year's series, e.g. VISPL/PO/2026-27/0007."""
	from .models import PurchaseOrder, PurchaseSettings

	fy = financial_year(day)
	stem = f'{prefix.rstrip("/")}/{fy}/'
	with transaction.atomic():
		PurchaseSettings.objects.select_for_update().filter(pk=1).first()  # serialise numbering
		used = PurchaseOrder.objects.filter(number__startswith=stem).values_list('number', flat=True)
		highest = max((int(number.rsplit('/', 1)[-1]) for number in used if number.rsplit('/', 1)[-1].isdigit()), default=0)
		return f'{stem}{highest + 1:04d}'


def _below_thousand(n):
	words = []
	if n >= 100:
		words += [ONES[n // 100], 'Hundred']
		n %= 100
	if n >= 20:
		words.append(TENS[n // 10])
		n %= 10
	if n:
		words.append(ONES[n])
	return words


def _indian(n):
	if n == 0:
		return ['Zero']
	words = []
	for size, name in ((10 ** 7, 'Crore'), (10 ** 5, 'Lakh'), (1000, 'Thousand')):
		if n >= size:
			chunk = n // size
			words += (_indian(chunk) if chunk >= 100 and size == 10 ** 7 else _below_thousand(chunk)) + [name]
			n %= size
	return words + _below_thousand(n)


def rupees_in_words(amount):
	"""Decimal('1234567.50') -> 'Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven and Fifty Paise Only'."""
	amount = Decimal(amount).quantize(Decimal('0.01'))
	rupees, paise = int(amount), int((amount - int(amount)) * 100)
	text = 'Rupees ' + ' '.join(_indian(rupees))
	if paise:
		text += ' and ' + ' '.join(_below_thousand(paise)) + ' Paise'
	return text + ' Only'
