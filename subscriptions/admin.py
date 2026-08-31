from django.contrib import admin

from .models import SubscriptionPlan, SubscriptionUpgradeRequest, VendorSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'price', 'billing_period', 'is_active', 'is_default',
        'sort_order', 'active_subscriber_count',
    )
    list_filter = ('is_active', 'is_default', 'billing_period')
    search_fields = ('name', 'description')
    ordering = ('sort_order', 'price')


@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'vendor', 'plan', 'status', 'start_date', 'end_date',
        'amount_paid', 'created_at',
    )
    list_filter = ('status', 'plan')
    search_fields = (
        'vendor__user__first_name', 'vendor__user__last_name',
        'vendor__user__phone_number', 'payment_reference',
    )
    autocomplete_fields = ('vendor',)
    readonly_fields = ('created_at', 'cancelled_at')
    date_hierarchy = 'start_date'


@admin.register(SubscriptionUpgradeRequest)
class SubscriptionUpgradeRequestAdmin(admin.ModelAdmin):
    list_display = (
        'vendor', 'plan', 'status', 'quoted_price', 'created_at',
        'reviewed_by', 'reviewed_at',
    )
    list_filter = ('status', 'plan')
    search_fields = (
        'vendor__user__first_name', 'vendor__user__last_name',
        'vendor__user__phone_number',
    )
    autocomplete_fields = ('vendor',)
    readonly_fields = ('created_at', 'reviewed_at', 'granted_subscription')
    date_hierarchy = 'created_at'
