"""
Automatic notifications driven by model changes.

Everything here is defensive: if a model or field name doesn't match your
project, the hook silently skips instead of breaking bookings. Adjust
STATUS_EVENTS below to match your real Booking.status values.
"""
import logging

from django.apps import apps
from django.db.models.signals import post_save, pre_save

from . import events
from .services import notify, notify_admins

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EDIT ME: map your Booking.status values to notification events.
# Keys are compared upper-cased. Unknown statuses are simply ignored.
# ---------------------------------------------------------------------------
STATUS_EVENTS = {
    "PENDING":            {"customer": None},
    "BOOKED":             {"customer": events.BOOKING_CREATED.key},
    "CONFIRMED":          {"customer": events.BOOKING_CREATED.key},
    "PLANNING":           {"customer": events.BOOKING_PLANNING.key},
    "VENDOR_ASSIGNED":    {"customer": events.BOOKING_VENDOR_ASSIGNED.key,
                           "vendor": events.JOB_ASSIGNED.key},
    "ASSIGNED":           {"customer": events.BOOKING_VENDOR_ASSIGNED.key,
                           "vendor": events.JOB_ASSIGNED.key},
    "WORK_STARTED":       {"customer": events.BOOKING_WORK_STARTED.key},
    "IN_PROGRESS":        {"customer": events.BOOKING_WORK_STARTED.key},
    "COMPLETED":          {"customer": events.BOOKING_COMPLETED.key},
    "PAYMENT_COMPLETED":  {"customer": events.PAYMENT_RECEIVED.key,
                           "admin": events.ADMIN_PAYMENT_RECEIVED.key},
    "PAID":               {"customer": events.PAYMENT_RECEIVED.key,
                           "admin": events.ADMIN_PAYMENT_RECEIVED.key},
    "CANCELLED":          {"customer": events.BOOKING_CANCELLED.key,
                           "vendor": events.JOB_CANCELLED.key,
                           "admin": events.ADMIN_BOOKING_CANCELLED.key},
}


# ------------------------------------------------------------------ helpers
def _val(obj, *names, default=""):
    """First non-empty attribute from a list of candidate field names."""
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value not in (None, ""):
                return value
    return default


def _booking_context(booking):
    customer = _val(booking, "customer", default=None)
    vendor = _val(booking, "vendor", "assigned_vendor", default=None)
    return {
        "booking_id": booking.pk,
        "booking_code": _val(booking, "code", "booking_code", "reference",
                             default=f"#{booking.pk}"),
        "service_name": _val(booking, "service_name", default="") or (
            str(_val(booking, "service", default="")) or "your service"
        ),
        "schedule": str(_val(booking, "scheduled_date", "booking_date",
                             "service_date", "scheduled_at", default="the scheduled time")),
        "amount": _val(booking, "final_amount", "amount", "total_amount", default=""),
        "reason": _val(booking, "cancellation_reason", "cancel_reason",
                       "reschedule_reason", default=""),
        "customer_name": str(customer) if customer else "A customer",
        "vendor_name": str(vendor) if vendor else "Your professional",
        "vendor_phone": _val(vendor, "phone_number", "phone", default="") if vendor else "",
        "vendor_id": vendor.pk if vendor else "",
    }


def _customer_of(booking):
    return _val(booking, "customer", default=None)


def _vendor_of(booking):
    return _val(booking, "vendor", "assigned_vendor", default=None)


# ------------------------------------------------------------------ bookings
def booking_pre_save(sender, instance, **kwargs):
    if not instance.pk:
        instance._notify_old_status = None
        instance._notify_old_vendor_id = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance._notify_old_status = _val(old, "status", default=None)
        instance._notify_old_vendor_id = getattr(
            old, "vendor_id", getattr(old, "assigned_vendor_id", None)
        )
    except Exception:
        instance._notify_old_status = None
        instance._notify_old_vendor_id = None


def booking_post_save(sender, instance, created, **kwargs):
    try:
        ctx = _booking_context(instance)
        customer = _customer_of(instance)
        vendor = _vendor_of(instance)
        status = str(_val(instance, "status", default="")).upper()
        old_status = str(getattr(instance, "_notify_old_status", "") or "").upper()

        # --- brand new booking ------------------------------------------
        if created:
            if customer:
                notify(events.BOOKING_CREATED.key, customer=customer,
                       booking=instance, context=ctx)
            notify_admins(events.ADMIN_BOOKING_CREATED.key,
                          booking=instance, context=ctx)
            return

        # Assigning a vendor normally flips the status in the SAME save, so
        # the two blocks below can reach for the same event. Whatever the
        # first one sends is recorded here and the second one skips it —
        # otherwise the customer and the vendor each get told twice.
        already_sent = set()

        # --- vendor newly attached (may happen without a status change) ---
        old_vendor_id = getattr(instance, "_notify_old_vendor_id", None)
        new_vendor_id = vendor.pk if vendor else None
        if new_vendor_id and new_vendor_id != old_vendor_id:
            if customer:
                notify(events.BOOKING_VENDOR_ASSIGNED.key, customer=customer,
                       booking=instance, context=ctx)
                already_sent.add(events.BOOKING_VENDOR_ASSIGNED.key)
            notify(events.JOB_ASSIGNED.key, vendor=vendor,
                   booking=instance, context=ctx)
            already_sent.add(events.JOB_ASSIGNED.key)
        elif old_vendor_id and not new_vendor_id:
            old_vendor = _vendor_model().objects.filter(pk=old_vendor_id).first()
            if old_vendor:
                notify(events.JOB_UNASSIGNED.key, vendor=old_vendor,
                       booking=instance, context=ctx)
                already_sent.add(events.JOB_UNASSIGNED.key)

        # --- status transition -------------------------------------------
        if status and status != old_status:
            mapping = STATUS_EVENTS.get(status) or {}
            customer_event = mapping.get("customer")
            vendor_event = mapping.get("vendor")

            if customer_event and customer and customer_event not in already_sent:
                notify(customer_event, customer=customer,
                       booking=instance, context=ctx)
            if vendor_event and vendor and vendor_event not in already_sent:
                notify(vendor_event, vendor=vendor,
                       booking=instance, context=ctx)
            if mapping.get("admin"):
                notify_admins(mapping["admin"], booking=instance, context=ctx)

            # ask for a review once the job is done
            if status in ("COMPLETED", "PAYMENT_COMPLETED", "PAID") and customer:
                notify(events.REVIEW_REQUESTED.key, customer=customer,
                       booking=instance, context=ctx)

    except Exception:
        logger.exception("booking notification hook failed (booking=%s)", instance.pk)


def _vendor_model():
    from .models import VENDOR_MODEL

    return apps.get_model(*VENDOR_MODEL.split("."))


# ------------------------------------------------------------------- reviews
def review_post_save(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        vendor = _val(instance, "vendor", default=None)
        booking = _val(instance, "booking", default=None)
        customer = _val(instance, "customer", default=None)
        rating = _val(instance, "rating", "stars", default=0)
        ctx = {
            "rating": rating,
            "customer_name": str(customer) if customer else "A customer",
            "vendor_name": str(vendor) if vendor else "",
            "service_name": _val(booking, "service_name", default="a service")
            if booking else "a service",
        }
        if vendor:
            notify(events.VENDOR_REVIEW_RECEIVED.key, vendor=vendor,
                   booking=booking, context=ctx)
        try:
            if float(rating) <= 2:
                notify_admins(events.ADMIN_LOW_RATING.key,
                              booking=booking, context=ctx)
        except (TypeError, ValueError):
            pass
    except Exception:
        logger.exception("review notification hook failed")


# ------------------------------------------------------------------- vendors
def vendor_post_save(sender, instance, created, **kwargs):
    try:
        ctx = {"vendor_name": str(instance), "vendor_id": instance.pk,
               "reason": _val(instance, "rejection_reason", default="")}
        if created:
            notify_admins(events.ADMIN_VENDOR_REGISTERED.key, context=ctx)
            return

        verified = _val(instance, "is_verified", "verified", default=None)
        status = str(_val(instance, "status", default="")).upper()
        if verified is True or status == "VERIFIED":
            if not getattr(instance, "_notify_was_verified", False):
                notify(events.VENDOR_VERIFIED.key, vendor=instance, context=ctx)
        elif status in ("REJECTED", "DECLINED"):
            notify(events.VENDOR_REJECTED.key, vendor=instance, context=ctx)
    except Exception:
        logger.exception("vendor notification hook failed")


def vendor_pre_save(sender, instance, **kwargs):
    if not instance.pk:
        instance._notify_was_verified = False
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance._notify_was_verified = bool(
            _val(old, "is_verified", "verified", default=False)
        ) or str(_val(old, "status", default="")).upper() == "VERIFIED"
    except Exception:
        instance._notify_was_verified = False


# ===========================================================================
def connect():
    """Called from NotificationsConfig.ready()."""
    from .models import BOOKING_MODEL, VENDOR_MODEL

    def _hook(path, handler, signal, uid):
        try:
            model = apps.get_model(*path.split("."))
        except Exception:
            logger.warning("notifications: model %s not found, hook skipped", path)
            return
        signal.connect(handler, sender=model, dispatch_uid=uid)

    _hook(BOOKING_MODEL, booking_pre_save, pre_save, "notify_booking_pre")
    _hook(BOOKING_MODEL, booking_post_save, post_save, "notify_booking_post")
    _hook(VENDOR_MODEL, vendor_pre_save, pre_save, "notify_vendor_pre")
    _hook(VENDOR_MODEL, vendor_post_save, post_save, "notify_vendor_post")

    # Reviews: your project has real + fake review proxies — hook the concrete
    # model only, so admin-created fake reviews don't ping real vendors.
    for candidate in ("reviews.Review",):
        try:
            model = apps.get_model(*candidate.split("."))
        except Exception:
            continue
        post_save.connect(review_post_save, sender=model,
                          dispatch_uid="notify_review_post")