"""
Backfill `Review.service` for reviews written before the API derived it.

Until now the customer app posted only booking/rating/comment, so every real
customer review was stored with service=NULL and never appeared on the service
detail page. Single-service bookings can be resolved unambiguously; reviews on
multi-service bookings are left alone (the read path matches those through the
booking instead).
"""
from django.db import migrations


def service_ids_in(services_json):
    ids = []
    for item in (services_json or []):
        if not isinstance(item, dict):
            continue
        try:
            ids.append(int(item['id']))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def backfill(apps, schema_editor):
    Review = apps.get_model('reviews', 'Review')
    Service = apps.get_model('services', 'Service')

    live_service_ids = set(Service.objects.values_list('id', flat=True))
    updates = []

    orphans = Review.objects.filter(
        service__isnull=True, booking__isnull=False
    ).select_related('booking')

    for review in orphans:
        ids = service_ids_in(review.booking.services_json)
        # Only when the booking was for exactly one service that still exists.
        if len(ids) == 1 and ids[0] in live_service_ids:
            review.service_id = ids[0]
            updates.append(review)

    if updates:
        Review.objects.bulk_update(updates, ['service'], batch_size=500)


def unbackfill(apps, schema_editor):
    """Deliberately a no-op: we can't tell a backfilled FK from a real one."""


class Migration(migrations.Migration):

    dependencies = [
        ('reviews', '0004_fakereviewproxy_realreviewproxy'),
        ('services', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
