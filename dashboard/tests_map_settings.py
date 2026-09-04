"""
The dashboard page that decides which map everything draws.

The form is a full-form save like the rest of the dashboard: every POST
carries both the provider and the key, and what is not sent is cleared.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from maps.models import MapSettings

from .tests_access import make_admin

KEY = 'AIzaTestKey'
PASSWORD = 'sup3r-secret-pw'

ALL_OK = [
    {'name': 'Map Tiles API', 'ok': True, 'detail': 'Serving tiles.'},
    {'name': 'Geocoding API', 'ok': True, 'detail': 'Turning pins into addresses.'},
]
TILES_REFUSED = [
    {'name': 'Map Tiles API', 'ok': False, 'detail': 'Map Tiles API has not been used'},
    {'name': 'Geocoding API', 'ok': True, 'detail': 'Turning pins into addresses.'},
]


class MapSettingsViewTests(TestCase):
    def setUp(self):
        make_admin('mapadmin', permissions=['system.maps'])
        self.client.post(reverse('dashboard_login'), {
            'username': 'mapadmin', 'password': PASSWORD,
        })
        self.url = reverse('map_settings')

    def test_page_opens_on_the_free_map(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The free map is live')

    @patch('dashboard.views.google_maps.check_key', return_value=ALL_OK)
    def test_saving_google_with_a_key_switches_every_map(self, mock_check):
        response = self.client.post(self.url, {
            'provider': 'GOOGLE', 'google_api_key': KEY,
        })

        settings_row = MapSettings.get_solo()
        self.assertEqual(settings_row.provider, MapSettings.Provider.GOOGLE)
        self.assertEqual(settings_row.google_api_key, KEY)
        self.assertTrue(settings_row.is_google)
        mock_check.assert_called_once_with(KEY)
        self.assertContains(response, 'What Google said about this key')

    def test_google_without_a_key_is_saved_but_says_so(self):
        response = self.client.post(self.url, {
            'provider': 'GOOGLE', 'google_api_key': '',
        })

        settings_row = MapSettings.get_solo()
        self.assertEqual(settings_row.provider, MapSettings.Provider.GOOGLE)
        # Still drawing the free map, because there is nothing to draw with.
        self.assertFalse(settings_row.is_google)
        self.assertContains(response, 'Google Maps needs an API key')

    @patch('dashboard.views.google_maps.check_key', return_value=TILES_REFUSED)
    def test_a_partly_refused_key_is_reported_per_api(self, _mock):
        response = self.client.post(self.url, {
            'provider': 'GOOGLE', 'google_api_key': KEY,
        })

        self.assertContains(response, 'Map Tiles API has not been used')
        self.assertContains(response, 'Google refused part of this key')

    def test_switching_back_to_free_keeps_the_key(self):
        MapSettings.objects.update_or_create(
            pk=1, defaults={'provider': 'GOOGLE', 'google_api_key': KEY},
        )

        self.client.post(self.url, {'provider': 'FREE', 'google_api_key': KEY})

        settings_row = MapSettings.get_solo()
        self.assertEqual(settings_row.provider, MapSettings.Provider.FREE)
        self.assertEqual(settings_row.google_api_key, KEY)

    @patch('dashboard.views.google_maps.check_key', return_value=ALL_OK)
    def test_a_new_key_throws_away_the_old_tile_session(self, _mock):
        MapSettings.objects.update_or_create(pk=1, defaults={
            'provider': 'GOOGLE',
            'google_api_key': 'AIzaOldKey',
            'tile_session': 'stale-session',
            'tile_session_expires_at': timezone.now() + timedelta(days=10),
        })

        self.client.post(self.url, {'provider': 'GOOGLE', 'google_api_key': KEY})

        settings_row = MapSettings.get_solo()
        self.assertEqual(settings_row.tile_session, '')
        self.assertIsNone(settings_row.tile_session_expires_at)

    def test_an_unknown_provider_falls_back_to_the_free_map(self):
        self.client.post(self.url, {'provider': 'MAPBOX', 'google_api_key': ''})

        self.assertEqual(MapSettings.get_solo().provider, MapSettings.Provider.FREE)

    def test_a_role_without_the_permission_cannot_open_it(self):
        self.client.get(reverse('dashboard_logout'))
        make_admin('nomaps', permissions=['bookings.view'])
        self.client.post(reverse('dashboard_login'), {
            'username': 'nomaps', 'password': PASSWORD,
        })

        response = self.client.get(self.url)

        self.assertNotEqual(response.status_code, 200)


class MapSettingsInDashboardMapsTests(TestCase):
    """The two dashboard pages that draw a map read the same setting."""

    def setUp(self):
        make_admin('mapviewer', super_admin=True)
        self.client.post(reverse('dashboard_login'), {
            'username': 'mapviewer', 'password': PASSWORD,
        })

    def test_vendors_map_uses_leaflet_on_the_free_map(self):
        response = self.client.get(reverse('assignment_center'))

        self.assertContains(response, 'leaflet')
        self.assertNotContains(response, 'maps.googleapis.com')

    @patch('maps.config.create_tile_session')
    def test_vendors_map_loads_google_once_configured(self, _mock):
        MapSettings.objects.update_or_create(
            pk=1, defaults={'provider': 'GOOGLE', 'google_api_key': KEY},
        )

        response = self.client.get(reverse('assignment_center'))

        self.assertContains(response, 'maps.googleapis.com')
        self.assertContains(response, KEY)
        self.assertNotContains(response, 'unpkg.com/leaflet')

    @patch('maps.config.create_tile_session')
    def test_vendor_form_picker_loads_google_once_configured(self, _mock):
        MapSettings.objects.update_or_create(
            pk=1, defaults={'provider': 'GOOGLE', 'google_api_key': KEY},
        )

        response = self.client.get(reverse('vendor_add'))

        self.assertContains(response, 'initPickerMap')
        self.assertContains(response, 'maps.googleapis.com')

    def test_vendor_form_picker_is_rendered_at_all(self):
        # It used to sit outside the content block, where Django dropped it.
        response = self.client.get(reverse('vendor_add'))

        self.assertContains(response, 'pickerStart')
        self.assertContains(response, 'unpkg.com/leaflet')
