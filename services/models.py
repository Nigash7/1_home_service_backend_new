from django.db import models

from tenders.project_types import ProjectType

from .pricing import (
    PricingType, allows_decimal_quantity, is_quote_only, measure_label,
    needs_quantity, price_label, shows_duration, unit_label,
)


class ServiceCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='category_icons/', blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Service Categories"
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name='subcategories'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.ImageField(upload_to='subcategory_icons/', blank=True, null=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Sub Categories"
        unique_together = ('category', 'name')

    def __str__(self):
        return f"{self.category.name} → {self.name}"


class Service(models.Model):
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name='services'
    )
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.CASCADE, related_name='services',
        null=True, blank=True
    )
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='service_images/', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # What `price` is a rate *of*. A flat ₹800, ₹15 for every square foot, or
    # nothing bookable at all because the vendor has to look first -- see
    # services/pricing.py, which every price display and every subtotal reads.
    pricing_type = models.CharField(
        max_length=20,
        choices=PricingType.choices,
        default=PricingType.FIXED,
        help_text="How the price becomes an amount. Fixed = one flat price.",
    )
    # Only a quote service ever reaches the tender form, and when it does the
    # form should open already knowing what kind of job this is. The category
    # and subcategory come from the service itself; this is the one thing a
    # service could not otherwise say. Empty leaves the form on its default.
    tender_project_type = models.CharField(
        max_length=20, blank=True, choices=ProjectType.choices,
        help_text="For Custom / Quote services: the project type the tender "
                  "form opens with. Empty = let the customer pick.",
    )
    duration_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Estimated duration in minutes. Only asked for, and only "
                  "shown, on Fixed and Starting From services -- see "
                  "`shows_duration`.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price']

    def __str__(self):
        if self.subcategory:
            return f"{self.subcategory.name} → {self.name}"
        return f"{self.category.name} → {self.name}"

    # ---- Pricing, as the cards and the cart need it -----------------------
    # Thin wrappers over services/pricing.py so a template or a serializer can
    # ask the service itself rather than knowing which helper to call.

    @property
    def price_label(self):
        """"₹15 / sq ft", "From ₹499", "Price on request"."""
        return price_label(self.price, self.pricing_type)

    @property
    def unit_label(self):
        """"sq ft", or empty when the price measures nothing."""
        return unit_label(self.pricing_type)

    @property
    def measure_label(self):
        """The label above the quantity box: "Area (sq ft)"."""
        return measure_label(self.pricing_type)

    @property
    def needs_quantity(self):
        """Whether the customer is asked for an amount before it can be priced."""
        return needs_quantity(self.pricing_type)

    @property
    def allows_decimal_quantity(self):
        """Whether half of one unit is a real amount to charge for."""
        return allows_decimal_quantity(self.pricing_type)

    @property
    def is_quote_only(self):
        """No bookable price -- these go to the tender flow for a quote."""
        return is_quote_only(self.pricing_type)

    @property
    def shows_duration(self):
        """
        Whether to ask for, and show, how long this takes.

        Only the flat types. A per-hour service is as long as the customer
        books it for, and a per-sq-ft one is as long as the area takes.
        """
        return shows_duration(self.pricing_type)