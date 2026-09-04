"""
The two endpoints the mobile apps call.

Both are public, like branding: the location picker is reachable from the
guest browsing flow on the web, before anyone has a token.
"""

import logging

import requests
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .config import map_config
from .google import GoogleMapsError
from .google import reverse_geocode as google_reverse_geocode
from .models import MapSettings

logger = logging.getLogger(__name__)

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/reverse'


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def map_config_view(request):
    """
    GET /api/maps/config/

    What to draw. The app caches this and swaps its tile URL -- there is no
    Google-specific code path in the app beyond showing Google's attribution.

    On the Google option this hands out a tile URL with the key in it. That is
    how client-side maps work everywhere -- the key is visible in any app that
    draws its own tiles -- which is why the dashboard tells the admin to
    restrict the key in Google Cloud rather than pretending it stays secret.
    """
    return Response(map_config())


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def reverse_geocode_view(request):
    """
    GET /api/maps/reverse-geocode/?lat=..&lng=..

    The address under the customer's pin. Proxied rather than called from the
    app for three reasons: the Google key stays on the server, the app keeps
    one code path whichever provider is on, and Nominatim's rate limit and
    User-Agent rule are honoured in one place instead of on every phone.
    """
    try:
        latitude = float(request.query_params.get('lat', ''))
        longitude = float(request.query_params.get('lng', ''))
    except (TypeError, ValueError):
        return Response(
            {'detail': 'lat and lng are required, as numbers.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return Response(
            {'detail': 'lat and lng are out of range.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    settings_row = MapSettings.get_solo()

    if settings_row.is_google:
        try:
            address = google_reverse_geocode(settings_row.key, latitude, longitude)
        except GoogleMapsError as exc:
            # Geocoding API not enabled, quota gone, key restricted: the
            # customer should still get an address, so fall through to the
            # free one rather than handing the app an error.
            logger.warning('Google reverse geocode failed: %s', exc)
        else:
            return Response({'address': address, 'provider': 'google'})

    return Response({
        'address': _nominatim_reverse_geocode(latitude, longitude),
        'provider': 'nominatim',
    })


def _nominatim_reverse_geocode(latitude, longitude):
    """OpenStreetMap's free service. Returns None rather than raising."""
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={'format': 'json', 'lat': latitude, 'lon': longitude},
            # Nominatim's usage policy requires an identifying User-Agent and
            # blocks requests without one.
            headers={'User-Agent': 'HomeServiceBackend/1.0'},
            timeout=8,
        )
        if response.status_code != 200:
            return None
        return response.json().get('display_name')
    except (requests.RequestException, ValueError):
        return None
