from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, OTPRequest


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'phone_number', 'is_active', 'date_joined')
    list_filter = ('role', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Role Info', {'fields': ('role', 'phone_number')}),
    )


@admin.register(OTPRequest)
class OTPRequestAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'code', 'is_verified', 'attempts', 'created_at', 'expires_at')
    list_filter = ('is_verified',)
    search_fields = ('phone_number',)
    readonly_fields = ('phone_number', 'code', 'created_at', 'expires_at', 'is_verified', 'attempts')
