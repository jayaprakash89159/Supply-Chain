"""Items on the request, vendors quoting online, staff entry and the comparative statement."""
import datetime
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import load_workbook

from suppliers.models import Supplier

from .models import QuoteRecipient, QuoteRequest, VendorQuote
from .templatetags.humanize_inr import inr

MEDIA = tempfile.mkdtemp(prefix='online-quote-media-')
BODY = 'Dear {contact_person},\n{requirement}\nQuote here: {quote_link}\nBy {due_date}\n{your_name}'


@override_settings(MEDIA_ROOT=MEDIA, PORTAL_PUBLIC_URL='https://portal.vishwa.test')
class OnlineQuoteTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.buyer = get_user_model().objects.create_user(username='buyer', password='pw', email='buyer@vishwa.test')
		self.client.force_login(self.buyer)
		self.a = Supplier.objects.create(vendor_code='A1', name='Alpha Steel', contact_person='Ravi', email='a@alpha.test')
		self.b = Supplier.objects.create(vendor_code='B1', name='Beta Steel', email='b@beta.test')
		self.c = Supplier.objects.create(vendor_code='C1', name='Gamma Steel', email='c@gamma.test')

	def send(self, **extra):
		data = {
			'step': 'send', 'subject': 'RFQ – {vendor_name}', 'body': BODY, 'requirement': 'Deliver to Kollapur site',
			'due_date': (datetime.date.today() + datetime.timedelta(days=5)).isoformat(),
			'item_description': ['TMT 12 mm', 'TMT 16 mm', ''], 'item_quantity': ['25', '18.5', ''], 'item_unit': ['MT', 'MT', ''],
			'vendors': [f'supplier:{self.a.pk}', f'supplier:{self.b.pk}', f'supplier:{self.c.pk}'],
		}
		data.update(extra)
		response = self.client.post('/quotes/new/', data)
		return response, QuoteRequest.objects.order_by('-pk').first()

	def submit(self, recipient, rates, gst=('18', '18'), client=None, **extra):
		items = list(recipient.request.items.all())
		data = {'delivery': '7 days', 'payment_terms': '30 days', 'validity': '15 days', 'freight': extra.pop('freight', '')}
		for item, rate, g in zip(items, rates, gst):
			data[f'rate_{item.pk}'] = rate
			data[f'gst_{item.pk}'] = g
		data.update(extra)
		return (client or self.client).post(f'/quotes/respond/{recipient.token}/', data)

	def test_items_and_personal_link_go_into_each_email(self):
		response, quote = self.send()
		self.assertRedirects(response, f'/quotes/{quote.pk}/', fetch_redirect_response=False)
		self.assertEqual(list(quote.items.values_list('description', 'quantity', 'unit')), [
			('TMT 12 mm', Decimal('25.000'), 'MT'), ('TMT 16 mm', Decimal('18.500'), 'MT'),
		])
		alpha = quote.recipients.get(vendor_code='A1')
		first = mail.outbox[0].body
		self.assertIn('1. TMT 12 mm – 25 MT', first)
		self.assertIn('2. TMT 16 mm – 18.5 MT', first)
		self.assertIn('Deliver to Kollapur site', first)
		self.assertIn(f'https://portal.vishwa.test/quotes/respond/{alpha.token}/', first)
		self.assertNotIn(quote.recipients.get(vendor_code='B1').token, first)  # each vendor sees only their own link

	def test_item_rows_are_validated(self):
		response, _ = self.send(item_description=['TMT 12 mm', ''], item_quantity=['lots', '5'], item_unit=['MT', ''])
		self.assertContains(response, 'Item row 1 (“TMT 12 mm”): enter the quantity as a number')
		self.assertContains(response, 'Item row 2: add a description')
		self.assertEqual(len(mail.outbox), 0)

	def test_vendor_submits_online_without_login_and_can_revise(self):
		_, quote = self.send()
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		page = self.client.get(f'/quotes/respond/{recipient.token}/')
		self.assertContains(page, 'Alpha Steel')
		self.assertContains(page, 'TMT 16 mm')
		self.assertNotContains(page, 'Beta Steel')
		self.assertEqual(page['X-Robots-Tag'], 'noindex, nofollow')
		done = self.submit(recipient, ['58,000', '59000'])
		self.assertContains(done, 'quotation received')
		answer = VendorQuote.objects.get(recipient=recipient)
		self.assertIsNone(answer.entered_by)
		self.assertEqual(sorted(answer.lines.values_list('rate', flat=True)), [Decimal('58000.00'), Decimal('59000.00')])
		self.assertContains(self.submit(recipient, ['57500', '59000']), 'quotation revised')
		answer.refresh_from_db()
		self.assertEqual(answer.revisions, 1)

	def test_vendor_form_errors_and_unknown_link(self):
		_, quote = self.send()
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		self.assertContains(self.submit(recipient, ['', '']), 'Enter a rate for at least one item')
		self.assertContains(self.submit(recipient, ['abc', '']), 'the rate “abc” is not a number')
		self.assertEqual(self.client.get('/quotes/respond/not-a-real-token/').status_code, 404)

	def test_link_closes_after_due_date(self):
		_, quote = self.send()
		QuoteRequest.objects.filter(pk=quote.pk).update(due_date=datetime.date.today() - datetime.timedelta(days=1))
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		response = self.submit(recipient, ['50000', '50000'])
		self.assertContains(response, 'Quotations are closed')
		self.assertFalse(VendorQuote.objects.exists())

	def test_staff_enters_quote_even_after_closing(self):
		_, quote = self.send()
		QuoteRequest.objects.filter(pk=quote.pk).update(due_date=datetime.date.today() - datetime.timedelta(days=1))
		recipient = quote.recipients.get(vendor_code='B1')
		items = list(quote.items.all())
		response = self.client.post(f'/quotes/{quote.pk}/enter/{recipient.pk}/', {
			f'rate_{items[0].pk}': '60000', f'gst_{items[0].pk}': '18', 'delivery': '10 days',
		})
		self.assertRedirects(response, f'/quotes/{quote.pk}/', fetch_redirect_response=False)
		self.assertEqual(VendorQuote.objects.get(recipient=recipient).entered_by, self.buyer)
		other = get_user_model().objects.create_user(username='other', password='pw')
		self.client.force_login(other)
		self.assertEqual(self.client.get(f'/quotes/{quote.pk}/enter/{recipient.pk}/').status_code, 404)

	def test_comparative_statement_ranks_by_landed_total(self):
		_, quote = self.send()
		a, b, c = (quote.recipients.get(vendor_code=code) for code in ('A1', 'B1', 'C1'))
		self.submit(a, ['58000', '59000'], freight='20000')           # 25*58000 + 18.5*59000 = 2,541,500 + 18% + 20,000
		self.submit(b, ['57000', '60000'])                            # 25*57000 + 18.5*60000 = 2,535,000 + 18%
		self.submit(c, ['50000', ''])                                 # incomplete: 16 mm not quoted
		page = self.client.get(f'/quotes/{quote.pk}/compare/')
		columns = page.context['columns']
		self.assertEqual([(col.recipient.vendor_code, col.rank) for col in columns], [('B1', 'L1'), ('A1', 'L2'), ('C1', '')])
		self.assertEqual(columns[0].landed, Decimal('2991300.00'))     # 2,535,000 × 1.18
		self.assertEqual(columns[1].landed, Decimal('3018970.00'))     # 2,541,500 × 1.18 + 20,000
		self.assertContains(page, '29,91,300.00')
		self.assertContains(page, 'not quoted')
		lowest = [cell['lowest'] for cell in page.context['rows'][0].cells]
		self.assertEqual(lowest, [False, False, True])                 # Gamma's 50,000 is lowest for 12 mm
		export = self.client.get(f'/quotes/{quote.pk}/compare.xlsx')
		sheet = load_workbook(BytesIO(export.content)).active
		values = [cell for row in sheet.iter_rows(values_only=True) for cell in row]
		self.assertIn('Beta Steel (L1)', values)
		self.assertIn(2991300.0, values)

	def test_vendor_document_is_private(self):
		_, quote = self.send()
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		self.submit(recipient, ['58000', '59000'], attachment=SimpleUploadedFile('offer.pdf', b'%PDF-1.4', content_type='application/pdf'))
		url = f'/quotes/{quote.pk}/file/{recipient.pk}/'
		self.assertEqual(self.client.get(url).status_code, 302)       # needs sign-in
		self.client.force_login(self.buyer)
		self.assertEqual(self.client.get(url).status_code, 200)
		self.client.logout()
		bad = self.submit(recipient, ['58000', '59000'], attachment=SimpleUploadedFile('run.exe', b'MZ'))
		self.assertContains(bad, 'Upload a PDF, Excel, Word, CSV or image file')

	def test_detail_page_shows_status_links_and_waiting(self):
		_, quote = self.send()
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		self.submit(recipient, ['58000', '59000'])
		self.client.force_login(self.buyer)
		page = self.client.get(f'/quotes/{quote.pk}/')
		self.assertContains(page, 'Compare quotes (1 received)')
		self.assertContains(page, 'online by vendor')
		self.assertContains(page, f'/quotes/respond/{recipient.token}/')
		self.assertContains(page, 'Waiting', count=2)

	def test_lump_sum_quote_without_items(self):
		_, quote = self.send(item_description=[''], item_quantity=[''], item_unit=[''], requirement='Shuttering labour for 2 months')
		recipient = quote.recipients.get(vendor_code='A1')
		self.client.logout()
		self.client.post(f'/quotes/respond/{recipient.token}/', {'lump_sum': '450000', 'lump_sum_gst_percent': '18'})
		self.client.force_login(self.buyer)
		column = self.client.get(f'/quotes/{quote.pk}/compare/').context['columns'][0]
		self.assertEqual((column.rank, column.landed), ('L1', Decimal('531000.00')))

	def test_inr_formatting(self):
		self.assertEqual(inr(Decimal('2991300')), '29,91,300.00')
		self.assertEqual(inr(Decimal('999.5')), '999.50')
		self.assertEqual(inr(1234567890.126), '1,23,45,67,890.13')


@override_settings(PORTAL_PUBLIC_URL='')
class LinkWithoutPublicAddressTests(TestCase):
	def test_compose_warns_when_portal_is_office_only(self):
		user = get_user_model().objects.create_user(username='buyer', password='pw', email='buyer@vishwa.test')
		self.client.force_login(user)
		supplier = Supplier.objects.create(vendor_code='A1', name='Alpha', email='a@a.test')
		page = self.client.post('/quotes/new/', {'step': 'select', 'kind': 'supplier', 'ids': [supplier.pk]})
		self.assertContains(page, 'Vendors outside the office cannot open')
		self.assertContains(page, 'name="item_description"')
