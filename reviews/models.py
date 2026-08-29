from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


def service_ids_in(services_json):
    """
    The service IDs inside a booking's `services_json` (entries look like
    {id, name, price, qty}). Junk entries are skipped rather than raising.
    """
    ids = []
    for item in (services_json or []):
        if not isinstance(item, dict):
            continue
        try:
            ids.append(int(item['id']))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def service_ids_in_booking(booking):
    """The service IDs a booking was placed for."""
    return service_ids_in(getattr(booking, 'services_json', None))


class Review(models.Model):
    booking = models.OneToOneField(
        'bookings.Booking', on_delete=models.CASCADE, related_name='review',
        null=True, blank=True
    )
    # A review comes from a booking or from a tender, never both. Keeping
    # tender reviews in this same table is what lets a vendor's rating count
    # everything they have done -- `reviews_received` already drives
    # Vendor.average_rating and every pro vendor card.
    tender = models.OneToOneField(
        'tenders.Tender', on_delete=models.CASCADE, related_name='review',
        null=True, blank=True
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='reviews_given',
        null=True, blank=True
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='reviews_received',
        null=True, blank=True
    )
    service_category = models.ForeignKey(
        'services.ServiceCategory', on_delete=models.CASCADE,
        related_name='reviews', null=True, blank=True
    )
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE,
        related_name='reviews', null=True, blank=True
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)
    reviewer_name = models.CharField(
        max_length=100, blank=True,
        help_text="Display name for admin-created reviews. Leave blank for real customer reviews."
    )
    is_admin_created = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Review #{self.id} — {self.rating}★ by {self.customer} for {self.vendor}"