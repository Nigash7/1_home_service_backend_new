from django.contrib import admin
from .models import AdminUser, OtpCode


@admin.register(AdminUser)
class AdminUserAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'role', 'is_active', 'last_login')
    list_filter = ('role', 'is_active')
    search_fields = ('full_name', 'email')

    fieldsets = (
        ('Basic Info', {
            'fields': ('full_name', 'email', 'role', 'is_active'),
        }),
        ('Staff Permissions (only for STAFF role)', {
            'fields': (
                'can_manage_bookings',
                'can_manage_vendors',
                'can_manage_customers',
                'can_manage_services',
                'can_manage_content',
                'can_manage_discounts',
                'can_view_reports',
            ),
            'description': 'Super Admins have all permissions automatically.',
        }),
    )


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'created_at', 'used')
    list_filter = ('used',)
    readonly_fields = ('email', 'code', 'created_at')