"""
The only module the rest of the project should import.

    from notifications.services import notify, notify_admins

    notify("booking.created", customer=booking.customer, booking=booking,
           context={"booking_code": booking.code, "service_name": "Deep Clean"})
"""
import logging

from django.apps import apps
from django.utils import timezone

from . import events, push
from .events import ADMIN, CUSTOMER, VENDOR
from .models import (
    Broadcast,
    Notification,
    NotificationPreference,
    NotificationTemplate,
    RecipientType,
)

logger = logging.getLogger(__name__)


class _SafeDict(dict):
    """format_map helper: unknown placeholders render as '' instead of raising."""

    def __missing__(self, key):
        return ""


def _render(template: str, context: dict) -> str:
    try:
        return template.format_map(_SafeDict(context or {})).strip()
    except Exception:  # malformed template — never break the caller
        return template


def _template_override(event_key: str):
    return NotificationTemplate.objects.filter(
        event=event_key, is_active=True
    ).first()


def _preference(recipient_type, customer=None, vendor=None, admin_user=None):
    lookup = {"recipient_type": recipient_type}
    if customer is not None:
        lookup["customer"] = customer
    elif vendor is not None:
        lookup["vendor"] = vendor
    elif admin_user is not None:
        lookup["admin_user"] = admin_user
    return NotificationPreference.objects.filter(**lookup).first()


# ===========================================================================
def notify(
    event_key,
    *,
    customer=None,
    vendor=None,
    admin_user=None,
    booking=None,
    context=None,
    data=None,
    route=None,
    title=None,
    body=None,
    send_push=None,
    broadcast=None,
):
    """
    Create one notification and (optionally) fire a push for it.

    Returns the Notification, or None if the event is unknown / no recipient.
    Never raises — a failed notification must not roll back the business
    transaction that triggered it.
    """
    try:
        spec = events.get_spec(event_key)
        if spec is None:
            logger.warning("notify(): unknown event %r", event_key)
            return None

        recipient_type = spec.audience
        if recipient_type == CUSTOMER and customer is None:
            return None
        if recipient_type == VENDOR and vendor is None:
            return None
        if recipient_type == ADMIN and admin_user is None:
            return None

        ctx = dict(context or {})
        if booking is not None:
            ctx.setdefault("booking_id", booking.pk)
            ctx.setdefault("booking_code", getattr(booking, "code", "") or f"#{booking.pk}")

        override = _template_override(event_key)
        title_tpl = title or (override.title_template if override else spec.title)
        body_tpl = body or (override.body_template if override else spec.body)
        category = override.category if override else spec.category
        route_tpl = route if route is not None else spec.route

        allowed_push = spec.push and (override.push_enabled if override else True)
        if send_push is not None:
            allowed_push = send_push

        note = Notification.objects.create(
            recipient_type=recipient_type,
            customer=customer if recipient_type == CUSTOMER else None,
            vendor=vendor if recipient_type == VENDOR else None,
            admin_user=admin_user if recipient_type == ADMIN else None,
            event=event_key,
            category=category,
            title=_render(title_tpl, ctx)[:200],
            body=_render(body_tpl, ctx),
            booking=booking,
            route=_render(route_tpl, ctx),
            data=dict(data or {}, event=event_key),
            broadcast=broadcast,
        )

        if allowed_push:
            prefs = _preference(recipient_type, customer, vendor, admin_user)
            if prefs is None or prefs.allows_push(category):
                push.dispatch(note)
            else:
                note.push_status = "SKIPPED"
                note.push_error = "Disabled in user preferences"
                note.save(update_fields=["push_status", "push_error"])
        else:
            note.push_status = "SKIPPED"
            note.save(update_fields=["push_status"])

        return note

    except Exception:
        logger.exception("notify() failed for event %r", event_key)
        return None


# ===========================================================================
def notify_admins(event_key, **kwargs):
    """Fan an admin event out to every active admin user."""
    kwargs.pop("admin_user", None)
    from .models import ADMIN_MODEL

    AdminModel = apps.get_model(*ADMIN_MODEL.split("."))
    qs = AdminModel.objects.all()
    for field in ("is_active", "active"):
        if hasattr(AdminModel, field):
            qs = qs.filter(**{field: True})
            break
    return [notify(event_key, admin_user=a, **kwargs) for a in qs]


def notify_customers(event_key, customers, **kwargs):
    return [notify(event_key, customer=c, **kwargs) for c in customers]


def notify_vendors(event_key, vendors, **kwargs):
    return [notify(event_key, vendor=v, **kwargs) for v in vendors]


# ===========================================================================
def send_broadcast(broadcast: Broadcast):
    """Deliver an admin-composed Broadcast to its whole audience."""
    broadcast.status = Broadcast.Status.SENDING
    broadcast.save(update_fields=["status"])

    from .models import ADMIN_MODEL, CUSTOMER_MODEL, VENDOR_MODEL

    try:
        if broadcast.audience == Broadcast.Audience.ALL_CUSTOMERS:
            model, event_key, kw = CUSTOMER_MODEL, events.PROMO_OFFER.key, "customer"
            qs = apps.get_model(*model.split(".")).objects.all()
        elif broadcast.audience in (
            Broadcast.Audience.ALL_VENDORS,
            Broadcast.Audience.VERIFIED_VENDORS,
        ):
            model, event_key, kw = VENDOR_MODEL, events.VENDOR_BROADCAST.key, "vendor"
            qs = apps.get_model(*model.split(".")).objects.all()
            if broadcast.audience == Broadcast.Audience.VERIFIED_VENDORS:
                for field in ("is_verified", "verified", "status"):
                    if hasattr(qs.model, field):
                        qs = (
                            qs.filter(status="VERIFIED")
                            if field == "status"
                            else qs.filter(**{field: True})
                        )
                        break
        else:
            model, event_key, kw = ADMIN_MODEL, events.ADMIN_SYSTEM.key, "admin_user"
            qs = apps.get_model(*model.split(".")).objects.all()

        ctx = {"title": broadcast.title, "body": broadcast.body}
        count = 0
        for recipient in qs.iterator():
            note = notify(
                event_key,
                context=ctx,
                route=broadcast.route,
                broadcast=broadcast,
                **{kw: recipient},
            )
            if note:
                count += 1

        broadcast.recipient_count = count
        broadcast.status = Broadcast.Status.SENT
        broadcast.sent_at = timezone.now()
        broadcast.save(update_fields=["recipient_count", "status", "sent_at"])

    except Exception as exc:
        logger.exception("Broadcast %s failed", broadcast.pk)
        broadcast.status = Broadcast.Status.FAILED
        broadcast.error = str(exc)
        broadcast.save(update_fields=["status", "error"])

    return broadcast


# ===========================================================================
def queryset_for(recipient_type, recipient):
    field = {
        RecipientType.CUSTOMER: "customer",
        RecipientType.VENDOR: "vendor",
        RecipientType.ADMIN: "admin_user",
    }[recipient_type]
    return Notification.objects.filter(
        recipient_type=recipient_type, **{field: recipient}
    )


def unread_count(recipient_type, recipient) -> int:
    return queryset_for(recipient_type, recipient).filter(is_read=False).count()


def mark_all_read(recipient_type, recipient) -> int:
    return queryset_for(recipient_type, recipient).filter(is_read=False).update(
        is_read=True, read_at=timezone.now()
    )