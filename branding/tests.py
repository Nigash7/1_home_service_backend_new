from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import AppBranding

# Smallest valid GIF, so the ImageField accepts it without Pillow complaining.
TINY_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!'
    b'\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00'
    b'\x00\x02\x02D\x01\x00;'
)


class AppBrandingApiTests(TestCase):
    def _create(self, app, name='Home Service'):
        return AppBranding.objects.create(
            app=app,
            app_name=name,
            logo=SimpleUploadedFile('logo.gif', TINY_GIF, content_type='image/gif'),
        )

    def test_returns_branding_for_the_requested_app(self):
        self._create(AppBranding.App.CUSTOMER, 'Make My House')
        res = self.client.get('/api/branding/customer/')

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['app'], 'CUSTOMER')
        self.assertEqual(res.data['app_name'], 'Make My House')
        self.assertTrue(res.data['logo'].endswith('.gif'))

    def test_app_name_is_case_insensitive_in_the_url(self):
        self._create(AppBranding.App.VENDOR)
        self.assertEqual(self.client.get('/api/branding/VENDOR/').status_code, 200)
        self.assertEqual(self.client.get('/api/branding/vendor/').status_code, 200)

    def test_apps_do_not_see_each_others_branding(self):
        self._create(AppBranding.App.CUSTOMER, 'Customer brand')
        res = self.client.get('/api/branding/vendor/')
        self.assertEqual(res.status_code, 404)

    def test_missing_branding_returns_404(self):
        self.assertEqual(self.client.get('/api/branding/customer/').status_code, 404)

    def test_unknown_app_returns_404(self):
        self.assertEqual(self.client.get('/api/branding/banana/').status_code, 404)

    def test_endpoint_is_public(self):
        # The splash screen calls this before anyone has logged in.
        self._create(AppBranding.App.CUSTOMER)
        self.assertEqual(self.client.get('/api/branding/customer/').status_code, 200)
