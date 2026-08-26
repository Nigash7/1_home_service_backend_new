from django.db import models


class HomeSection(models.Model):
    title = models.CharField(max_length=200, help_text="e.g. Most booked services, Plumbing, AC Repair")
    subtitle = models.CharField(max_length=200, blank=True, help_text="e.g. Grooming essentials")
    home_display_limit = models.PositiveIntegerField(
        default=3,
        help_text="How many services to show on the home page. Rest appear in 'See all' page."
    )
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower = shown first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Home Sections"

    def __str__(self):
        return self.title


class HomeSectionItem(models.Model):
    section = models.ForeignKey(
        HomeSection, on_delete=models.CASCADE, related_name='items'
    )
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE, related_name='home_section_items'
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']
        unique_together = ('section', 'service')

    def __str__(self):
        return f"{self.section.title} → {self.service.name}"

class ProVendorSection(models.Model):
    """
    A home-screen row of Pro Vendors, curated exactly the way a HomeSection
    curates services: admin picks the members, the order and how many show
    before the customer has to tap "See all".
    """
    title = models.CharField(max_length=200, help_text="e.g. Top rated electricians")
    subtitle = models.CharField(max_length=200, blank=True, help_text="e.g. Hand-picked, verified pros")
    home_display_limit = models.PositiveIntegerField(
        default=5,
        help_text="How many vendors to show on the home page. Rest appear in 'See all' page."
    )
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower = shown first")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Pro Vendor Sections"

    def __str__(self):
        return self.title


class ProVendorSectionItem(models.Model):
    section = models.ForeignKey(
        ProVendorSection, on_delete=models.CASCADE, related_name='items'
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='pro_section_items'
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']
        unique_together = ('section', 'vendor')

    def __str__(self):
        return f"{self.section.title} → {self.vendor.display_name}"
