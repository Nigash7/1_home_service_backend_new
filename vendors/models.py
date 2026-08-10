from django.db import models
from django.conf import settings


class Vendor(models.Model):
    """
    Extra profile info for a User with role=VENDOR.
    Created by ADMIN after verifying documents (not self-registered).
    """

    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        VERIFIED = 'VERIFIED', 'Verified'
        REJECTED = 'REJECTED', 'Rejected'

    class AvailabilityStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        BUSY = 'BUSY', 'Busy'
        OFFLINE = 'OFFLINE', 'Offline'

    # Booking statuses that mean "this vendor is actively on a job right now"
    ACTIVE_JOB_STATUSES = ['ASSIGNED', 'IN_PROGRESS']

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_profile'
    )

    # Categories this vendor can do work for (a vendor could be both Plumber + Electrician)
    categories = models.ManyToManyField(
        'services.ServiceCategory', related_name='vendors', blank=True
    )

    # Service area — used for "nearest vendor" matching (address-based, per your decision)
    service_area = models.CharField(
        max_length=255, help_text="e.g. area/zone/pincode this vendor covers"
    )
    address = models.TextField(blank=True)

    verification_status = models.CharField(
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )

    last_assigned_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When this vendor was last given a job (for round-robin)"
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    is_available = models.BooleanField(
        default=True, help_text="Toggle off when vendor is busy/on leave"
    )

    status = models.CharField(
        max_length=10,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.AVAILABLE,
        help_text="Available = free, Busy = on a job, Offline = not working",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.service_area}"

    @property
    def active_job_count(self):
        """Number of jobs this vendor is currently working on."""
        # Annotated value wins if the queryset already computed it (avoids N+1)
        if hasattr(self, '_active_jobs'):
            return self._active_jobs

        from bookings.models import Booking
        return Booking.objects.filter(
            vendor=self, status__in=self.ACTIVE_JOB_STATUSES
        ).count()

    @property
    def computed_status(self):
        """
        Live availability:
          OFFLINE   - manually set (leave, not working)
          BUSY      - has at least one active job
          AVAILABLE - free to take work
        """
        if self.status == self.AvailabilityStatus.OFFLINE or not self.is_available:
            return self.AvailabilityStatus.OFFLINE

        if self.active_job_count > 0:
            return self.AvailabilityStatus.BUSY

        return self.AvailabilityStatus.AVAILABLE


class VendorDocument(models.Model):
    """
    Documents uploaded for verification (ID proof, address proof, trade certificate, etc.)
    Admin reviews these before setting Vendor.verification_status = VERIFIED.
    """

    class DocType(models.TextChoices):
        ID_PROOF = 'ID_PROOF', 'ID Proof'
        ADDRESS_PROOF = 'ADDRESS_PROOF', 'Address Proof'
        TRADE_CERTIFICATE = 'TRADE_CERT', 'Trade Certificate'
        OTHER = 'OTHER', 'Other'

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='documents')
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    file = models.FileField(upload_to='vendor_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor} - {self.get_doc_type_display()}"