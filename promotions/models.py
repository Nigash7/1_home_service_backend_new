from django.db import models


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