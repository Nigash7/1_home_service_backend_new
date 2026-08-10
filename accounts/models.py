from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. We extend Django's built-in auth so the SAME
    username/password system works for:
      - Admin (created via createsuperuser)
      - Vendor (created by admin from the admin panel)
      - Customer (created via app signup)
    The `role` field tells us which type of user this is.
    """

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        VENDOR = 'VENDOR', 'Vendor'
        CUSTOMER = 'CUSTOMER', 'Customer'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER)
    phone_number = models.CharField(max_length=15, blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.role})"


class OTPRequest(models.Model):
    """
    Stores a one-time-password sent to a phone number for signup/login.
    A new row is created every time an OTP is requested; old ones just
    become invalid once expired or once a newer one is issued.
    """
    phone_number = models.CharField(max_length=15, db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)  # wrong-code tries against THIS otp

    def __str__(self):
        return f"OTP for {self.phone_number} (verified={self.is_verified})"
