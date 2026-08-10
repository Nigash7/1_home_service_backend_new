from django.db import models


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
    duration_minutes = models.PositiveIntegerField(
        default=60, help_text="Estimated duration in minutes"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price']

    def __str__(self):
        if self.subcategory:
            return f"{self.subcategory.name} → {self.name}"
        return f"{self.category.name} → {self.name}"