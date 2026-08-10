"""
Works out whether the JWT on a request belongs to a customer or a vendor,
so both Flutter apps can share one set of notification endpoints.

If your accessor names differ, add them to the tuples below — that's the
only change needed.
"""
from .models import RecipientType

CUSTOMER_ACCESSORS = ("customer_profile", "customer")
VENDOR_ACCESSORS = ("vendor_profile", "vendor", "vendorprofile")


def _first(user, accessors):
    for name in accessors:
        try:
            obj = getattr(user, name, None)
        except Exception:  # RelatedObjectDoesNotExist
            continue
        if obj is not None:
            return obj
    return None


def resolve_recipient(request):
    """Returns (recipient_type, recipient_object) or (None, None)."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None, None

    vendor = _first(user, VENDOR_ACCESSORS)
    if vendor is not None:
        return RecipientType.VENDOR, vendor

    customer = _first(user, CUSTOMER_ACCESSORS)
    if customer is not None:
        return RecipientType.CUSTOMER, customer

    return None, None