from django.db import models
from django.utils import timezone


class MapSettings(models.Model):
    """
    Which map every screen draws, and the Google key behind it when Google is
    the one chosen.

    One row. The admin picks between the free basemap this project has always
    used and Google Maps, and pastes a Google Maps Platform key for the second.
    Everything that draws a map -- the Vendors Map and the vendor location
    picker in this dashboard, and the customer app's "Confirm Your Location"
    screen -- reads its answer from here, so the switch is one setting rather
    than a code change in three places.

    The key is deliberately allowed to be wrong: `effective_provider` falls
    back to the free map whenever Google is chosen without a key, so a
    half-finished setup leaves working maps rather than blank grey boxes.
    """

    # --- The free option: no key, no billing account, no expiry. -----------
    #
    # Esri's World Street Map. Keyless, and checked on 2026-09-04 against the
    # two things that disqualify a "free" tile source:
    #
    #   No watermark. CARTO, which this used to draw, now stamps
    #   "API KEY REQUIRED" diagonally across every keyless tile while still
    #   answering 200, so nothing in the code notices -- the map just looks
    #   broken. OpenStreetMap's own tile server answers 418 to apps.
    #
    #   Access-Control-Allow-Origin: *, because the customer app's web
    #   build draws the very same URL.
    #
    # Note the {z}/{y}/{x} order: Esri puts row before column, the opposite
    # of the usual slippy-map convention. It needs no subdomains and serves
    # no @2x tiles, hence no {s} and no {r} here.
    FREE_TILE_URL = (
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map'
        '/MapServer/tile/{z}/{y}/{x}'
    )
    FREE_SUBDOMAINS = ''
    FREE_ATTRIBUTION = 'Esri, HERE, Garmin, OpenStreetMap contributors'
    FREE_MAX_ZOOM = 19

    # --- The Google option -------------------------------------------------
    #
    # Raster tiles for the app come from the Map Tiles API, which hands out
    # {z}/{x}/{y} tiles any slippy-map renderer can draw -- so the app keeps
    # flutter_map and needs no rebuild to switch. The dashboard uses the Maps
    # JavaScript API instead, because a browser can run the real thing.
    GOOGLE_TILE_URL = (
        'https://tile.googleapis.com/v1/2dtiles/{z}/{x}/{y}'
        '?session={session}&key={key}'
    )
    GOOGLE_ATTRIBUTION = '\u00a9 Google'
    GOOGLE_MAX_ZOOM = 22

    class Provider(models.TextChoices):
        FREE = 'FREE', 'Free map'
        GOOGLE = 'GOOGLE', 'Google Maps'

    provider = models.CharField(
        max_length=10, choices=Provider.choices, default=Provider.FREE,
        help_text="Which map the dashboard and the customer app draw.",
    )
    google_api_key = models.CharField(
        max_length=200, blank=True,
        help_text="Google Maps Platform API key. Needs Maps JavaScript API, "
                  "Map Tiles API and Geocoding API enabled on it.",
    )

    # Map Tiles API hands out a session token that stands for "a map of this
    # type, in this language" and is required on every tile request. It lasts
    # about two weeks; it is cached here so the app is not made to re-request
    # one, and cleared whenever the key or the provider changes.
    tile_session = models.CharField(max_length=100, blank=True, editable=False)
    tile_session_expires_at = models.DateTimeField(
        null=True, blank=True, editable=False,
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Map Settings'
        verbose_name_plural = 'Map Settings'

    def __str__(self):
        return f'Map Settings ({self.get_provider_display()})'

    @classmethod
    def get_solo(cls):
        """The one and only settings row, created with defaults on first use."""
        settings_row, _ = cls.objects.get_or_create(pk=1)
        return settings_row

    # ------------------------------------------------------------------
    # What is actually in force
    # ------------------------------------------------------------------

    @property
    def effective_provider(self):
        """
        The provider that can really be served right now.

        Google without a key is not Google -- it is a grey box -- so it reads
        back as the free map until somebody pastes one in.
        """
        if self.provider == self.Provider.GOOGLE and self.google_api_key.strip():
            return self.Provider.GOOGLE
        return self.Provider.FREE

    @property
    def is_google(self):
        return self.effective_provider == self.Provider.GOOGLE

    @property
    def is_awaiting_key(self):
        """Google was picked but no key was pasted, so the free map is showing."""
        return self.provider == self.Provider.GOOGLE and not self.google_api_key.strip()

    @property
    def key(self):
        return self.google_api_key.strip()

    def has_live_tile_session(self):
        return bool(
            self.tile_session
            and self.tile_session_expires_at
            and self.tile_session_expires_at > timezone.now()
        )

    def clear_tile_session(self):
        self.tile_session = ''
        self.tile_session_expires_at = None
