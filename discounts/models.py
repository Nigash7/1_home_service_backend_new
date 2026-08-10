from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class Discount(models.Model):
    """
    A discount applied automatically to specific services/categories.
    E.g. 20% off on Plumbing, or ₹100 off on all AC services.
    """

    class DiscountType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage (%)'
        FLAT = 'FLAT', 'Flat Amount (₹)'

    name = models.CharField(max_length=200, help_text="e.g. Monsoon Sale, First Booking Offer")
    description = models.TextField(blank=True)
    discount_type = models.CharField(
        max_length=15, choices=DiscountType.choices, default=DiscountType.PERCENTAGE
    )
    value = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Percentage (e.g. 20 for 20%) or flat amount (e.g. 100 for ₹100)"
    )
    max_discount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Max discount amount (for percentage discounts only)"
    )
    min_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Minimum cart total required to apply this discount"
    )

    # Target — leave all blank for site-wide discount
    category = models.ForeignKey(
        'services.ServiceCategory', on_delete=models.CASCADE,
        null=True, blank=True, related_name='discounts'
    )
    subcategory = models.ForeignKey(
        'services.SubCategory', on_delete=models.CASCADE,
        null=True, blank=True, related_name='discounts'
    )
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE,
        null=True, blank=True, related_name='discounts'
    )

    # Validity
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = 'All Services'
        if self.service:
            target = f"Service: {self.service.name}"
        elif self.subcategory:
            target = f"Subcategory: {self.subcategory.name}"
        elif self.category:
            target = f"Category: {self.category.name}"
        return f"{self.name} — {target}"

    def is_valid_now(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True


class Coupon(models.Model):
    """
    A coupon code the customer enters manually.
    E.g. WELCOME50, MONSOON20.
    """

    class DiscountType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage (%)'
        FLAT = 'FLAT', 'Flat Amount (₹)'

    code = models.CharField(max_length=50, unique=True, help_text="e.g. WELCOME50")
    description = models.CharField(max_length=200, blank=True)
    discount_type = models.CharField(
        max_length=15, choices=DiscountType.choices, default=DiscountType.PERCENTAGE
    )
    value = models.DecimalField(max_digits=10, decimal_places=2)
    max_discount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Max discount amount for percentage coupons"
    )
    min_order_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Minimum cart total to use this coupon"
    )

    # Usage limits
    total_usage_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Max number of times this coupon can be used across all customers (blank = unlimited)"
    )
    per_customer_limit = models.PositiveIntegerField(
        default=1,
        help_text="Max times a single customer can use this coupon"
    )
    times_used = models.PositiveIntegerField(default=0)

    # Validity
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} — {self.value}{'%' if self.discount_type == 'PERCENTAGE' else '₹'} off"

    def is_valid_now(self):
        from django.utils import timezone
        now = timezone.now()
        if not self.is_active:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.total_usage_limit and self.times_used >= self.total_usage_limit:
            return False
        return True


class CouponUsage(models.Model):
    """Tracks each time a customer uses a coupon."""
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='usages')
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='coupon_usages'
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.CASCADE, related_name='coupon_usages',
        null=True, blank=True
    )
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-used_at']

    def __str__(self):
        return f"{self.coupon.code} used by {self.customer} — ₹{self.discount_amount}"