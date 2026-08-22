from django.db.models.signals import post_save
from django.dispatch import receiver

from bookings.models import Booking
from .models import Referral, ReferralProgram


@receiver(post_save, sender=Booking)
def mark_referral_earned(sender, instance, **kwargs):
    """
    A referral pays out once the invited friend's first booking is completed.
    Listening on the booking itself means every path that completes one —
    vendor app, dashboard, admin — is covered by the same rule.
    """
    if instance.status != Booking.Status.COMPLETED:
        return

    referral = Referral.objects.filter(
        referred_customer=instance.customer, status=Referral.Status.PENDING,
    ).first()
    if referral is None:
        return

    program = ReferralProgram.get_solo()
    if not program.is_active:
        return

    referral.mark_earned(instance, program.referrer_reward)
