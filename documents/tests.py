import datetime
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import VendorDocument

MEDIA = tempfile.mkdtemp(prefix='document-test-media-')


def pdf(name='doc.pdf'):
	return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')


def days(n):
	return timezone.localdate() + datetime.timedelta(days=n)


@override_settings(MEDIA_ROOT=MEDIA)
class DocumentVaultTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(username='boss', email='boss@vishwa.test', password='pw')
		self.viewer = get_user_model().objects.create_user(username='viewer', password='pw')
		self.supplier = Supplier.objects.create(vendor_code='S1', name='Alpha Steel')
		self.gang = DirectSubcontractor.objects.create(code='L1', name='Execution Gang')
		self.client.force_login(self.admin)

	def upload(self, kind, vendor, **data):
		data.setdefault('file', pdf())
		return self.client.post(f'/documents/upload/{kind}/{vendor.pk}/', data, follow=True)

	def add(self, vendor, kind, doc_type, expires=None, uploaded=None):
		document = VendorDocument.objects.create(kind=kind, vendor_id=vendor.pk, doc_type=doc_type, expires_on=expires, file='documents/x.pdf')
		if uploaded:
			VendorDocument.objects.filter(pk=document.pk).update(uploaded_at=uploaded)
		return document

	def test_admin_uploads_and_profile_shows_status_and_missing(self):
		response = self.upload('subcontractor', self.gang, doc_type='labour_licence', number='LL/1', expires_on=days(10).isoformat())
		self.assertContains(response, 'Labour licence uploaded for Execution Gang')
		self.assertContains(response, 'Expires in 10 days')
		self.assertContains(response, 'Missing: PAN card, Cancelled cheque / bank letter, Workmen compensation insurance')
		document = VendorDocument.objects.get()
		self.assertEqual(document.uploaded_by, self.admin)

	def test_expiry_date_required_for_licences_and_file_types_checked(self):
		response = self.upload('subcontractor', self.gang, doc_type='wc_insurance')
		self.assertContains(response, 'has a validity period: enter the “Valid until” date')
		response = self.upload('supplier', self.supplier, doc_type='gst', file=SimpleUploadedFile('a.exe', b'MZ'))
		self.assertContains(response, 'Upload a PDF or a photo')
		response = self.upload('supplier', self.supplier, doc_type='gst', issued_on=days(5).isoformat(), expires_on=days(1).isoformat())
		self.assertContains(response, 'cannot be before')
		self.assertFalse(VendorDocument.objects.exists())

	def test_viewer_can_view_and_download_but_not_upload_or_delete(self):
		document = self.add(self.supplier, 'supplier', 'gst')
		document.file.save('gst.pdf', pdf(), save=True)
		self.client.force_login(self.viewer)
		page = self.client.get(f'/suppliers/{self.supplier.pk}/')
		self.assertContains(page, 'GST registration certificate')
		self.assertNotContains(page, 'Upload document')
		self.assertEqual(self.client.get(f'/documents/{document.pk}/file/').status_code, 200)
		self.upload('supplier', self.supplier, doc_type='pan')
		self.client.post(f'/documents/{document.pk}/delete/')
		self.assertEqual(VendorDocument.objects.count(), 1)
		self.client.logout()
		self.assertEqual(self.client.get(f'/documents/{document.pk}/file/').status_code, 302)

	def test_expiring_page_dashboard_and_badge(self):
		self.add(self.gang, 'subcontractor', 'labour_licence', days(-3))
		self.add(self.supplier, 'supplier', 'iso', days(20))
		self.add(self.supplier, 'supplier', 'trade_licence', days(200))
		page = self.client.get('/documents/')
		self.assertContains(page, 'Expired 3 days ago')
		self.assertContains(page, 'Expires in 20 days')
		self.assertNotContains(page, 'Trade licence</a>')
		self.assertEqual(len(self.client.get('/documents/', {'within': 'expired'}).context['documents']), 1)
		dashboard = self.client.get('/')
		self.assertEqual((dashboard.context['documents_expired'], dashboard.context['documents_expiring']), (1, 1))
		self.assertContains(dashboard, 'class="nav-badge"')

	def test_renewed_document_stops_alerting(self):
		old = self.add(self.gang, 'subcontractor', 'wc_insurance', days(-5), uploaded=timezone.now() - datetime.timedelta(days=300))
		self.assertEqual(len(self.client.get('/documents/').context['documents']), 1)
		self.add(self.gang, 'subcontractor', 'wc_insurance', days(360))
		self.assertEqual(len(self.client.get('/documents/').context['documents']), 0)
		profile = self.client.get(f'/subcontractors/{self.gang.pk}/')
		self.assertContains(profile, '1 older version')
		self.assertNotIn(old, profile.context['documents'])

	def test_deleted_vendors_are_left_out(self):
		self.add(self.gang, 'subcontractor', 'labour_licence', days(-1))
		DirectSubcontractor.objects.filter(pk=self.gang.pk).update(archived_at=timezone.now())
		self.assertEqual(len(self.client.get('/documents/').context['documents']), 0)

	def test_alert_email_command(self):
		call_command('send_document_alerts')  # nothing to report
		self.assertEqual(len(mail.outbox), 0)
		self.add(self.gang, 'subcontractor', 'labour_licence', days(-2))
		call_command('send_document_alerts')
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ['boss@vishwa.test'])
		self.assertIn('1 expired', mail.outbox[0].subject)
		self.assertIn('Execution Gang (Labour & Composite): Labour licence – Expired 2 days ago', mail.outbox[0].body)

	def test_admin_deletes_document(self):
		document = self.add(self.supplier, 'supplier', 'pan')
		response = self.client.post(f'/documents/{document.pk}/delete/', follow=True)
		self.assertContains(response, 'PAN card deleted.')
		self.assertFalse(VendorDocument.objects.exists())
