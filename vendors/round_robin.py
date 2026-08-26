from django.utils import timezone
from django.db.models import Count, Q
from .models import Vendor
from datetime import datetime, UTC


def _covering_the_job(vendors, booking):
    """
    Drops vendors who do not do every service on the booking.

    Falls through untouched when the booking has no services recorded -- older
    bookings predate services_json and there is nothing to check them against.
    """
    if booking is None:
        return vendors

    from services.models import Service
    from reviews.models import service_ids_in

    service_ids = service_ids_in(getattr(booking, 'services_json', None))
    if not service_ids:
        return vendors

    booked = list(Service.objects.filter(id__in=service_ids))
    if not booked:
        return vendors

    return [v for v in vendors if all(v.covers(s) for s in booked)]


def get_rotation_queue(category, booking=None):
    """
    Returns eligible vendors for a category, ordered by round-robin priority.
    Vendor assigned longest ago (or never) comes first.
    """
    vendors = Vendor.objects.filter(
        verification_status='VERIFIED',
        categories=category,
    ).exclude(status='OFFLINE').select_related('user').prefetch_related(
        'categories', 'subcategories', 'services'
    ).annotate(
        active_jobs=Count('assigned_bookings', filter=Q(
            assigned_bookings__status__in=['ASSIGNED', 'IN_PROGRESS']
        )),
    )

    # A vendor who only handles part of the category must not be rotated onto
    # a job outside their part. Vendors who never narrowed themselves cover
    # the whole category, so this changes nothing for them.
    vendors = _covering_the_job(vendors, booking)

    # Order: never-assigned first (last_assigned_at is null), then oldest assignment
    # Secondary sort: fewer active jobs
    # in vendors/round_robin.py
    vendors = sorted(
    vendors,
    key=lambda v: (
        v.last_assigned_at or datetime.min.replace(tzinfo=UTC),
        v.active_jobs,
    )
)

    # Optionally add distance if booking has coords
    if booking and booking.location_lat and booking.location_lng:
        from .distance import haversine_distance
        for v in vendors:
            if v.latitude and v.longitude:
                v.distance_km = round(haversine_distance(
                    float(booking.location_lat), float(booking.location_lng),
                    float(v.latitude), float(v.longitude),
                ), 1)
            else:
                v.distance_km = None

    return vendors


def pick_next_vendor(category, booking=None):
    """Returns the single best round-robin vendor, or None."""
    queue = get_rotation_queue(category, booking)
    return queue[0] if queue else None


def mark_assigned(vendor):
    """Update the vendor's last_assigned_at to now."""
    vendor.last_assigned_at = timezone.now()
    vendor.save(update_fields=['last_assigned_at'])