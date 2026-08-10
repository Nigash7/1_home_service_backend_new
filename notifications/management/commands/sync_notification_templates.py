"""
Seed / refresh NotificationTemplate rows from events.py so admins can reword
notification copy from the dashboard without a code change.

    python manage.py sync_notification_templates
    python manage.py sync_notification_templates --overwrite
"""
from django.core.management.base import BaseCommand

from notifications.events import REGISTRY
from notifications.models import NotificationTemplate


class Command(BaseCommand):
    help = "Create NotificationTemplate rows for every event in events.py"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Reset existing rows back to the code defaults.",
        )

    def handle(self, *args, **options):
        created = updated = 0
        for key, spec in REGISTRY.items():
            defaults = {
                "audience": spec.audience,
                "category": spec.category,
                "title_template": spec.title,
                "body_template": spec.body,
                "push_enabled": spec.push,
            }
            obj, was_created = NotificationTemplate.objects.get_or_create(
                event=key, defaults=defaults
            )
            if was_created:
                created += 1
            elif options["overwrite"]:
                for field, value in defaults.items():
                    setattr(obj, field, value)
                obj.save()
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Templates: {created} created, {updated} updated, "
            f"{len(REGISTRY)} total events."
        ))