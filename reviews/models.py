from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Review(models.Model):
    booking = models.OneToOneField(
        'bookings.Booking', on_delete=models.CASCADE, related_name='review',
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