from django.contrib import admin
from .models import ServiceCategory, SubCategory, Service


class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 1
    fields = ('name', 'description', 'icon', 'base_price', 'is_active')


class ServiceInline(admin.TabularInline):
    model = Service
    extra = 1
    fields = ('name', 'subcategory', 'description', 'image', 'price', 'duration_minutes', 'is_active')


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'sort_order', 'base_price', 'is_active', 'created_at')
    list_editable = ('sort_order',)
    list_filter = ('is_active',)
    search_fields = ('name',)
    inlines = [SubCategoryInline, ServiceInline]


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'base_price', 'is_active', 'created_at')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'category__name')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'subcategory', 'price', 'duration_minutes', 'is_active')
    list_filter = ('is_active', 'category', 'subcategory')
    search_fields = ('name', 'category__name', 'subcategory__name')