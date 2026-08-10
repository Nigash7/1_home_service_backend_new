from django.contrib import admin
from .models import Discount, Coupon, CouponUsage


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_type', 'value', 'target_display', 'valid_until', 'is_active')
    list_filter = ('discount_type', 'is_active', 'category')
    list_editable = ('is_active',)
    search_fields = ('name', 'description')
    autocomplete_fields = ('category', 'subcategory', 'service')

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'description', 'is_active'),
        }),
        ('Discount Amount', {
            'fields': ('discount_type', 'value', 'max_discount', 'min_order_amount'),
        }),
        ('Target (leave all blank for site-wide)', {
            'fields': ('category', 'subcategory', 'service'),
            'description': 'Choose one target level: specific service, subcategory, or category. All blank = applies to all services.',
        }),
        ('Validity', {
            'fields': ('valid_from', 'valid_until'),
        }),
    )

    def target_display(self, obj):
        if obj.service:
            return f"Service: {obj.service.name}"
        if obj.subcategory:
            return f"Subcategory: {obj.subcategory.name}"
        if obj.category:
            return f"Category: {obj.category.name}"
        return 'All Services'
    target_display.short_description = 'Applies To'


class CouponUsageInline(admin.TabularInline):
    model = CouponUsage
    extra = 0
    readonly_fields = ('customer', 'booking', 'discount_amount', 'used_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_type', 'value', 'times_used', 'total_usage_limit', 'valid_until', 'is_active')
    list_filter = ('discount_type', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('code', 'description')
    readonly_fields = ('times_used', 'created_at')
    inlines = [CouponUsageInline]

    fieldsets = (
        ('Coupon Info', {
            'fields': ('code', 'description', 'is_active'),
        }),
        ('Discount', {
            'fields': ('discount_type', 'value', 'max_discount', 'min_order_amount'),
        }),
        ('Usage Limits', {
            'fields': ('total_usage_limit', 'per_customer_limit', 'times_used'),
        }),
        ('Validity', {
            'fields': ('valid_from', 'valid_until'),
        }),
        ('Timestamps', {
            'fields': ('created_at',),
        }),
    )


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = ('coupon', 'customer', 'booking', 'discount_amount', 'used_at')
    list_filter = ('coupon',)
    readonly_fields = ('coupon', 'customer', 'booking', 'discount_amount', 'used_at')

    def has_add_permission(self, request):
        return False