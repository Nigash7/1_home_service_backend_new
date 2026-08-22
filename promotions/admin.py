from django.contrib import admin
from .models import SpotlightBanner, HeaderBanner, PromoCard


@admin.register(PromoCard)
class PromoCardAdmin(admin.ModelAdmin):
    list_display = ('title', 'placement', 'after_section', 'category', 'sort_order', 'is_active')
    list_filter = ('is_active', 'placement', 'category')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'subtitle', 'badge_text')
    autocomplete_fields = ('category', 'subcategory')


@admin.register(HeaderBanner)
class HeaderBannerAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'category', 'subcategory', 'sort_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'subtitle')
    autocomplete_fields = ('category', 'subcategory')


@admin.register(SpotlightBanner)
class SpotlightBannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'subcategory', 'sort_order', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title', 'subtitle')
    autocomplete_fields = ('category', 'subcategory')
