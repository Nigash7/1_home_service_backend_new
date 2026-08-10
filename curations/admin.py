from django.contrib import admin
from .models import CurationSection, CurationItem


class CurationItemInline(admin.TabularInline):
    model = CurationItem
    extra = 1
    autocomplete_fields = ('service',)
    fields = ('title', 'thumbnail', 'video', 'service', 'sort_order', 'is_active')


@admin.register(CurationSection)
class CurationSectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'sort_order', 'is_active', 'created_at')
    list_editable = ('sort_order', 'is_active')
    search_fields = ('title',)
    inlines = [CurationItemInline]


@admin.register(CurationItem)
class CurationItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'section', 'service', 'sort_order', 'is_active')
    list_filter = ('is_active', 'section')
    search_fields = ('title',)
    autocomplete_fields = ('service',)