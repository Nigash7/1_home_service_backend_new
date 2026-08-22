"""
Point existing form submissions back at their booking.

A submission is created before the booking exists, so the app attaches it via
`Booking.form_submission` at checkout and `FormSubmission.booking` stays null.
The admin page and the vendor's job read the answers through that reverse link,
so without this the answers on every past booking stay invisible.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')
    FormSubmission = apps.get_model('service_forms', 'FormSubmission')

    linked = Booking.objects.filter(
        form_submission__isnull=False, form_submission__booking__isnull=True
    ).values_list('id', 'form_submission_id')

    updates = []
    for booking_id, submission_id in linked:
        updates.append(FormSubmission(id=submission_id, booking_id=booking_id))

    if updates:
        FormSubmission.objects.bulk_update(updates, ['booking'], batch_size=500)


def unbackfill(apps, schema_editor):
    """No-op: a backfilled link is indistinguishable from one set normally."""


class Migration(migrations.Migration):

    dependencies = [
        ('service_forms', '0001_initial'),
        ('bookings', '0011_alter_booking_assigned_by'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
