from django.db import models
from django.conf import settings


class Customer(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    address = models.TextField(blank=True)
    state = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class ServiceView(models.Model):
    """
    One row per customer per service, holding only the latest visit. Keeping
    it collapsed like this means "recently viewed" never shows the same
    service twice and the table stays small.
    """
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='service_views'
    )
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE, related_name='views'
    )
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-viewed_at']
        unique_together = ('customer', 'service')
        indexes = [models.Index(fields=['customer', '-viewed_at'])]

    def __str__(self):
        return f"{self.customer} viewed {self.service.name}"