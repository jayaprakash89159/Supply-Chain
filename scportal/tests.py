"""Tests for the vendor tools: export, duplicates, completeness, bulk status, phone links and vCard."""
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook

from materials.models import Trade
from relationships.models import DirectSubcontractorTrade
from scportal.vendor_tools import phone_numbers
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier


class VendorToolsTests(TestCase):
	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(username='boss', email='b@example.com', password='pw')
		self.viewer = get_user_model().objects.create_user(username='viewer', password='pw')
		self.full = Supplier.objects.create(
			vendor_code='SP1', name='Alpha Steel', supplier_type='Dealer', contact_person='Ravi', mobile_number='98765 43210',
			email='a@alpha.in; b@alpha.in', full_address='Plot 1', city='Hyderabad', state='Telangana', pin_code='500001',
			gstin='36ABCPK1234F1Z5', pan='ABCPK1234F', bank_name='SBI', bank_account_number='1234567890', ifsc='SBIN0001234',
			gstin_check=True, worked_with_vishwa_before=True, overall_rating='4.50',
		)
		self.twin = Supplier.objects.create(
			vendor_code='SP2', name='Beta Traders', city='Pune', bank_account_number='12345 67890', alternate_number='+91 98765-43210',
		)
		self.other = Supplier.objects.create(vendor_code='SP3', name='Gamma Cement', city='Pune', status='on_hold')

	# Export -------------------------------------------------------------------------------------
	def test_export_uses_template_columns_and_current_filters(self):
		self.client.force_login(self.viewer)
		response = self.client.get('/suppliers/export.xlsx', {'city': 'Pune'})
		self.assertEqual(response.status_code, 200)
		self.assertIn('attachment; filename="suppliers_', response['Content-Disposition'])
		sheet = load_workbook(BytesIO(response.content)).active
		headers = [cell.value for cell in sheet[1]]
		self.assertEqual(headers[:3], ['Sl No', 'Vendor Code', 'Vendor / Firm Name'])
		codes = sorted(row[1] for row in sheet.iter_rows(min_row=2, values_only=True))
		self.assertEqual(codes, ['SP2', 'SP3'])

	def test_export_values_are_readable(self):
		self.client.force_login(self.viewer)
		sheet = load_workbook(BytesIO(self.client.get('/suppliers/export.xlsx', {'q': 'Alpha'}).content)).active
		row = dict(zip([c.value for c in sheet[1]], [c.value for c in sheet[2]]))
		self.assertEqual(row['Status'], 'Active')
		self.assertEqual(row['GSTIN Check'], 'OK')
		self.assertEqual(row['Worked with VISHWA Before?'], 'Yes')
		self.assertEqual(row['Overall Rating'], 4.5)
		self.assertEqual(row['Email'], 'a@alpha.in; b@alpha.in')

	def test_subcontractor_export_includes_trades(self):
		sub = DirectSubcontractor.objects.create(code='LC1', name='Gang One')
		DirectSubcontractorTrade.objects.create(subcontractor=sub, trade=Trade.objects.create(name='Civil'))
		self.client.force_login(self.viewer)
		sheet = load_workbook(BytesIO(self.client.get('/subcontractors/export.xlsx').content)).active
		row = dict(zip([c.value for c in sheet[1]], [c.value for c in sheet[2]]))
		self.assertEqual((row['Vendor Code'], row['Trade']), ('LC1', 'Civil'))

	# Duplicates ---------------------------------------------------------------------------------
	def test_duplicate_page_finds_shared_bank_account_and_phone(self):
		self.client.force_login(self.viewer)
		response = self.client.get('/suppliers/duplicates/')
		self.assertContains(response, 'Bank account number')
		self.assertContains(response, '1234567890')
		self.assertContains(response, '9876543210')
		self.assertNotContains(response, 'Gamma Cement')

	def test_profile_warns_about_duplicate_and_list_filter(self):
		self.client.force_login(self.viewer)
		response = self.client.get(f'/suppliers/{self.twin.pk}/')
		self.assertContains(response, 'Possible duplicate')
		self.assertContains(response, 'Alpha Steel')
		listing = self.client.get('/suppliers/', {'duplicates': '1'})
		self.assertContains(listing, 'Beta Traders')
		self.assertNotContains(listing, 'Gamma Cement')

	# Completeness -------------------------------------------------------------------------------
	def test_completeness_shown_and_missing_filter(self):
		self.client.force_login(self.viewer)
		self.assertContains(self.client.get(f'/suppliers/{self.full.pk}/'), 'Profile 100% complete')
		response = self.client.get(f'/suppliers/{self.other.pk}/')
		self.assertContains(response, 'Missing: Supplier type, Contact person')
		listing = self.client.get('/suppliers/', {'missing': 'pan'})
		self.assertContains(listing, 'Gamma Cement')
		self.assertNotContains(listing, 'Alpha Steel')
		self.assertNotContains(self.client.get('/suppliers/', {'missing': 'any'}), 'Alpha Steel')

	# Bulk status --------------------------------------------------------------------------------
	def test_admin_sets_status_for_selected(self):
		self.client.force_login(self.admin)
		response = self.client.post('/suppliers/set-status/', {'ids': [self.full.pk, self.twin.pk], 'status': 'inactive'}, follow=True)
		self.assertContains(response, 'Status set to Inactive for 2 suppliers.')
		self.assertEqual(set(Supplier.objects.filter(status='inactive').values_list('vendor_code', flat=True)), {'SP1', 'SP2'})

	def test_status_needs_a_valid_choice_and_admin(self):
		self.client.force_login(self.admin)
		response = self.client.post('/suppliers/set-status/', {'ids': [self.full.pk], 'status': 'bogus'}, follow=True)
		self.assertContains(response, 'Choose the new status first')
		self.client.force_login(self.viewer)
		self.client.post('/suppliers/set-status/', {'ids': [self.full.pk], 'status': 'inactive'})
		self.assertEqual(Supplier.objects.get(pk=self.full.pk).status, 'active')

	# Phones and vCard ---------------------------------------------------------------------------
	def test_phone_numbers(self):
		numbers = phone_numbers('98765 43210 / 040-27763835', '+91 98765-43210')
		self.assertEqual([n['dial'] for n in numbers], ['+919876543210', '+914027763835'])
		self.assertEqual([n['whatsapp'] for n in numbers], ['919876543210', ''])

	def test_profile_has_call_whatsapp_and_vcard(self):
		self.client.force_login(self.viewer)
		response = self.client.get(f'/suppliers/{self.full.pk}/')
		self.assertContains(response, 'href="tel:+919876543210"')
		self.assertContains(response, 'href="https://wa.me/919876543210"')
		vcard = self.client.get(f'/suppliers/{self.full.pk}/contact.vcf')
		self.assertEqual(vcard['Content-Type'], 'text/vcard; charset=utf-8')
		text = vcard.content.decode()
		for line in ('FN:Ravi', 'ORG:Alpha Steel', 'TEL;TYPE=CELL:+919876543210', 'EMAIL;TYPE=WORK:b@alpha.in', 'NOTE:Supplier SP1'):
			self.assertIn(line, text)
		sub = DirectSubcontractor.objects.create(code='LC9', name='G')
		self.assertEqual(self.client.get(f'/subcontractors/{sub.pk}/contact.vcf').status_code, 200)

	def test_list_pages_render_for_admin_and_viewer(self):
		DirectSubcontractor.objects.create(code='LC2', name='Gang Two', mobile_number='9123456780')
		for user in (self.admin, self.viewer):
			self.client.force_login(user)
			for url in ('/suppliers/', '/subcontractors/', '/subcontractors/duplicates/', '/search/?q=98765'):
				self.assertEqual(self.client.get(url).status_code, 200, url)
		self.client.force_login(self.admin)
		self.assertContains(self.client.get('/suppliers/'), 'Set status')
		self.assertContains(self.client.get('/subcontractors/', {'q': 'Gang'}), 'wa.me/919123456780')
