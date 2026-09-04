from django.contrib import admin

from .models import MapSettings


@admin.register(MapSettings)
class MapSettingsAdmin(admin.ModelAdmin):
    """
    Present so the row is visible in Django admin, but the dashboard's own
    Maps page is the one to use -- it checks the key against Google before
    trusting it.
    """
    list_display = ['provider', 'has_key', 'updated_at']
    readonly_fields = ['tile_session', 'tile_session_expires_at', 'updated_at']

    @admin.display(boolean=True, description='Google key set')
    def has_key(self, obj):
        return bool(obj.key)
