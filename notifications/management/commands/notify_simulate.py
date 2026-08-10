"""
Walk one booking through every status and report which notifications fired.
Use this to verify STATUS_EVENTS matches your real Booking.status values.

    python manage.py notify_simulate                  # list statuses, do nothing
    python manage.py notify_simulate --booking 42     # walk booking 42
    python manage.py notify_simulate --booking 42 --restore

Use a throwaway/test booking — this really does change its status and really
does create notifications for the customer, vendor and every admin.
"""
from django.core.management.base import BaseCommand, CommandError

from notifications.models import BOOKING_MODEL, Notification


class Command(BaseCommand):
    help = "Step a booking through its statuses and show which hooks fire."

    def add_arguments(self, parser):
        parser.add_argument("--booking", type=int,
                            help="Booking id to walk. Omit to just list statuses.")
        parser.add_argument("--restore", action="store_true",
                            help="Put the original status back when finished.")

    def handle(self, *args, **options):
        from django.apps import apps

        Booking = apps.get_model(*BOOKING_MODEL.split("."))
        field = Booking._meta.get_field("status")
        statuses = [c[0] for c in (field.choices or [])]

        if not statuses:
            raise CommandError("Booking.status has no choices defined.")

        self.stdout.write(self.style.HTTP_INFO("Booking.status values:"))
        for value in statuses:
            self.stdout.write(f"  {value}")
        self.stdout.write("")

        # ---- compare against the map in signals.py ------------------------
        from notifications.signals import STATUS_EVENTS

        unmapped = [s for s in statuses if s.upper() not in STATUS_EVENTS]
        if unmapped:
            self.stdout.write(self.style.WARNING(
                "Not in STATUS_EVENTS (no notification will fire for these):"
            ))
            for value in unmapped:
                self.stdout.write(self.style.WARNING(f"  {value}"))
            self.stdout.write("")
        else:
            self.stdout.write(self.style.SUCCESS("Every status is mapped.\n"))

        if not options["booking"]:
            self.stdout.write("Pass --booking <id> to actually walk a booking.")
            return

        booking = Booking.objects.filter(pk=options["booking"]).first()
        if booking is None:
            raise CommandError(f"Booking {options['booking']} not found.")

        original = booking.status
        self.stdout.write(self.style.HTTP_INFO(
            f"Walking booking {booking.pk} (currently {original})\n"
        ))

        for value in statuses:
            if value == booking.status:
                continue
            before = Notification.objects.order_by("-id").values_list(
                "id", flat=True
            ).first() or 0

            booking.status = value
            booking.save()

            fired = Notification.objects.filter(id__gt=before).order_by("id")
            label = self.style.SUCCESS if fired else self.style.WARNING
            self.stdout.write(label(f"{value}  →  {fired.count()} notification(s)"))
            for note in fired:
                self.stdout.write(
                    f"    {note.recipient_type:<8} {note.event:<28} {note.title}"
                )
            self.stdout.write("")

        if options["restore"]:
            booking.status = original
            booking.save()
            self.stdout.write(self.style.HTTP_INFO(f"Restored to {original}."))