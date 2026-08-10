from django.contrib import admin

from .models import (
    Broadcast,
    DeviceToken,
    Notification,
    NotificationPreference,
    NotificationTemplate,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient_type", "event", "is_read",
                    "push_status", "created_at")
    list_filter = ("recipient_type", "category", "is_read", "push_status")
    search_fields = ("title", "body", "event")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "read_at", "push_sent_at")


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("__str__", "recipient_type", "platform", "is_active",
                    "last_seen_at")
    list_filter = ("recipient_type", "platform", "is_active")
    search_fields = ("token", "device_id")


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("event", "audience", "category", "is_active", "push_enabled")
    list_filter = ("audience", "category", "is_active")
    search_fields = ("event", "title_template", "body_template")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "recipient_type", "push_enabled")
    list_filter = ("recipient_type", "push_enabled")


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "status", "recipient_count", "created_at")
    list_filter = ("audience", "status")