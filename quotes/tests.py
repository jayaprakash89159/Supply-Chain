import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from subcontractors.models import DirectSubcontractor
from suppliers.models import Supplier

from .models import QuoteRecipient, QuoteRequest

MEDIA = tempfile.mkdtemp(prefix='quote-test-media-')
BODY = 'Dear {contact_person},\n\nPlease quote for:\n{requirement}\n\nRegards,\n{your_name}'


@override_settings(DEFAULT_FROM_EMAIL='VISHWA Purchase <purchase@vishwa.test>', MEDIA_ROOT=MEDIA)
class QuoteRequestTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='buyer', password='pw', email='buyer@vishwa.test', first_name='Kiran', last_name='Rao',
		)
		self.client.force_login(self.user)
		self.steel1 = Supplier.objects.create(vendor_code='ST1', name='Alpha Steel', contact_person='Ravi', email='sales@alpha.in; accounts@alpha.in')
		self.steel2 = Supplier.objects.create(vendor_code='ST2', name='Beta Steel', email='beta@steel.in')
		self.no_mail = Supplier.objects.create(vendor_code='ST3', name='Gamma Steel')
		self.gang = DirectSubcontractor.objects.create(code='LC1', name='Execution Gang', contact_person='Mohan', email='gang@work.in')

	def send(self, **extra):
		data = {
			'step': 'send', 'subject': 'RFQ steel – {vendor_name}', 'body': BODY,
			'requirement': 'TMT 12 mm – 25 MT', 'vendors': [f'supplier:{self.steel1.pk}', f'supplier:{self.steel2.pk}', f'supplier:{self.no_mail.pk}'],
		}
		data.update(extra)
		return self.client.post('/quotes/new/', data)

	def test_list_selection_opens_compose_page(self):
		response = self.client.post('/quotes/new/', {'step': 'select', 'kind': 'supplier', 'ids': [self.steel1.pk, self.no_mail.pk]})
		self.assertContains(response, 'Alpha Steel')
		self.assertContains(response, 'No email on record')
		self.assertContains(response, 'sales@alpha.in; accounts@alpha.in')
		self.assertContains(response, '{requirement}')

	def test_each_vendor_gets_its_own_email_without_cc_or_bcc(self):
		response = self.send()
		quote = QuoteRequest.objects.get()
		self.assertRedirects(response, f'/quotes/{quote.pk}/', fetch_redirect_response=False)
		self.assertEqual(len(mail.outbox), 2)
		first, second = mail.outbox
		self.assertEqual(first.to, ['sales@alpha.in', 'accounts@alpha.in'])
		self.assertEqual(second.to, ['beta@steel.in'])
		for message in mail.outbox:
			self.assertEqual(message.cc, [])
			self.assertEqual(message.bcc, [])
			self.assertEqual(message.reply_to, ['buyer@vishwa.test'])
			self.assertEqual(message.from_email, 'VISHWA Purchase <purchase@vishwa.test>')
		self.assertEqual(first.subject, 'RFQ steel – Alpha Steel')
		self.assertIn('Dear Ravi,', first.body)
		self.assertIn('TMT 12 mm – 25 MT', first.body)
		self.assertIn('Kiran Rao', first.body)
		self.assertIn('Dear Sir/Madam,', second.body)
		statuses = dict(QuoteRecipient.objects.values_list('vendor_code', 'status'))
		self.assertEqual(statuses, {'ST1': 'sent', 'ST2': 'sent', 'ST3': 'skipped'})
		page = self.client.get(f'/quotes/{quote.pk}/')
		self.assertContains(page, 'Skipped (no email)')

	def test_mixed_suppliers_and_subcontractors_from_search_with_attachment(self):
		attachment = SimpleUploadedFile('BOQ.pdf', b'%PDF-1.4 test', content_type='application/pdf')
		self.send(vendors=[f'subcontractor:{self.gang.pk}', f'supplier:{self.steel2.pk}'], attachment=attachment)
		self.assertEqual([message.to for message in mail.outbox], [['gang@work.in'], ['beta@steel.in']])
		self.assertIn('Dear Mohan,', mail.outbox[0].body)
		for message in mail.outbox:
			self.assertEqual(message.attachments[0][0], 'BOQ.pdf')

	def test_test_email_goes_only_to_the_sender(self):
		self.send(step='test')
		self.assertEqual(len(mail.outbox), 1)
		self.assertEqual(mail.outbox[0].to, ['buyer@vishwa.test'])
		self.assertIn('Dear Ravi,', mail.outbox[0].body)
		self.assertFalse(QuoteRequest.objects.exists())

	def test_unknown_placeholder_and_missing_requirement_slot_are_explained(self):
		response = self.send(body='Hello {vendor} {requirement}')
		self.assertContains(response, 'Unknown placeholder(s): {vendor}')
		response = self.send(body='Hello {vendor_name}')
		self.assertContains(response, 'Put {requirement} in the message')
		self.assertEqual(len(mail.outbox), 0)

	@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='')
	def test_sending_is_blocked_until_email_is_configured(self):
		response = self.send()
		self.assertContains(response, 'Email sending is not set up')
		self.assertEqual(len(mail.outbox), 0)
		self.assertFalse(QuoteRequest.objects.exists())

	def test_history_shows_own_requests_only(self):
		self.send()
		other = get_user_model().objects.create_user(username='other', password='pw')
		self.client.force_login(other)
		self.assertNotContains(self.client.get('/quotes/'), 'RFQ steel')
		self.assertEqual(self.client.get(f'/quotes/{QuoteRequest.objects.get().pk}/').status_code, 404)

	def test_requires_sign_in_and_post(self):
		self.assertEqual(self.client.get('/quotes/new/').status_code, 405)
		self.client.logout()
		self.assertEqual(self.client.post('/quotes/new/', {'step': 'select'}).status_code, 302)

	def test_search_page_has_selection(self):
		response = self.client.get('/search/', {'q': 'Steel'})
		self.assertContains(response, f'value="supplier:{self.steel1.pk}"')
		self.assertContains(response, 'Request quotes')


class MailErrorMessageTests(TestCase):
	@override_settings(EMAIL_HOST='smtp.gmail.com', EMAIL_HOST_USER='buyer@gmail.test')
	def test_gmail_login_refusal_is_explained(self):
		import smtplib
		from .mailer import explain_mail_error
		message = explain_mail_error(smtplib.SMTPServerDisconnected('Connection unexpectedly closed'))
		self.assertIn('refused to sign in to buyer@gmail.test', message)
		self.assertIn('app password', message)
		self.assertIn('Could not reach', explain_mail_error(TimeoutError('timed out')))
