"""
Live tail of the notification table. Leave this running in a second terminal
while you use the customer app / admin dashboard.

    python manage.py notify_watch
    python manage.py notify_watch --all       # show existing rows first
    python manage.py notify_watch --interval 1
"""
import time

from django.core.management.base import BaseCommand

from notifications.models import Notification

COLOR = {
    "CUSTOMER": "SUCCESS",
    "VENDOR": "WARNING",
    "ADMIN": "NOTICE",
}


class Command(BaseCommand):
    help = "Print notifications live as they are created."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=2.0,
                            help="Seconds between polls (default 2).")
        parser.add_argument("--all", action="store_true",
                            help="Print the last 20 existing rows before watching.")

    def _print(self, note):
        style = getattr(self.style, COLOR.get(note.recipient_type, "NOTICE"))
        who = note.recipient
        line = (
            f"[{note.created_at:%H:%M:%S}] "
            f"{note.recipient_type:<8} → {str(who)[:28]:<28} "
            f"{note.event:<28} push={note.push_status}"
        )
        self.stdout.write(style(line))
        self.stdout.write(f"           {note.title}")
        if note.body:
            self.stdout.write(f"           {note.body[:110]}")
        self.stdout.write("")

    def handle(self, *args, **options):
        if options["all"]:
            for note in reversed(list(Notification.objects.order_by("-id")[:20])):
                self._print(note)

        last_id = (
            Notification.objects.order_by("-id").values_list("id", flat=True).first()
            or 0
        )
        self.stdout.write(self.style.HTTP_INFO(
            f"Watching for new notifications (last id = {last_id}). Ctrl+C to stop.\n"
        ))

        try:
            while True:
                for note in Notification.objects.filter(id__gt=last_id).order_by("id"):
                    self._print(note)
                    last_id = note.id
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write(self.style.HTTP_INFO("\nStopped."))