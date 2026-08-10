"""
Central registry of every notification event in the platform.

Add a new notification = add one line here. Nothing else changes.

Placeholders available in title/body depend on the context you pass to
notify(). Missing placeholders render as empty strings, never crash.

Common placeholders:
    {booking_code} {booking_id} {service_name} {schedule} {amount}
    {customer_name} {vendor_name} {vendor_phone} {reason} {rating}
    {old_schedule} {new_schedule}
"""
from dataclasses import dataclass

# ---------------------------------------------------------------- audiences
CUSTOMER = "CUSTOMER"
VENDOR = "VENDOR"
ADMIN = "ADMIN"

# ---------------------------------------------- categories (drive user prefs)
CAT_BOOKING = "BOOKING"
CAT_PAYMENT = "PAYMENT"
CAT_PROMO = "PROMO"
CAT_REVIEW = "REVIEW"
CAT_ACCOUNT = "ACCOUNT"
CAT_SYSTEM = "SYSTEM"

CATEGORY_CHOICES = [
    (CAT_BOOKING, "Booking updates"),
    (CAT_PAYMENT, "Payments & refunds"),
    (CAT_PROMO, "Offers & promotions"),
    (CAT_REVIEW, "Reviews & ratings"),
    (CAT_ACCOUNT, "Account"),
    (CAT_SYSTEM, "System"),
]


@dataclass(frozen=True)
class EventSpec:
    key: str
    audience: str
    category: str
    title: str
    body: str
    route: str = ""      # deep link the app opens when the notification is tapped
    push: bool = True    # send an FCM push in addition to the in-app record


REGISTRY: dict[str, EventSpec] = {}


def _e(key, audience, category, title, body, route="", push=True):
    spec = EventSpec(key, audience, category, title, body, route, push)
    REGISTRY[key] = spec
    return spec


def get_spec(key: str) -> EventSpec | None:
    return REGISTRY.get(key)


# =============================================================== CUSTOMER app
BOOKING_CREATED = _e(
    "booking.created", CUSTOMER, CAT_BOOKING,
    "Booking confirmed",
    "Your booking {booking_code} for {service_name} is confirmed for {schedule}.",
    route="/bookings/{booking_id}",
)
BOOKING_PLANNING = _e(
    "booking.planning", CUSTOMER, CAT_BOOKING,
    "We're planning your service",
    "We're arranging a professional for {service_name}. You'll hear from us shortly.",
    route="/bookings/{booking_id}",
)
BOOKING_VENDOR_ASSIGNED = _e(
    "booking.vendor_assigned", CUSTOMER, CAT_BOOKING,
    "{vendor_name} is on the job",
    "{vendor_name} has been assigned to your booking {booking_code}. Reach them on {vendor_phone}.",
    route="/bookings/{booking_id}",
)
BOOKING_WORK_STARTED = _e(
    "booking.work_started", CUSTOMER, CAT_BOOKING,
    "Work has started",
    "{vendor_name} has started work on {service_name}.",
    route="/bookings/{booking_id}",
)
BOOKING_COMPLETED = _e(
    "booking.completed", CUSTOMER, CAT_BOOKING,
    "Service completed",
    "Your {service_name} booking is complete. Thanks for choosing us!",
    route="/bookings/{booking_id}",
)
BOOKING_RESCHEDULED = _e(
    "booking.rescheduled", CUSTOMER, CAT_BOOKING,
    "Booking rescheduled",
    "Booking {booking_code} has moved to {new_schedule}. {reason}",
    route="/bookings/{booking_id}",
)
BOOKING_CANCELLED = _e(
    "booking.cancelled", CUSTOMER, CAT_BOOKING,
    "Booking cancelled",
    "Booking {booking_code} has been cancelled. {reason}",
    route="/bookings/{booking_id}",
)
BOOKING_REMINDER = _e(
    "booking.reminder", CUSTOMER, CAT_BOOKING,
    "Service tomorrow",
    "Reminder: {service_name} is scheduled for {schedule}.",
    route="/bookings/{booking_id}",
)
PAYMENT_RECEIVED = _e(
    "payment.received", CUSTOMER, CAT_PAYMENT,
    "Payment received",
    "We've received {amount} for booking {booking_code}.",
    route="/bookings/{booking_id}",
)
PAYMENT_PENDING = _e(
    "payment.pending", CUSTOMER, CAT_PAYMENT,
    "Payment pending",
    "{amount} is still due on booking {booking_code}.",
    route="/bookings/{booking_id}",
)
REFUND_INITIATED = _e(
    "payment.refund_initiated", CUSTOMER, CAT_PAYMENT,
    "Refund initiated",
    "A refund of {amount} for booking {booking_code} is on its way.",
    route="/bookings/{booking_id}",
)
REVIEW_REQUESTED = _e(
    "review.requested", CUSTOMER, CAT_REVIEW,
    "How did we do?",
    "Rate your {service_name} experience with {vendor_name}.",
    route="/bookings/{booking_id}/review",
)
PROMO_OFFER = _e(
    "promo.offer", CUSTOMER, CAT_PROMO,
    "{title}", "{body}",
    route="/offers",
)
COUPON_EXPIRING = _e(
    "promo.coupon_expiring", CUSTOMER, CAT_PROMO,
    "Your coupon expires soon",
    "Use {coupon_code} before {expiry} to save on your next booking.",
    route="/offers",
)
PROFILE_INCOMPLETE = _e(
    "account.profile_incomplete", CUSTOMER, CAT_ACCOUNT,
    "Complete your profile",
    "Add your address and phone number so we can serve you faster.",
    route="/profile",
    push=False,
)

# ================================================================= VENDOR app
JOB_ASSIGNED = _e(
    "job.assigned", VENDOR, CAT_BOOKING,
    "New job assigned",
    "{service_name} for {customer_name} on {schedule}. Booking {booking_code}.",
    route="/jobs/{booking_id}",
)
JOB_RESCHEDULED = _e(
    "job.rescheduled", VENDOR, CAT_BOOKING,
    "Job rescheduled",
    "Booking {booking_code} moved from {old_schedule} to {new_schedule}.",
    route="/jobs/{booking_id}",
)
JOB_CANCELLED = _e(
    "job.cancelled", VENDOR, CAT_BOOKING,
    "Job cancelled",
    "Booking {booking_code} has been cancelled. {reason}",
    route="/jobs/{booking_id}",
)
JOB_UNASSIGNED = _e(
    "job.unassigned", VENDOR, CAT_BOOKING,
    "Job reassigned",
    "Booking {booking_code} has been reassigned to another professional.",
    route="/jobs",
)
JOB_REMINDER = _e(
    "job.reminder", VENDOR, CAT_BOOKING,
    "Job tomorrow",
    "{service_name} for {customer_name} at {schedule}.",
    route="/jobs/{booking_id}",
)
VENDOR_REVIEW_RECEIVED = _e(
    "vendor.review_received", VENDOR, CAT_REVIEW,
    "You got a {rating}-star review",
    "{customer_name} reviewed your work on {service_name}.",
    route="/reviews",
)
VENDOR_VERIFIED = _e(
    "vendor.verified", VENDOR, CAT_ACCOUNT,
    "Account verified",
    "Your account is verified. You can start accepting jobs now.",
    route="/profile",
)
VENDOR_REJECTED = _e(
    "vendor.rejected", VENDOR, CAT_ACCOUNT,
    "Verification unsuccessful",
    "We couldn't verify your account. {reason}",
    route="/profile",
)
VENDOR_DOCUMENT_EXPIRING = _e(
    "vendor.document_expiring", VENDOR, CAT_ACCOUNT,
    "Document expiring",
    "Your {document_type} expires on {expiry}. Please upload a new one.",
    route="/profile/documents",
)
VENDOR_PAYOUT_PROCESSED = _e(
    "vendor.payout_processed", VENDOR, CAT_PAYMENT,
    "Payout processed",
    "{amount} has been sent to your registered account.",
    route="/earnings",
)
VENDOR_BROADCAST = _e(
    "vendor.broadcast", VENDOR, CAT_SYSTEM,
    "{title}", "{body}",
)

# ============================================================ ADMIN dashboard
ADMIN_BOOKING_CREATED = _e(
    "admin.booking_created", ADMIN, CAT_BOOKING,
    "New booking",
    "{customer_name} booked {service_name} for {schedule}. ({booking_code})",
    route="/bookings/{booking_id}/",
)
ADMIN_BOOKING_CANCELLED = _e(
    "admin.booking_cancelled", ADMIN, CAT_BOOKING,
    "Booking cancelled",
    "{booking_code} was cancelled. {reason}",
    route="/bookings/{booking_id}/",
)
ADMIN_BOOKING_UNASSIGNED = _e(
    "admin.booking_unassigned", ADMIN, CAT_BOOKING,
    "Booking needs a vendor",
    "{booking_code} is scheduled for {schedule} and still has no vendor assigned.",
    route="/bookings/{booking_id}/",
)
ADMIN_VENDOR_REGISTERED = _e(
    "admin.vendor_registered", ADMIN, CAT_ACCOUNT,
    "New vendor signup",
    "{vendor_name} registered and is awaiting verification.",
    route="/vendors/{vendor_id}/",
)
ADMIN_VENDOR_DOCUMENT = _e(
    "admin.vendor_document", ADMIN, CAT_ACCOUNT,
    "Vendor document uploaded",
    "{vendor_name} uploaded a {document_type} for review.",
    route="/vendors/{vendor_id}/",
)
ADMIN_PAYMENT_RECEIVED = _e(
    "admin.payment_received", ADMIN, CAT_PAYMENT,
    "Payment received",
    "{amount} received for booking {booking_code}.",
    route="/bookings/{booking_id}/",
)
ADMIN_PAYMENT_FAILED = _e(
    "admin.payment_failed", ADMIN, CAT_PAYMENT,
    "Payment failed",
    "Payment of {amount} failed on booking {booking_code}. {reason}",
    route="/bookings/{booking_id}/",
)
ADMIN_LOW_RATING = _e(
    "admin.low_rating", ADMIN, CAT_REVIEW,
    "Low rating alert",
    "{customer_name} left {rating} stars for {vendor_name} on {service_name}.",
    route="/reviews/",
)
ADMIN_SYSTEM = _e(
    "admin.system", ADMIN, CAT_SYSTEM,
    "{title}", "{body}",
)