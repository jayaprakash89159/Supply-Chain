from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook

from materials.models import Brand, Material, MaterialCategory, Trade
from projects.models import Project
from relationships.models import SupplierBrand, SupplierMaterial, SupplierProject, SupplierTrade
from .models import Supplier


class SupplierDirectoryTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='viewer', password='test-password')
		self.client.login(username='viewer', password='test-password')
		Supplier.objects.create(vendor_code='SUP-001', name='Northstar Steel', city='Pune', status='active')
		Supplier.objects.create(vendor_code='SUP-002', name='Riverbend Cement', city='Mumbai', status='on_hold')

	def test_directory_requires_authentication(self):
		self.client.logout()
		response = self.client.get('/suppliers/')
		self.assertRedirects(response, '/accounts/login/?next=/suppliers/')

	def test_search_filters_by_vendor_name(self):
		response = self.client.get('/suppliers/', {'q': 'northstar'})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Northstar Steel')
		self.assertNotContains(response, 'Riverbend Cement')

	def test_status_filter_combines_with_search(self):
		response = self.client.get('/suppliers/', {'q': 'SUP-', 'status': 'active'})
		self.assertContains(response, 'Northstar Steel')
		self.assertNotContains(response, 'Riverbend Cement')

	def test_normal_user_cannot_open_admin_add_form(self):
		response = self.client.get('/admin/suppliers/supplier/add/')
		self.assertEqual(response.status_code, 302)
		self.assertTrue(response.url.startswith('/admin/login/'))

	def test_supplier_profile_renders(self):
		supplier = Supplier.objects.get(vendor_code='SUP-001')
		response = self.client.get(f'/suppliers/{supplier.pk}/')
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Northstar Steel')


class SupplierAdminImportTests(TestCase):
	def setUp(self):
		user = get_user_model().objects.create_superuser(
			username='admin', email='admin@example.com', password='test-password'
		)
		self.client.force_login(user)

	def workbook_upload(self, rows):
		workbook = Workbook()
		sheet = workbook.active
		sheet.title = 'Suppliers'
		sheet.append(['Vendor Code', 'Vendor / Firm Name', 'City', 'Overall Rating'])
		for row in rows:
			sheet.append(row)
		content = BytesIO()
		workbook.save(content)
		return SimpleUploadedFile(
			'suppliers.xlsx',
			content.getvalue(),
			content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
		)

	def test_admin_can_download_supplier_template(self):
		response = self.client.get('/admin/suppliers/supplier/template.xlsx')
		self.assertEqual(response.status_code, 200)
		workbook = load_workbook(BytesIO(response.content), read_only=True)
		self.assertIn('Instructions', workbook.sheetnames)
		rows = workbook['Suppliers'].iter_rows(values_only=True)
		headers = next(rows)
		sample = next(rows)
		self.assertIn('Vendor Code', headers)
		self.assertIn('Vendor / Firm Name', headers)
		self.assertEqual(len(sample), len(headers))
		self.assertEqual(sample[1:3], ('SP0001', 'Sri Lakshmi Traders'))
		response = self.client.post(
			'/admin/suppliers/supplier/import/',
			{'file': SimpleUploadedFile('supplier_template.xlsx', response.content)},
		)
		self.assertRedirects(response, '/admin/suppliers/supplier/')
		supplier = Supplier.objects.get(vendor_code='SP0001')
		self.assertEqual(supplier.gstin, '36BCNPP5410K1ZA')
		self.assertTrue(supplier.gstin_check)
		self.assertTrue(supplier.worked_with_vishwa_before)
		self.assertEqual(supplier.status, Supplier.Status.ACTIVE)
		self.assertIn('SRIKANTH PILLA', supplier.remarks)

	def test_admin_can_import_supplier_workbook(self):
		trade = Trade.objects.create(name='Electrical')
		category = MaterialCategory.objects.create(name='Electrical')
		material = Material.objects.create(name='Cable', category=category)
		brand = Brand.objects.create(name='Acme')
		project = Project.objects.create(code='P-001', name='Clinic Upgrade')
		workbook = Workbook()
		sheet = workbook.active
		sheet.title = 'Suppliers'
		sheet.append([
			'Vendor Code', 'Vendor / Firm Name', 'City', 'Overall Rating', 'Trade',
			'Material Category', 'Key Materials Supplied', 'Brands Dealt', 'Project(s) Worked On',
		])
		sheet.append([
			'SUP-003', 'Summit Hardware', 'Pune', 4.5, 'Electrical', 'Electrical',
			'Cable', 'Acme', 'P-001',
		])
		content = BytesIO()
		workbook.save(content)
		response = self.client.post(
			'/admin/suppliers/supplier/import/',
			{'file': SimpleUploadedFile('suppliers.xlsx', content.getvalue())},
		)
		self.assertRedirects(response, '/admin/suppliers/supplier/')
		supplier = Supplier.objects.get(vendor_code='SUP-003')
		self.assertEqual(supplier.name, 'Summit Hardware')
		self.assertEqual(supplier.city, 'Pune')
		self.assertEqual(supplier.overall_rating, 4.5)
		self.assertEqual(SupplierTrade.objects.get(supplier=supplier).trade, trade)
		self.assertEqual(SupplierMaterial.objects.get(supplier=supplier).material, material)
		self.assertEqual(SupplierBrand.objects.get(supplier=supplier).brand, brand)
		self.assertEqual(SupplierProject.objects.get(supplier=supplier).project, project)

	def test_invalid_workbook_data_is_rejected_without_importing_rows(self):
		response = self.client.post(
			'/admin/suppliers/supplier/import/',
			{'file': self.workbook_upload([
				['SUP-004', 'Valid Supplier', 'Pune', 4],
				['SUP-005', 'Invalid Supplier', 'Mumbai', 6],
			])},
		)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Row 3 (SUP-005 – Invalid Supplier), column “Overall Rating”')
		self.assertContains(response, 'outside the 0–5 rating scale')
		self.assertFalse(Supplier.objects.filter(vendor_code__in=['SUP-004', 'SUP-005']).exists())

	def test_import_creates_missing_master_data(self):
		workbook = Workbook()
		sheet = workbook.active
		sheet.title = 'Suppliers'
		sheet.append([
			'Vendor Code', 'Vendor / Firm Name', 'Trade', 'Material Category',
			'Key Materials Supplied', 'Supplier Type', 'Brands Dealt', 'Project(s) Worked On',
		])
		sheet.append(['SUP-010', 'New Traders', 'Civil, Plumbing', 'Cement', 'OPC 53, PPC', 'Dealer', 'UltraTech; ACC', 'Sreenidhi CR-2'])
		sheet.append(['SUP-011', 'Category Only', '', 'Steel', '', 'Distributor', '', ''])
		content = BytesIO()
		workbook.save(content)
		response = self.client.post('/admin/suppliers/supplier/import/', {'file': SimpleUploadedFile('s.xlsx', content.getvalue())})
		self.assertRedirects(response, '/admin/suppliers/supplier/')
		supplier = Supplier.objects.get(vendor_code='SUP-010')
		self.assertEqual(supplier.supplier_type, 'Dealer')
		self.assertEqual(sorted(link.trade.name for link in supplier.trade_links.all()), ['Civil', 'Plumbing'])
		self.assertEqual({(link.material.name, link.material.category.name) for link in supplier.material_links.all()}, {('OPC 53', 'Cement'), ('PPC', 'Cement')})
		self.assertEqual(sorted(link.brand.name for link in supplier.brand_links.all()), ['ACC', 'UltraTech'])
		self.assertEqual(supplier.project_links.get().project.name, 'Sreenidhi CR-2')
		other = Supplier.objects.get(vendor_code='SUP-011')
		self.assertEqual(other.material_category_links.get().category.name, 'Steel')
		profile = self.client.get(f'/suppliers/{supplier.pk}/')
		for text in ('Supply profile', 'Civil, Plumbing', 'Cement', 'OPC 53, PPC', 'Dealer', 'Sreenidhi CR-2'):
			self.assertContains(profile, text)

	def test_edit_form_shows_and_saves_linked_fields(self):
		supplier = Supplier.objects.create(vendor_code='SUP-020', name='Edit Me')
		response = self.client.post(f'/suppliers/{supplier.pk}/edit/', {
			'vendor_code': 'SUP-020', 'name': 'Edit Me', 'status': 'active', 'supplier_type': 'Manufacturer',
			'trades': 'Electrical', 'material_categories': 'Cables', 'materials': 'Armoured cable, Flexible wire',
			'brands': 'Polycab', 'projects': 'A S Rao Nagar',
		})
		self.assertRedirects(response, f'/suppliers/{supplier.pk}/')
		page = self.client.get(f'/suppliers/{supplier.pk}/edit/')
		self.assertContains(page, 'Key Materials Supplied')
		self.assertContains(page, 'Armoured cable, Flexible wire')
		self.assertContains(page, 'value="Polycab"')
		self.assertContains(page, 'value="A S Rao Nagar"')
		labels = [field.label for field in page.context['form']]
		self.assertEqual(labels[:8], ['Vendor Code', 'Vendor / Firm Name', 'Trade', 'Material Category', 'Key Materials Supplied', 'Supplier Type', 'Brands Dealt', 'Unit of Supply'])
		self.client.post(f'/suppliers/{supplier.pk}/edit/', {'vendor_code': 'SUP-020', 'name': 'Edit Me', 'status': 'active', 'trades': ''})
		self.assertFalse(supplier.trade_links.exists())


class GstinCheckTests(TestCase):
	def setUp(self):
		self.client.force_login(get_user_model().objects.create_superuser('gst', 'gst@example.com', 'pw'))

	def test_inspect_reads_state_pan_and_check_character(self):
		from scportal.gstin import inspect
		info = inspect(' 36bcnpp5410k1za ')
		self.assertEqual((info['status'], info['gstin'], info['state_code'], info['state'], info['pan']), ('ok', '36BCNPP5410K1ZA', '36', 'Telangana', 'BCNPP5410K'))
		typo = inspect('09AERPY3845G2Z0')
		self.assertEqual((typo['status'], typo['expected_check']), ('check_mismatch', 'O'))
		self.assertEqual(inspect('ABC')['status'], 'invalid_format')
		self.assertEqual(inspect('')['status'], 'empty')

	def test_form_tidies_gstin_and_rejects_bad_format(self):
		response = self.client.post('/suppliers/add/', {'vendor_code': 'SP0700', 'name': 'Tidy', 'status': 'active', 'gstin': '36bcnpp5410k1za', 'pan': 'bcnpp5410k'})
		supplier = Supplier.objects.get(vendor_code='SP0700')
		self.assertRedirects(response, f'/suppliers/{supplier.pk}/')
		self.assertEqual((supplier.gstin, supplier.pan), ('36BCNPP5410K1ZA', 'BCNPP5410K'))
		response = self.client.post('/suppliers/add/', {'vendor_code': 'SP0701', 'name': 'Bad', 'status': 'active', 'gstin': '36BCNPP5410'})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Not a valid GSTIN format')
		self.assertFalse(Supplier.objects.filter(vendor_code='SP0701').exists())

	def test_check_mismatch_is_saved_but_flagged_on_profile(self):
		self.client.post('/suppliers/add/', {'vendor_code': 'SP0702', 'name': 'Typo', 'status': 'active', 'gstin': '09AERPY3845G2Z0'})
		supplier = Supplier.objects.get(vendor_code='SP0702')
		page = self.client.get(f'/suppliers/{supplier.pk}/')
		self.assertContains(page, 'Check character mismatch')
		self.assertContains(page, 'data-gst-check="09AERPY3845G2Z0"')
		self.assertContains(page, 'https://services.gst.gov.in/services/searchtp')
		self.assertContains(page, 'js/gstin.js')

	def test_form_pages_load_gstin_helper(self):
		for url in ('/suppliers/add/', '/subcontractors/add/'):
			page = self.client.get(url)
			self.assertContains(page, 'id="gst-config"', msg_prefix=url)
			self.assertContains(page, '"36": "Telangana"', msg_prefix=url)


class AdminDeleteTests(TestCase):
	def setUp(self):
		from subcontractors.models import DirectSubcontractor
		from relationships.models import SupplierDirectSubcontractor

		self.admin = get_user_model().objects.create_superuser(username='boss', email='boss@example.com', password='pw')
		self.viewer = get_user_model().objects.create_user(username='viewer', password='pw')
		self.s1 = Supplier.objects.create(vendor_code='SUP-001', name='Northstar Steel')
		self.s2 = Supplier.objects.create(vendor_code='SUP-002', name='Riverbend Cement')
		self.s3 = Supplier.objects.create(vendor_code='SUP-003', name='Keep Me Traders')
		self.sub1 = DirectSubcontractor.objects.create(code='LC-001', name='Gang One')
		self.sub2 = DirectSubcontractor.objects.create(code='LC-002', name='Gang Two')
		SupplierDirectSubcontractor.objects.create(supplier=self.s3, subcontractor=self.sub1)
		self.Sub = DirectSubcontractor

	def test_admin_deletes_multiple_suppliers(self):
		self.client.force_login(self.admin)
		response = self.client.post('/suppliers/delete/', {'ids': [self.s1.pk, self.s2.pk], 'next': '/suppliers/?q=x'})
		self.assertRedirects(response, '/suppliers/?q=x', fetch_redirect_response=False)
		self.assertEqual(list(Supplier.objects.values_list('vendor_code', flat=True)), ['SUP-003'])

	def test_admin_list_shows_checkboxes_viewer_does_not(self):
		self.client.force_login(self.admin)
		self.assertContains(self.client.get('/suppliers/'), 'name="ids"', count=3)
		self.client.force_login(self.viewer)
		self.assertNotContains(self.client.get('/suppliers/'), 'name="ids"')
		self.assertNotContains(self.client.get(f'/suppliers/{self.s1.pk}/'), 'Delete supplier')

	def test_viewer_cannot_delete(self):
		self.client.force_login(self.viewer)
		self.client.post('/suppliers/delete/', {'ids': [self.s1.pk]})
		self.client.post('/subcontractors/delete/', {'ids': [self.sub2.pk]})
		self.assertEqual(Supplier.objects.count(), 3)
		self.assertEqual(self.Sub.objects.count(), 2)

	def test_get_is_rejected(self):
		self.client.force_login(self.admin)
		self.assertEqual(self.client.get('/suppliers/delete/').status_code, 405)

	def test_nothing_selected_shows_error(self):
		self.client.force_login(self.admin)
		response = self.client.post('/suppliers/delete/', {}, follow=True)
		self.assertContains(response, 'Select at least one supplier')
		self.assertEqual(Supplier.objects.count(), 3)

	def test_admin_deletes_linked_subcontractor(self):
		self.client.force_login(self.admin)
		response = self.client.post('/subcontractors/delete/', {'ids': [self.sub1.pk, self.sub2.pk]})
		self.assertRedirects(response, '/subcontractors/', fetch_redirect_response=False)
		self.assertEqual(self.Sub.objects.count(), 0)
		self.assertTrue(Supplier.objects.filter(pk=self.s3.pk).exists())

	def test_external_next_url_is_ignored(self):
		self.client.force_login(self.admin)
		response = self.client.post('/suppliers/delete/', {'ids': [self.s1.pk], 'next': 'https://evil.example/'})
		self.assertRedirects(response, '/suppliers/', fetch_redirect_response=False)

	def test_admin_profile_pages_show_delete_button(self):
		self.client.force_login(self.admin)
		response = self.client.get(f'/suppliers/{self.s1.pk}/')
		self.assertContains(response, 'Delete supplier')
		self.assertContains(response, 'js/bulk-actions.js')
		response = self.client.get(f'/subcontractors/{self.sub1.pk}/')
		self.assertContains(response, 'Delete subcontractor')
		self.assertContains(self.client.get('/subcontractors/'), 'name="ids"', count=2)


class UploadMessageTests(TestCase):
	"""Cells that used to fail with Django's internal messages, e.g. '“” value must be a decimal number'."""

	HEADERS = ['Vendor Code', 'Vendor / Firm Name', 'Quality (1-5)', 'Overall Rating', 'Last Reviewed On', 'Status', 'Email']

	def setUp(self):
		self.client.force_login(get_user_model().objects.create_superuser(username='boss', email='b@example.com', password='pw'))

	def upload(self, *rows):
		workbook = Workbook()
		sheet = workbook.active
		sheet.title = 'Suppliers'
		sheet.append(self.HEADERS)
		for row in rows:
			sheet.append(row)
		output = BytesIO()
		workbook.save(output)
		return self.client.post('/suppliers/upload/', {'file': SimpleUploadedFile('s.xlsx', output.getvalue())})

	def test_blank_looking_and_na_cells_are_treated_as_empty(self):
		response = self.upload(
			['SP1', 'Blank Rating', ' ', '', '', '', ''],
			['SP2', 'NA Rating', 'NA', '-', 'N/A', '', ''],
		)
		self.assertRedirects(response, '/suppliers/', fetch_redirect_response=False)
		supplier = Supplier.objects.get(vendor_code='SP1')
		self.assertIsNone(supplier.overall_rating)
		self.assertEqual(supplier.status, 'active')
		self.assertIsNone(Supplier.objects.get(vendor_code='SP2').quality_rating)

	def test_common_excel_formats_are_accepted(self):
		response = self.upload(['SP3', 'Formats', '4,5', 4.3333, '17/11/2026', 'on hold', ''])
		self.assertRedirects(response, '/suppliers/', fetch_redirect_response=False)
		supplier = Supplier.objects.get(vendor_code='SP3')
		self.assertEqual(str(supplier.quality_rating), '4.50')
		self.assertEqual(str(supplier.overall_rating), '4.33')
		self.assertEqual(supplier.last_reviewed_on.isoformat(), '2026-11-17')
		self.assertEqual(supplier.status, 'on_hold')

	def test_problems_name_row_vendor_column_and_fix(self):
		Supplier.objects.create(vendor_code='SP9', name='Already Here')
		response = self.upload(
			['SP4', 'Bad Cells', 'good', 9, 'someday', 'Maybe', 'not-an-email'],
			['SP9', 'Already Here', '', '', '', '', ''],
			['SP4', 'Copy', '', '', '', '', ''],
			['', 'No Code', '', '', '', '', ''],
		)
		self.assertEqual(Supplier.objects.count(), 1)
		content = response.content.decode()
		self.assertNotIn('__all__', content)
		self.assertNotIn('value must be a decimal number', content)
		for text in (
			'Nothing was imported. Found 8 problems in 4 rows.',
			'SP4 – Bad Cells', 'Quality (1-5)', '“good” is not a number.',
			'“9” is outside the 0–5 rating scale.',
			'“someday” is not a date. Use YYYY-MM-DD',
			'“Maybe” is not a status the portal knows. Use one of: Active, On hold, Inactive.',
			'“not-an-email” is not a valid email address',
			'“SP9” is already in the portal.',
			'Vendor code “SP4” is used again — it already appears on row 2 of this sheet.',
			'This cell is empty, but the column is required.',
		):
			self.assertIn(text, content)

	def test_unknown_and_missing_columns_are_explained(self):
		self.HEADERS = ['Vendor Code', 'Firm', 'Colour']
		response = self.upload(['SP5', 'X', 'Red'])
		self.assertContains(response, 'column(s) the portal does not recognise: “Firm”, “Colour”')

	def test_supplier_upload_accepts_several_emails(self):
		self.HEADERS = ['Vendor Code', 'Vendor / Firm Name', 'Email']
		response = self.upload(['SP6', 'Multi Mail', 'sales@abc.com; accounts@abc.com;purchase@abc.com'])
		self.assertRedirects(response, '/suppliers/', fetch_redirect_response=False)
		supplier = Supplier.objects.get(vendor_code='SP6')
		self.assertEqual(supplier.email_list, ['sales@abc.com', 'accounts@abc.com', 'purchase@abc.com'])
		self.assertContains(self.client.get(f'/suppliers/{supplier.pk}/'), 'href="mailto:purchase@abc.com"')
