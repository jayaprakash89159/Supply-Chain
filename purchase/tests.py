import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from quotes.models import QuoteItem, QuoteRecipient, QuoteRequest, VendorQuote, VendorQuoteLine
from suppliers.models import Supplier

from .models import ApprovalLevel, PurchaseOrder, PurchaseSettings
from .numbers import financial_year, rupees_in_words

User = get_user_model()


class PurchaseOrderFlowTests(TestCase):
	def setUp(self):
		self.buyer = User.objects.create_superuser(username='buyer', email='buyer@vishwa.test', password='pw')
		self.head = User.objects.create_user(username='head', email='head@vishwa.test', password='pw')
		self.md = User.objects.create_user(username='md', email='md@vishwa.test', password='pw')
		self.viewer = User.objects.create_user(username='viewer', password='pw')
		level1 = ApprovalLevel.objects.create(order=1, name='Purchase head', min_amount=0)
		level1.approvers.add(self.head)
		level2 = ApprovalLevel.objects.create(order=2, name='Managing Director', min_amount=Decimal('2500000'))
		level2.approvers.add(self.md)
		PurchaseSettings.objects.create(pk=1, company_state_code='36')

		self.alpha = Supplier.objects.create(vendor_code='A1', name='Alpha Steel', email='a@alpha.test', gstin='36ABCPK1234F1Z5', city='Hyderabad')
		self.beta = Supplier.objects.create(vendor_code='B1', name='Beta Steel', email='b@beta.test', gstin='27ABCPK1234F1Z5', city='Pune')
		self.rfq = QuoteRequest.objects.create(subject='TMT – {vendor_name}', body='{requirement}', sent_by=self.buyer)
		self.i8 = QuoteItem.objects.create(request=self.rfq, position=1, description='TMT 8 mm', quantity=10, unit='MT')
		self.i12 = QuoteItem.objects.create(request=self.rfq, position=2, description='TMT 12 mm', quantity=25, unit='MT')
		self.ra = self._quote(self.alpha, {self.i8: 60000, self.i12: 58000}, freight=10000)
		self.rb = self._quote(self.beta, {self.i8: 59000, self.i12: 59500})
		self.client.force_login(self.buyer)

	def _quote(self, vendor, rates, freight=None):
		recipient = QuoteRecipient.objects.create(request=self.rfq, kind='supplier', vendor_id=vendor.pk, vendor_code=vendor.vendor_code,
		                                          vendor_name=vendor.name, emails=vendor.email, status='sent')
		response = VendorQuote.objects.create(recipient=recipient, freight=freight, payment_terms='30 days')
		for item, rate in rates.items():
			VendorQuoteLine.objects.create(quote=response, item=item, rate=rate, gst_percent=18)
		return recipient

	def award(self, **picks):
		data = {f'award_{item.pk}': str(recipient.pk) if recipient else '' for item, recipient in picks.get('picks', {}).items()}
		data['reason'] = picks.get('reason', '')
		return self.client.post(f'/purchase/award/{self.rfq.pk}/', data)

	def fill_and_submit(self, order):
		self.client.post(f'/purchase/{order.pk}/', {
			'delivery_address': 'Kollapur site, Telangana', 'place_of_supply': '36',
			'delivery_date': (timezone.localdate() + datetime.timedelta(days=10)).isoformat(),
			'payment_terms': '30 days', 'freight': order.freight, 'freight_gst_percent': '18', 'terms': 'Standard terms',
			**{f'{name}_{line.pk}': value for line in order.lines.all() for name, value in (('qty', line.quantity), ('rate', line.rate), ('gst', line.gst_percent))},
		})
		return self.client.post(f'/purchase/{order.pk}/submit/', follow=True)

	def test_award_defaults_to_lowest_and_splits_by_vendor(self):
		page = self.client.get(f'/purchase/award/{self.rfq.pk}/')
		chosen = {c['item'].description: c['chosen'] for c in page.context['choices']}
		self.assertEqual(chosen, {'TMT 8 mm': str(self.rb.pk), 'TMT 12 mm': str(self.ra.pk)})
		self.award(picks={self.i8: self.rb, self.i12: self.ra})
		orders = {o.vendor_code: o for o in PurchaseOrder.objects.all()}
		self.assertEqual(set(orders), {'A1', 'B1'})
		self.assertEqual([l.description for l in orders['A1'].lines.all()], ['TMT 12 mm'])
		self.assertEqual(orders['A1'].freight, Decimal('10000.00'))
		self.assertEqual(orders['A1'].vendor_state_code, '36')
		self.assertEqual(orders['B1'].status, 'draft')

	def test_non_lowest_needs_a_reason_and_items_are_not_awarded_twice(self):
		response = self.award(picks={self.i8: self.ra, self.i12: self.ra})
		self.assertContains(response, 'Give the reason')
		self.assertFalse(PurchaseOrder.objects.exists())
		self.award(picks={self.i8: self.ra, self.i12: self.ra}, reason='Alpha delivers 10 days earlier')
		order = PurchaseOrder.objects.get()
		self.assertEqual(order.award_reason, 'Alpha delivers 10 days earlier')
		again = self.client.get(f'/purchase/award/{self.rfq.pk}/')
		self.assertTrue(all(choice['ordered'] for choice in again.context['choices']))

	def test_gst_split_intra_and_interstate(self):
		self.award(picks={self.i8: self.rb, self.i12: self.ra})
		alpha = PurchaseOrder.objects.get(vendor_code='A1')   # Telangana vendor, Telangana site -> CGST + SGST
		beta = PurchaseOrder.objects.get(vendor_code='B1')    # Maharashtra vendor -> IGST
		a = alpha.totals()
		self.assertEqual((a['basic'], a['freight']), (Decimal('1450000.00'), Decimal('10000.00')))
		self.assertEqual(a['cgst'] + a['sgst'], Decimal('262800.00'))  # 18% of 14,60,000
		self.assertEqual(a['igst'], 0)
		self.assertEqual(a['grand'], Decimal('1722800.00'))
		self.assertTrue(beta.interstate)
		self.assertEqual(beta.totals()['igst'], Decimal('106200.00'))

	def test_maker_checker_and_single_level_approval_gives_number(self):
		self.award(picks={self.i8: self.rb, self.i12: ''})
		order = PurchaseOrder.objects.get()
		response = self.fill_and_submit(order)
		self.assertContains(response, 'Waiting for approval: Purchase head')
		order.refresh_from_db()
		self.assertEqual(order.status, 'pending')
		self.assertEqual(mail.outbox[-1].to, ['head@vishwa.test'])
		# The buyer is not an approver of this level and cannot approve.
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'pending')
		self.client.force_login(self.head)
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve', 'comment': 'OK'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'approved')       # ₹6.96 lakh: only level 1 needed
		self.assertEqual(order.number, f'VISPL/PO/{financial_year()}/0001')

	def test_big_po_needs_both_levels_in_order_and_return_resets(self):
		QuoteItem.objects.filter(pk=self.i12.pk).update(quantity=40)
		self.award(picks={self.i8: '', self.i12: self.ra})
		order = PurchaseOrder.objects.get()
		order.lines.update(quantity=40)
		self.fill_and_submit(order)                       # 40 x 58,000 + 18% = ₹27.5 lakh -> MD too
		order.refresh_from_db()
		self.assertEqual([l.name for l in order.required_levels()], ['Purchase head', 'Managing Director'])
		self.client.force_login(self.md)                  # MD can't jump the queue
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'})
		self.assertEqual(order.approved_level_ids(), set())
		self.client.force_login(self.head)
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'})
		self.client.force_login(self.md)
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'reject'})   # no comment -> refused
		order.refresh_from_db()
		self.assertEqual(order.status, 'pending')
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'reject', 'comment': 'Negotiate 12 mm rate'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'rejected')
		self.client.force_login(self.buyer)
		self.fill_and_submit(order)                       # resubmitted: approvals start again
		order.refresh_from_db()
		self.assertEqual((order.status, order.next_level().name), ('pending', 'Purchase head'))

	def test_self_approval_setting(self):
		level = ApprovalLevel.objects.get(order=1)
		level.approvers.add(self.buyer)
		self.award(picks={self.i8: self.rb, self.i12: ''})
		order = PurchaseOrder.objects.get()
		self.fill_and_submit(order)
		response = self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'}, follow=True)
		self.assertContains(response, 'someone else must approve it')
		PurchaseSettings.objects.filter(pk=1).update(allow_self_approval=True)
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'approved')

	def test_submit_checks_delivery_and_levels(self):
		self.award(picks={self.i8: self.rb, self.i12: ''})
		order = PurchaseOrder.objects.get()
		response = self.client.post(f'/purchase/{order.pk}/submit/', follow=True)
		self.assertContains(response, '“Deliver to” is empty')
		self.assertContains(response, 'the delivery date is missing')

	def test_pdf_send_and_cancel(self):
		self.award(picks={self.i8: self.rb, self.i12: ''})
		order = PurchaseOrder.objects.get()
		self.fill_and_submit(order)
		self.client.force_login(self.head)
		self.client.post(f'/purchase/{order.pk}/decide/', {'decision': 'approve'})
		pdf = self.client.get(f'/purchase/{order.pk}/pdf/')
		self.assertEqual(pdf['Content-Type'], 'application/pdf')
		self.assertTrue(pdf.content.startswith(b'%PDF'))
		self.client.force_login(self.buyer)
		self.client.post(f'/purchase/{order.pk}/send/', {'how': 'email'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'sent')
		sent = mail.outbox[-1]
		self.assertEqual(sent.to, ['b@beta.test'])
		self.assertEqual(sent.attachments[0][2], 'application/pdf')
		self.assertIn(order.number, sent.subject)
		self.client.post(f'/purchase/{order.pk}/cancel/', {'reason': 'Project on hold'})
		order.refresh_from_db()
		self.assertEqual(order.status, 'cancelled')
		self.assertFalse(self.client.get(f'/purchase/award/{self.rfq.pk}/').context['choices'][0]['ordered'])

	def test_visibility_and_settings_page(self):
		self.award(picks={self.i8: self.rb, self.i12: ''})
		order = PurchaseOrder.objects.get()
		self.client.force_login(self.viewer)
		self.assertEqual(self.client.get(f'/purchase/{order.pk}/').status_code, 404)
		self.assertNotContains(self.client.get('/'), 'Purchase orders</a>')
		self.client.force_login(self.head)
		self.assertEqual(self.client.get(f'/purchase/{order.pk}/').status_code, 200)
		self.client.force_login(self.buyer)
		response = self.client.post('/purchase/settings/', {'action': 'save_level', 'order': '3', 'name': 'Board', 'min_amount': '10000000', 'approvers': [self.md.pk], 'is_active': 'on'}, follow=True)
		self.assertContains(response, 'Approval level “Board” saved')
		response = self.client.post('/purchase/settings/', {'action': 'save_level', 'order': '1', 'name': 'Dup', 'approvers': [self.md.pk]}, follow=True)
		self.assertContains(response, 'step 1 is already used')

	def test_numbers_and_words(self):
		self.assertEqual(financial_year(datetime.date(2027, 3, 31)), '2026-27')
		self.assertEqual(financial_year(datetime.date(2027, 4, 1)), '2027-28')
		self.assertEqual(rupees_in_words(Decimal('1722800')), 'Rupees Seventeen Lakh Twenty Two Thousand Eight Hundred Only')
		self.assertEqual(rupees_in_words(Decimal('123456789.50')), 'Rupees Twelve Crore Thirty Four Lakh Fifty Six Thousand Seven Hundred Eighty Nine and Fifty Paise Only')
