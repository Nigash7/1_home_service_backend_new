from django.contrib import admin
from .models import AppBranding


@admin.register(AppBranding)
class AppBrandingAdmin(admin.ModelAdmin):
    list_display = ('app', 'app_name', 'updated_at')
