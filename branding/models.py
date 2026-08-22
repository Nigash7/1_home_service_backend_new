from django.db import models


class AppBranding(models.Model):
    """
    The logo and wordmark each mobile app pulls at launch.

    This drives the branding *inside* the app — splash, login, headers. The
    launcher icon on the phone's home screen is compiled into the APK and
    cannot be changed from here; that one still needs a new build.
    """
    class App(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer App'
        VENDOR = 'VENDOR', 'Vendor App'

    app = models.CharField(max_length=10, choices=App.choices, unique=True)
    logo = models.ImageField(upload_to='branding/')
    app_name = models.CharField(
        max_length=60, blank=True,
        help_text="Shown under the logo on the splash and login screens",
    )
    tagline = models.CharField(
        max_length=120, blank=True, help_text="Small line under the app name",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Branding"
        verbose_name_plural = "App Branding"
        ordering = ['app']

    def __str__(self):
        return self.get_app_display()
