from django.conf import settings
from django.db import models
from django.utils import timezone

from .events import CATEGORY_CHOICES, CAT_SYSTEM

# ---------------------------------------------------------------------------
# Model paths. Override in settings.py if your app labels differ.
# ---------------------------------------------------------------------------
CUSTOMER_MODEL = getattr(settings, "NOTIFY_CUSTOMER_MODEL", "customers.Customer")
VENDOR_MODEL = getattr(settings, "NOTIFY_VENDOR_MODEL", "vendors.Vendor")
ADMIN_MODEL = getattr(settings, "NOTIFY_ADMIN_MODEL", "dashboard.AdminUser")
BOOKING_MODEL = getattr(settings, "NOTIFY_BOOKING_MODEL", "bookings.Booking")


class RecipientType(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    VENDOR = "VENDOR", "Vendor"
    ADMIN = "ADMIN", "Admin"


class PushStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"


class Platform(models.TextChoices):
    ANDROID = "ANDROID", "Android"
    IOS = "IOS", "iOS"
    WEB = "WEB", "Web"


# ===========================================================================
class Notification(models.Model):
    """One in-app notification row for exactly one recipient."""

    recipient_type = models.CharField(
        max_length=10, choices=RecipientType.choices, db_index=True
    )
    customer = models.ForeignKey(
        CUSTOMER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="app_notifications",
    )
    vendor = models.ForeignKey(
        VENDOR_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="app_notifications",
    )
    admin_user = models.ForeignKey(
        ADMIN_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="app_notifications",
    )

    event = models.CharField(max_length=64, db_index=True)
    category = models.CharField(
        max_length=16, choices=CATEGORY_CHOICES, default=CAT_SYSTEM, db_index=True
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    booking = models.ForeignKey(
        BOOKING_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="app_notifications",
    )
    route = models.CharField(
        max_length=255, blank=True,
        help_text="Deep link the app opens on tap, e.g. /bookings/42",
    )
    data = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    push_status = models.CharField(
        max_length=10, choices=PushStatus.choices, default=PushStatus.PENDING
    )
    push_error = models.TextField(blank=True)
    push_sent_at = models.DateTimeField(null=True, blank=True)

    broadcast = models.ForeignKey(
        "notifications.Broadcast", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient_type", "customer", "is_read"]),
            models.Index(fields=["recipient_type", "vendor", "is_read"]),
            models.Index(fields=["recipient_type", "admin_user", "is_read"]),
        ]

    def __str__(self):
        return f"[{self.recipient_type}] {self.title}"

    @property
    def recipient(self):
        return {
            RecipientType.CUSTOMER: self.customer,
            RecipientType.VENDOR: self.vendor,
            RecipientType.ADMIN: self.admin_user,
        }.get(self.recipient_type)

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


# ===========================================================================
class DeviceToken(models.Model):
    """An FCM registration token for one device of one recipient."""

    recipient_type = models.CharField(max_length=10, choices=RecipientType.choices)
    customer = models.ForeignKey(
        CUSTOMER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="device_tokens",
    )
    vendor = models.ForeignKey(
        VENDOR_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="device_tokens",
    )
    admin_user = models.ForeignKey(
        ADMIN_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="device_tokens",
    )

    token = models.TextField(unique=True)
    platform = models.CharField(
        max_length=10, choices=Platform.choices, default=Platform.ANDROID
    )
    device_id = models.CharField(max_length=128, blank=True)
    app_version = models.CharField(max_length=32, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.recipient_type} · {self.platform} · {self.token[:18]}…"

    def deactivate(self, reason=""):
        self.is_active = False
        self.save(update_fields=["is_active"])


# ===========================================================================
class NotificationPreference(models.Model):
    """Per-recipient push toggles. Missing row = everything enabled."""

    recipient_type = models.CharField(max_length=10, choices=RecipientType.choices)
    customer = models.OneToOneField(
        CUSTOMER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="notification_preference",
    )
    vendor = models.OneToOneField(
        VENDOR_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="notification_preference",
    )
    admin_user = models.OneToOneField(
        ADMIN_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="notification_preference",
    )

    push_enabled = models.BooleanField(default=True)
    booking_updates = models.BooleanField(default=True)
    payment_updates = models.BooleanField(default=True)
    promotions = models.BooleanField(default=True)
    review_updates = models.BooleanField(default=True)
    account_updates = models.BooleanField(default=True)
    system_updates = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    _CATEGORY_FIELD = {
        "BOOKING": "booking_updates",
        "PAYMENT": "payment_updates",
        "PROMO": "promotions",
        "REVIEW": "review_updates",
        "ACCOUNT": "account_updates",
        "SYSTEM": "system_updates",
    }

    def allows_push(self, category: str) -> bool:
        if not self.push_enabled:
            return False
        return getattr(self, self._CATEGORY_FIELD.get(category, ""), True)

    def __str__(self):
        return f"Preferences · {self.recipient_type}"


# ===========================================================================
class NotificationTemplate(models.Model):
    """
    Optional DB override for the defaults in events.py so admins can reword
    copy without a deploy. Run `manage.py sync_notification_templates` to seed.
    """

    event = models.CharField(max_length=64, unique=True)
    audience = models.CharField(max_length=10, choices=RecipientType.choices)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    title_template = models.CharField(max_length=200)
    body_template = models.TextField(blank=True)
    push_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["audience", "event"]

    def __str__(self):
        return self.event


# ===========================================================================
class Broadcast(models.Model):
    """An admin-composed message blasted to a segment of users."""

    class Audience(models.TextChoices):
        ALL_CUSTOMERS = "ALL_CUSTOMERS", "All customers"
        ALL_VENDORS = "ALL_VENDORS", "All vendors"
        VERIFIED_VENDORS = "VERIFIED_VENDORS", "Verified vendors only"
        ALL_ADMINS = "ALL_ADMINS", "All admins"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    title = models.CharField(max_length=200)
    body = models.TextField()
    audience = models.CharField(max_length=20, choices=Audience.choices)
    route = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    recipient_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    created_by = models.ForeignKey(
        ADMIN_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="broadcasts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} → {self.get_audience_display()}"