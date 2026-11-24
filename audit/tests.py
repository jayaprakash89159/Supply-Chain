import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook

from documents.models import VendorDocument
from relationships.models import SupplierDirectSubcontractor
from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import AuditEntry

MEDIA = tempfile.mkdtemp(prefix='audit-test-media-')


@override_settings(MEDIA_ROOT=MEDIA)
class AuditAndRecycleBinTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(username='boss', email='b@vishwa.test', password='pw')
		self.viewer = get_user_model().objects.create_user(username='viewer', password='pw')
		self.client.force_login(self.admin)
		self.client.post('/suppliers/add/', {'vendor_code': 'S1', 'name': 'Alpha Steel', 'status': 'active', 'city': 'Pune'})
		self.supplier = Supplier.objects.get(vendor_code='S1')

	def test_create_and_edit_are_recorded_with_old_and_new_values(self):
		self.client.post(f'/suppliers/{self.supplier.pk}/edit/', {'vendor_code': 'S1', 'name': 'Alpha Steel', 'status': 'on_hold', 'city': 'Hyderabad'})
		created, edited = AuditEntry.objects.order_by('pk')
		self.assertEqual((created.action, created.user, created.object_label), ('created', self.admin, 'S1 – Alpha Steel'))
		self.assertEqual(edited.action, 'updated')
		self.assertIn({'field': 'City', 'old': 'Pune', 'new': 'Hyderabad'}, edited.changes)
		self.assertIn({'field': 'Status', 'old': 'Active', 'new': 'On hold'}, edited.changes)
		profile = self.client.get(f'/suppliers/{self.supplier.pk}/')
		self.assertContains(profile, 'Pune <b aria-label="changed to">→</b> Hyderabad')

	def test_bulk_status_and_documents_are_recorded(self):
		self.client.post('/suppliers/set-status/', {'ids': [self.supplier.pk], 'status': 'inactive'})
		self.client.post(f'/documents/upload/supplier/{self.supplier.pk}/', {
			'doc_type': 'pan', 'number': 'ABCPK1234F', 'file': SimpleUploadedFile('pan.pdf', b'%PDF', content_type='application/pdf'),
		})
		document = VendorDocument.objects.get()
		self.client.post(f'/documents/{document.pk}/delete/')
		actions = list(AuditEntry.objects.filter(object_id=self.supplier.pk).order_by('pk').values_list('action', 'note'))
		self.assertEqual(actions[1:], [
			('status', 'Bulk status change'), ('document_added', 'PAN card ABCPK1234F'), ('document_removed', 'PAN card ABCPK1234F'),
		])

	def test_delete_moves_to_bin_and_restore_brings_it_back(self):
		moved = self.client.post('/suppliers/delete/', {'ids': [self.supplier.pk]}, follow=True)
		self.assertContains(moved, 'to the recycle bin: S1')
		self.assertEqual(self.client.get(f'/suppliers/{self.supplier.pk}/').status_code, 404)
		self.assertNotContains(self.client.get('/suppliers/'), 'Alpha Steel')
		bin_page = self.client.get('/admin-tools/recycle-bin/')
		self.assertContains(bin_page, 'Alpha Steel')
		self.assertContains(bin_page, 'boss')
		self.client.post('/admin-tools/recycle-bin/restore/', {'items': [f'supplier:{self.supplier.pk}']})
		self.assertEqual(self.client.get(f'/suppliers/{self.supplier.pk}/').status_code, 200)
		self.assertEqual(
			list(AuditEntry.objects.filter(action__in=['deleted', 'restored']).values_list('action', flat=True).order_by('pk')),
			['deleted', 'restored'],
		)

	def test_permanent_delete_removes_record_documents_and_links_but_keeps_history(self):
		gang = DirectSubcontractor.objects.create(code='L1', name='Execution Gang')
		SupplierDirectSubcontractor.objects.create(supplier=self.supplier, subcontractor=gang)
		document = VendorDocument.objects.create(kind='subcontractor', vendor_id=gang.pk, doc_type='pan', file='documents/x.pdf')
		self.client.post('/subcontractors/delete/', {'ids': [gang.pk]})
		response = self.client.post('/admin-tools/recycle-bin/purge/', {'items': [f'subcontractor:{gang.pk}']}, follow=True)
		self.assertContains(response, 'Permanently deleted 1: Execution Gang')
		self.assertFalse(DirectSubcontractor.objects.filter(pk=gang.pk).exists())
		self.assertFalse(VendorDocument.objects.filter(pk=document.pk).exists())
		self.assertTrue(Supplier.objects.filter(pk=self.supplier.pk).exists())
		activity = self.client.get('/admin-tools/activity/', {'q': 'Execution'})
		self.assertContains(activity, 'Deleted permanently')
		self.assertContains(activity, 'L1 – Execution Gang')

	def test_upload_explains_code_in_recycle_bin(self):
		self.client.post('/suppliers/delete/', {'ids': [self.supplier.pk]})
		workbook = Workbook()
		sheet = workbook.active
		sheet.title = 'Suppliers'
		sheet.append(['Vendor Code', 'Vendor / Firm Name'])
		sheet.append(['S1', 'Alpha Steel again'])
		output = BytesIO()
		workbook.save(output)
		response = self.client.post('/suppliers/upload/', {'file': SimpleUploadedFile('s.xlsx', output.getvalue())})
		self.assertContains(response, 'is in the Recycle bin (it was deleted)')

	def test_activity_filters_and_admin_only(self):
		Supplier.objects.create(vendor_code='S2', name='Beta Cement')
		page = self.client.get('/admin-tools/activity/', {'q': 'Beta'})
		self.assertEqual(page.context['page'].paginator.count, 1)
		self.client.force_login(self.viewer)
		self.assertEqual(self.client.get('/admin-tools/activity/').status_code, 302)
		self.assertEqual(self.client.get('/admin-tools/recycle-bin/').status_code, 302)
		self.client.post('/admin-tools/recycle-bin/purge/', {'items': [f'supplier:{self.supplier.pk}']})
		self.assertTrue(Supplier.objects.filter(pk=self.supplier.pk).exists())
