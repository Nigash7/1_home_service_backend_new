from django.apps import AppConfig


class ReferralsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'referrals'

    def ready(self):
        # Wires the booking-completed listener that marks a referral as earned.
        from . import signals  # noqa: F401
