"""
Day-before reminders for customers and vendors.
Schedule once a day with Windows Task Scheduler:

    python manage.py send_booking_reminders
"""
from datetime import timedelta

from django.apps import apps
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications import events
from notifications.models import BOOKING_MODEL
from notifications.services import notify
from notifications.signals import _booking_context, _customer_of, _vendor_of


class Command(BaseCommand):
    help = "Notify customers and vendors about bookings scheduled for tomorrow"

    def handle(self, *args, **options):
        Booking = apps.get_model(*BOOKING_MODEL.split("."))
        tomorrow = (timezone.localdate() + timedelta(days=1))

        date_field = None
        for candidate in ("scheduled_date", "booking_date", "service_date"):
            if any(f.name == candidate for f in Booking._meta.get_fields()):
                date_field = candidate
                break
        if not date_field:
            self.stderr.write("Could not find a schedule date field on Booking.")
            return

        qs = Booking.objects.filter(**{f"{date_field}__date": tomorrow}) \
            if "at" in date_field else Booking.objects.filter(**{date_field: tomorrow})
        qs = qs.exclude(status__iexact="CANCELLED")

        sent = 0
        for booking in qs.iterator():
            ctx = _booking_context(booking)
            customer = _customer_of(booking)
            vendor = _vendor_of(booking)
            if customer:
                notify(events.BOOKING_REMINDER.key, customer=customer,
                       booking=booking, context=ctx)
                sent += 1
            if vendor:
                notify(events.JOB_REMINDER.key, vendor=vendor,
                       booking=booking, context=ctx)
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"{sent} reminders queued."))