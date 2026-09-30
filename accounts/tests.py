from django.contrib.auth import get_user_model
from django.test import TestCase


class AccountAccessTests(TestCase):
	def test_login_page_is_available(self):
		response = self.client.get('/accounts/login/')
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Sign in')

	def test_dashboard_requires_login(self):
		response = self.client.get('/')
		self.assertRedirects(response, '/accounts/login/?next=/')

	def test_normal_user_cannot_manage_accounts(self):
		user = get_user_model().objects.create_user(username='viewer', password='test-password')
		self.client.force_login(user)
		response = self.client.get('/accounts/users/')
		self.assertEqual(response.status_code, 302)
		self.assertTrue(response.url.startswith('/accounts/login/'))

	def test_health_endpoint_does_not_require_login(self):
		response = self.client.get('/health/')
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'status': 'ok'})


class UserAccessManagementTests(TestCase):
	def setUp(self):
		self.admin = get_user_model().objects.create_superuser('boss', 'boss@example.com', 'pw')
		self.client.force_login(self.admin)

	def _create(self, username, access):
		return self.client.post('/accounts/users/', {
			'action': 'create', 'username': username, 'access': access,
			'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
		})

	def test_read_only_user_can_view_but_not_upload(self):
		self._create('viewer', 'read_only')
		user = get_user_model().objects.get(username='viewer')
		self.assertFalse(user.is_superuser or user.is_staff)
		self.client.force_login(user)
		response = self.client.get('/suppliers/')
		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, 'Upload suppliers')
		self.assertEqual(self.client.get('/suppliers/upload/').status_code, 302)
		self.assertEqual(self.client.get('/accounts/users/').status_code, 302)

	def test_admin_user_can_upload_and_manage_users(self):
		self._create('manager', 'admin')
		user = get_user_model().objects.get(username='manager')
		self.assertTrue(user.is_superuser and user.is_staff)
		self.client.force_login(user)
		self.assertContains(self.client.get('/suppliers/'), 'Upload suppliers')
		self.assertEqual(self.client.get('/suppliers/upload/').status_code, 200)
		self.assertEqual(self.client.get('/accounts/users/').status_code, 200)

	def test_change_access_and_status(self):
		user = get_user_model().objects.create_user('viewer', password='pw')
		self.client.post('/accounts/users/', {'action': 'set_access', 'user_id': user.pk, 'access': 'admin'})
		user.refresh_from_db()
		self.assertTrue(user.is_superuser)
		self.client.post('/accounts/users/', {'action': 'set_access', 'user_id': user.pk, 'access': 'read_only'})
		self.client.post('/accounts/users/', {'action': 'deactivate', 'user_id': user.pk})
		user.refresh_from_db()
		self.assertFalse(user.is_superuser or user.is_active)
		self.client.post('/accounts/users/', {'action': 'activate', 'user_id': user.pk})
		user.refresh_from_db()
		self.assertTrue(user.is_active)

	def test_admin_cannot_change_own_access(self):
		self.client.post('/accounts/users/', {'action': 'set_access', 'user_id': self.admin.pk, 'access': 'read_only'})
		self.admin.refresh_from_db()
		self.assertTrue(self.admin.is_superuser)
