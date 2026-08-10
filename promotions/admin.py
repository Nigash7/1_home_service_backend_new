from django.contrib import admin
from .models import SpotlightBanner


@admin.register(SpotlightBanner)
class SpotlightBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'subcategory', 'sort_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'subtitle')
    autocomplete_fields = ('category', 'subcategory')