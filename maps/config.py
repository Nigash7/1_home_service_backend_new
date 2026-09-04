"""
The one answer to "what should this client draw?", shared by everything.

The dashboard templates and the customer app's API both come through here, so
switching provider in the dashboard cannot leave the two disagreeing.
"""

import logging
from urllib.parse import quote

from .google import GoogleMapsError, create_tile_session
from .models import MapSettings

logger = logging.getLogger(__name__)


def tile_session_for(settings_row):
    """
    A live Map Tiles session token, minted the first time and then reused.

    Returns None when Google is not in force or when Google refuses -- the
    caller then serves the free map, which is always better than no map.
    """
    if not settings_row.is_google:
        return None

    if settings_row.has_live_tile_session():
        return settings_row.tile_session

    try:
        token, expires_at = create_tile_session(settings_row.key)
    except GoogleMapsError as exc:
        # Most often: Map Tiles API not enabled on the key. The dashboard's
        # settings page says so in plain words; here we just fall back.
        logger.warning('Map Tiles session refused: %s', exc)
        return None

    settings_row.tile_session = token
    settings_row.tile_session_expires_at = expires_at
    settings_row.save(update_fields=['tile_session', 'tile_session_expires_at',
                                     'updated_at'])
    return token


def map_config(settings_row=None):
    """
    Everything a slippy-map renderer needs, as plain values.

    Deliberately shaped so a client swaps one URL string and one attribution
    line rather than learning who the provider is -- `provider` is along for
    the ride only so the app can decide whether to show a Google logo.
    """
    settings_row = settings_row or MapSettings.get_solo()

    if settings_row.is_google:
        session = tile_session_for(settings_row)
        if session:
            return {
                'provider': MapSettings.Provider.GOOGLE,
                # Only the two query values are filled in; {z}/{x}/{y}
                # stay in place for the renderer to substitute per tile.
                'tile_url': (
                    MapSettings.GOOGLE_TILE_URL
                    .replace('{session}', quote(session, safe=''))
                    .replace('{key}', quote(settings_row.key, safe=''))
                ),
                'subdomains': '',
                'attribution': MapSettings.GOOGLE_ATTRIBUTION,
                'max_zoom': MapSettings.GOOGLE_MAX_ZOOM,
                # Google's 2x tiles already come back at 512px, so a renderer
                # must not double them a second time for a retina screen.
                'retina_tiles': False,
            }

    return {
        'provider': MapSettings.Provider.FREE,
        'tile_url': MapSettings.FREE_TILE_URL,
        'subdomains': MapSettings.FREE_SUBDOMAINS,
        'attribution': MapSettings.FREE_ATTRIBUTION,
        'max_zoom': MapSettings.FREE_MAX_ZOOM,
        'retina_tiles': True,
    }
