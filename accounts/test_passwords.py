from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import AccountSettings

OLD = 'Old-pass-2026'
NEW = 'Fresh-Steel-77'


class OwnPasswordChangeTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username='ravi', password=OLD)
		self.client.login(username='ravi', password=OLD)

	def test_change_needs_the_current_password(self):
		response = self.client.post('/accounts/password/', {'old_password': 'wrong', 'new_password1': NEW, 'new_password2': NEW})
		self.assertContains(response, 'Your old password was entered incorrectly')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password(OLD))

	def test_change_works_and_keeps_this_session_signed_in(self):
		other_device = Client()
		other_device.login(username='ravi', password=OLD)
		response = self.client.post('/accounts/password/', {'old_password': OLD, 'new_password1': NEW, 'new_password2': NEW}, follow=True)
		self.assertContains(response, 'Your password was changed.')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password(NEW))
		self.assertEqual(self.client.get('/suppliers/').status_code, 200)
		self.assertEqual(other_device.get('/suppliers/').status_code, 302)  # other sessions are signed out

	def test_weak_or_mismatched_passwords_are_rejected(self):
		response = self.client.post('/accounts/password/', {'old_password': OLD, 'new_password1': '12345678', 'new_password2': '12345678'})
		self.assertContains(response, 'too common')
		response = self.client.post('/accounts/password/', {'old_password': OLD, 'new_password1': NEW, 'new_password2': NEW + 'x'})
		self.assertContains(response, 'didn’t match')

	def test_username_in_top_bar_links_to_change_page(self):
		self.assertContains(self.client.get('/'), 'href="/accounts/password/"')


class AdminResetTests(TestCase):
	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(username='boss', email='b@example.com', password=OLD)
		self.user = get_user_model().objects.create_user(username='ravi', password=OLD)
		self.client.force_login(self.admin)

	def test_admin_sets_password_without_old_one(self):
		response = self.client.post(f'/accounts/users/{self.user.pk}/password/', {'new_password1': NEW, 'new_password2': NEW})
		self.assertContains(response, 'Password reset for ravi')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password(NEW))
		settings_row = AccountSettings.objects.get(user=self.user)
		self.assertFalse(settings_row.must_change_password)
		self.assertEqual(settings_row.password_changed_by, self.admin)

	def test_generated_password_is_shown_once_and_works(self):
		response = self.client.post(f'/accounts/users/{self.user.pk}/password/', {'generate': 'on', 'must_change': 'on'})
		temp = response.context['generated']
		self.assertEqual(len(temp), 12)
		self.assertContains(response, temp)
		self.assertIn('no-cache', response['Cache-Control'])
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password(temp))

	def test_user_must_choose_own_password_after_reset(self):
		user_device = Client()
		user_device.login(username='ravi', password=OLD)
		self.client.post(f'/accounts/users/{self.user.pk}/password/', {'new_password1': NEW, 'new_password2': NEW, 'must_change': 'on'})
		self.assertEqual(user_device.get('/suppliers/').status_code, 302)  # signed out by the reset
		self.assertTrue(user_device.login(username='ravi', password=NEW))
		response = user_device.get('/suppliers/')
		self.assertRedirects(response, '/accounts/password/')
		self.assertContains(user_device.get('/accounts/password/'), 'An administrator reset your password')
		user_device.post('/accounts/password/', {'old_password': NEW, 'new_password1': 'Own-Choice-2027', 'new_password2': 'Own-Choice-2027'})
		self.assertEqual(user_device.get('/suppliers/').status_code, 200)
		self.assertFalse(AccountSettings.objects.get(user=self.user).must_change_password)

	def test_reset_form_errors_are_clear(self):
		url = f'/accounts/users/{self.user.pk}/password/'
		self.assertContains(self.client.post(url, {}), 'Type a new password, or tick')
		self.assertContains(self.client.post(url, {'new_password1': NEW}), 'Type the new password again')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password(OLD))

	def test_admin_can_reset_another_admin_but_not_bypass_own_old_password(self):
		other_admin = get_user_model().objects.create_superuser(username='boss2', email='c@example.com', password=OLD)
		self.client.post(f'/accounts/users/{other_admin.pk}/password/', {'new_password1': NEW, 'new_password2': NEW})
		other_admin.refresh_from_db()
		self.assertTrue(other_admin.check_password(NEW))
		self.assertRedirects(self.client.get(f'/accounts/users/{self.admin.pk}/password/'), '/accounts/password/')

	def test_users_page_links_and_non_admin_blocked(self):
		page = self.client.get('/accounts/users/')
		self.assertContains(page, f'/accounts/users/{self.user.pk}/password/')
		self.assertContains(page, 'Change my password')
		self.client.force_login(self.user)
		self.client.post(f'/accounts/users/{self.admin.pk}/password/', {'new_password1': NEW, 'new_password2': NEW})
		self.admin.refresh_from_db()
		self.assertTrue(self.admin.check_password(OLD))


class UserEmailTests(TestCase):
	def setUp(self):
		self.admin = get_user_model().objects.create_superuser(username='boss', email='', password=OLD)
		self.user = get_user_model().objects.create_user(username='ravi', password=OLD)
		self.client.force_login(self.admin)

	def test_admin_sets_and_validates_emails(self):
		self.client.post('/accounts/users/', {'action': 'set_email', 'user_id': self.admin.pk, 'email': 'boss@vishwa.test'})
		self.admin.refresh_from_db()
		self.assertEqual(self.admin.email, 'boss@vishwa.test')
		response = self.client.post('/accounts/users/', {'action': 'set_email', 'user_id': self.user.pk, 'email': 'not-mail'}, follow=True)
		self.assertContains(response, 'is not a valid email address')
		self.client.force_login(self.user)
		self.client.post('/accounts/users/', {'action': 'set_email', 'user_id': self.user.pk, 'email': 'x@y.test'})
		self.user.refresh_from_db()
		self.assertEqual(self.user.email, '')
