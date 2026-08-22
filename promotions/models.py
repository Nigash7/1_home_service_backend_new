from django.db import models


class HeaderBanner(models.Model):
    """
    Slides of the carousel inside the home screen hero header.
    Fully managed by admin — image, overlay text and where a tap leads.
    """
    image = models.ImageField(upload_to='header_banners/')
    title = models.CharField(
        max_length=120, blank=True,
        help_text="Big text drawn over the image. Leave blank to show the image only.",
    )
    subtitle = models.CharField(max_length=160, blank=True, help_text="Small text under the title")

    # Where tapping the slide takes the customer
    category = models.ForeignKey(
        'services.ServiceCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='header_banners',
    )
    subcategory = models.ForeignKey(
        'services.SubCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='header_banners',
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Header Banners"

    def __str__(self):
        return self.title or f"Header banner #{self.pk}"


class PromoCard(models.Model):
    """
    Large full-bleed promo card shown on the home screen, positioned
    relative to the home sections by the admin.
    """
    PLACEMENT_BEFORE = 'BEFORE_SECTIONS'
    PLACEMENT_AFTER_SECTION = 'AFTER_SECTION'
    PLACEMENT_AFTER = 'AFTER_SECTIONS'
    PLACEMENT_CHOICES = [
        (PLACEMENT_BEFORE, 'Before all home sections'),
        (PLACEMENT_AFTER_SECTION, 'After a specific home section'),
        (PLACEMENT_AFTER, 'After all home sections'),
    ]

    image = models.ImageField(upload_to='promo_cards/')
    badge_text = models.CharField(
        max_length=40, blank=True, help_text="Small chip at the top, e.g. New Launch",
    )
    badge_color = models.CharField(
        max_length=7, default='#9C1458', help_text="Hex colour of the badge chip",
    )
    title = models.CharField(max_length=120, help_text="e.g. Korean Facials at home")
    subtitle = models.CharField(max_length=120, blank=True, help_text="e.g. From ₹1,899")
    button_text = models.CharField(max_length=40, default='Book now')

    # Where tapping the card takes the customer
    category = models.ForeignKey(
        'services.ServiceCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='promo_cards',
    )
    subcategory = models.ForeignKey(
        'services.SubCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='promo_cards',
    )

    # Where the card sits on the home screen
    placement = models.CharField(
        max_length=20, choices=PLACEMENT_CHOICES, default=PLACEMENT_AFTER,
    )
    after_section = models.ForeignKey(
        'home_sections.HomeSection',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='promo_cards',
        help_text="Only used when placement is 'After a specific home section'",
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(
        default=0, help_text="Lower number = shown first within the same placement",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Promo Cards"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # A section reference only means something for the 'after a section'
        # placement — drop it otherwise so the app never mis-places the card.
        if self.placement != self.PLACEMENT_AFTER_SECTION:
            self.after_section = None
        super().save(*args, **kwargs)


class SpotlightBanner(models.Model):
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True)
    background_image = models.ImageField(upload_to='spotlight_banners/')
    button_text = models.CharField(max_length=50, default='Book now')

    # Link to a specific category or subcategory
    category = models.ForeignKey(
        'services.ServiceCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='spotlight_banners',
    )
    subcategory = models.ForeignKey(
        'services.SubCategory',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='spotlight_banners',
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = shown first")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-created_at']
        verbose_name_plural = "Spotlight Banners"

    def __str__(self):
        return self.title