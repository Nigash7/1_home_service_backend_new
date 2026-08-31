from django.contrib import admin

from .models import AdminLoginAttempt, AdminProfile, AdminRole


@admin.register(AdminRole)
class AdminRoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'permission_count', 'staff_count', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Accesses')
    def permission_count(self, obj):
        return len(obj.permission_set)

    @admin.display(description='Users')
    def staff_count(self, obj):
        return obj.staff.count()


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'username', 'role_display', 'is_active', 'last_login_at')
    list_filter = ('is_super_admin', 'is_active', 'role')
    search_fields = ('full_name', 'user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'last_login_at')
    raw_id_fields = ('user', 'created_by')

    @admin.display(description='Username', ordering='user__username')
    def username(self, obj):
        return obj.user.username


@admin.register(AdminLoginAttempt)
class AdminLoginAttemptAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'username', 'ip_address', 'outcome', 'cleared')
    list_filter = ('outcome', 'cleared')
    search_fields = ('username', 'ip_address')
    readonly_fields = ('username', 'ip_address', 'user_agent', 'outcome', 'created_at')

    def has_add_permission(self, request):
        # The log is written by the sign-in view, never typed in by hand.
        return False
