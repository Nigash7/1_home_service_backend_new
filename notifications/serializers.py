from rest_framework import serializers

from .models import DeviceToken, Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id", "event", "category", "title", "body",
            "booking", "route", "data", "image_url",
            "is_read", "read_at", "created_at",
        ]
        read_only_fields = fields


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = ["token", "platform", "device_id", "app_version"]

    def validate_token(self, value):
        value = (value or "").strip()
        if len(value) < 20:
            raise serializers.ValidationError("Invalid FCM token.")
        return value


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "push_enabled", "booking_updates", "payment_updates",
            "promotions", "review_updates", "account_updates", "system_updates",
        ]