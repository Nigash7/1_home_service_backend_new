from django.contrib import admin
from .models import HomeSection, HomeSectionItem


class HomeSectionItemInline(admin.TabularInline):
    model = HomeSectionItem
    extra = 1
    autocomplete_fields = ('service',)
    fields = ('service', 'sort_order')


@admin.register(HomeSection)
class HomeSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'home_display_limit', 'sort_order', 'is_active', 'created_at')
    list_editable = ('home_display_limit', 'sort_order', 'is_active')
    search_fields = ('title',)
    inlines = [HomeSectionItemInline]