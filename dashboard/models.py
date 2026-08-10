from django.db import models
from django.conf import settings
from django.utils import timezone
import random
import string


class AdminUser(models.Model):
    """
    Custom admin user for the dashboard. Separate from Django's auth.
    Can be a super admin or a staff member with role-based permissions.
    """

    class Role(models.TextChoices):
        SUPER_ADMIN = 'SUPER_ADMIN', 'Super Admin'
        STAFF = 'STAFF', 'Staff'

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)

    # Staff permissions (fine-grained)
    can_manage_bookings = models.BooleanField(default=True)
    can_manage_vendors = models.BooleanField(default=True)
    can_manage_customers = models.BooleanField(default=False)
    can_manage_services = models.BooleanField(default=False)
    can_manage_content = models.BooleanField(default=False, help_text="Home sections, spotlights, curations")
    can_manage_discounts = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Admin User"
        verbose_name_plural = "Admin Users"

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN


class OtpCode(models.Model):
    """One-time code sent to admin's email for login."""
    email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def generate_for(cls, email):
        code = ''.join(random.choices(string.digits, k=6))
        # Invalidate old OTPs
        cls.objects.filter(email=email, used=False).update(used=True)
        return cls.objects.create(email=email, code=code)

    def is_expired(self):
        # Valid for 10 minutes
        return (timezone.now() - self.created_at).total_seconds() > 600

    def __str__(self):
        return f"OTP for {self.email}"

class CustomerNotification(models.Model):
    """Notifications for customers (booking updates, vendor assigned, etc.)."""
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE,
        related_name='notifications'
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE,
        null=True, blank=True, related_name='notifications'
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} — {self.customer}"        