"""Excel-style column filters on the lists, and exports that follow searches and filters."""
import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook

from materials.models import Trade
from relationships.models import DirectSubcontractorTrade
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier


def sheet_codes(response, sheet=None):
	workbook = load_workbook(BytesIO(response.content))
	ws = workbook[sheet] if sheet else workbook.active
	return sorted(row[1] for row in ws.iter_rows(min_row=2, values_only=True))


class ColumnFilterTests(TestCase):
	def setUp(self):
		self.client.force_login(get_user_model().objects.create_user(username='viewer', password='pw'))
		Supplier.objects.create(vendor_code='S1', name='Alpha', supplier_type='Dealer', city='Pune', overall_rating='4.50')
		Supplier.objects.create(vendor_code='S2', name='Beta', supplier_type='Dealer', city='Hyderabad', overall_rating='3.00', status='on_hold')
		Supplier.objects.create(vendor_code='S3', name='Gamma', supplier_type='Manufacturer', city='Hyderabad')
		Supplier.objects.create(vendor_code='S4', name='Delta', supplier_type='', city='')

	def menus(self, response):
		return json.loads(response.content.decode().split('<script id="column-menus" type="application/json">')[1].split('</script>')[0])

	def test_heading_menus_list_values_with_counts_and_blanks(self):
		menus = self.menus(self.client.get('/suppliers/'))
		types = {item['l']: item['n'] for item in menus['type']['values']}
		self.assertEqual(types, {'Dealer': 2, 'Manufacturer': 1, '(Blanks)': 1})
		self.assertEqual([item['l'] for item in menus['status']['values']], ['Active', 'On hold'])
		self.assertEqual([item['l'] for item in menus['rating']['values']], ['3', '4.5', '(Blanks)'])

	def test_filter_one_column_with_several_values_and_blanks(self):
		response = self.client.get('/suppliers/', {'f_location': ['Pune', '__blank__']})
		self.assertContains(response, 'Alpha')
		self.assertContains(response, 'Delta')
		self.assertNotContains(response, 'Gamma')
		self.assertContains(response, 'col-head filtered')

	def test_filters_combine_and_other_menus_narrow_like_excel(self):
		response = self.client.get('/suppliers/', {'f_type': 'Dealer', 'f_location': 'Hyderabad'})
		self.assertContains(response, 'Beta')
		self.assertNotContains(response, 'Alpha')
		menus = self.menus(response)
		# The Location menu shows values from rows left by the Type filter, as Excel does.
		self.assertEqual([item['l'] for item in menus['location']['values']], ['Hyderabad', 'Pune'])
		self.assertEqual([item['on'] for item in menus['location']['values']], [True, False])

	def test_sort_and_export_follow_column_filters_and_search(self):
		response = self.client.get('/suppliers/', {'sort': '-rating'})
		content = response.content.decode()
		self.assertLess(content.index('Alpha'), content.index('Beta'))
		export = self.client.get('/suppliers/export.xlsx', {'f_type': 'Dealer', 'q': 'a'})
		self.assertEqual(sheet_codes(export), ['S1', 'S2'])
		export = self.client.get('/suppliers/export.xlsx', {'f_status': 'on_hold'})
		self.assertEqual(sheet_codes(export), ['S2'])

	def test_profile_and_trade_columns_filter(self):
		sub = DirectSubcontractor.objects.create(code='L1', name='Execution Gang', service_type='Labour', scope_of_work='Execution of pipelines')
		DirectSubcontractor.objects.create(code='L2', name='Painters', service_type='Composite')
		DirectSubcontractorTrade.objects.create(subcontractor=sub, trade=Trade.objects.create(name='Civil'))
		response = self.client.get('/subcontractors/', {'f_trade': 'Civil'})
		self.assertContains(response, 'Execution Gang')
		self.assertNotContains(response, 'Painters')
		self.assertEqual(sheet_codes(self.client.get('/subcontractors/export.xlsx', {'f_profile': 'low'})), ['L1', 'L2'])
		self.assertEqual(sheet_codes(self.client.get('/subcontractors/export.xlsx', {'q': 'execution'})), ['L1'])

	def test_search_page_export_has_both_directories(self):
		DirectSubcontractor.objects.create(code='L5', name='Hyderabad Gang', city='Hyderabad')
		page = self.client.get('/search/', {'q': 'Hyderabad'})
		self.assertContains(page, 'Export results to Excel')
		response = self.client.get('/search/export.xlsx', {'q': 'Hyderabad'})
		self.assertIn('filename="search_hyderabad_', response['Content-Disposition'])
		self.assertEqual(sheet_codes(response, 'Suppliers'), ['S2', 'S3'])
		self.assertEqual(sheet_codes(response, 'Labour & Composite'), ['L5'])

	def test_pages_still_need_sign_in(self):
		self.client.logout()
		for url in ('/search/?q=a', '/search/export.xlsx?q=a', '/suppliers/export.xlsx'):
			self.assertEqual(self.client.get(url).status_code, 302, url)
