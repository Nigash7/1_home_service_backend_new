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
SUPPORT_REPLY = _e(
    "support.reply", CUSTOMER, CAT_SYSTEM,
    "Support replied to your ticket",
    "{subject}: {preview}",
    route="/support/{ticket_id}",
)
SUPPORT_STATUS = _e(
    "support.status_changed", CUSTOMER, CAT_SYSTEM,
    "Support ticket {status}",
    "Your ticket \"{subject}\" is now {status}.",
    route="/support/{ticket_id}",
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
VENDOR_BANK_ACCOUNT_CHANGED = _e(
    "vendor.bank_account_changed", VENDOR, CAT_PAYMENT,
    "Payout account {action}",
    "Your payouts will now go to the account ending {account}. "
    "If this was not you, contact support straight away.",
    route="/profile/bank-account",
)
VENDOR_BANK_ACCOUNT_MISSING = _e(
    "vendor.bank_account_missing", VENDOR, CAT_PAYMENT,
    "Add your payout details",
    "We cannot send your earnings until you add a bank account in the app.",
    route="/profile/bank-account",
)
VENDOR_PAYOUT_FAILED = _e(
    "vendor.payout_failed", VENDOR, CAT_PAYMENT,
    "Payout could not be sent",
    "We could not send {amount} because {reason}. Check your payout details "
    "and we will try again.",
    route="/profile/bank-account",
)
VENDOR_BANK_ACCOUNT_VERIFIED = _e(
    "vendor.bank_account_verified", VENDOR, CAT_PAYMENT,
    "Payout account verified",
    "Your account ending {account} is verified. Earnings will be sent there.",
    route="/profile/bank-account",
)
VENDOR_BROADCAST = _e(
    "vendor.broadcast", VENDOR, CAT_SYSTEM,
    "{title}", "{body}",
)
VENDOR_SUPPORT_REPLY = _e(
    "vendor.support_reply", VENDOR, CAT_SYSTEM,
    "Support replied to your ticket",
    "{subject}: {preview}",
    route="/support/{ticket_id}",
)
VENDOR_SUPPORT_STATUS = _e(
    "vendor.support_status_changed", VENDOR, CAT_SYSTEM,
    "Support ticket {status}",
    "Your ticket \"{subject}\" is now {status}.",
    route="/support/{ticket_id}",
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
ADMIN_SUPPORT_TICKET = _e(
    "admin.support_ticket", ADMIN, CAT_SYSTEM,
    "New support ticket",
    "{requester_name} ({requester_type}) raised \"{subject}\" — {category}.",
    route="/support/{ticket_id}/",
)
ADMIN_SUPPORT_REPLY = _e(
    "admin.support_reply", ADMIN, CAT_SYSTEM,
    "New reply on ticket #{ticket_id}",
    "{requester_name} ({requester_type}) replied: {preview}",
    route="/support/{ticket_id}/",
)
ADMIN_SYSTEM = _e(
    "admin.system", ADMIN, CAT_SYSTEM,
    "{title}", "{body}",
)

# =================================================================== TENDERS
# Bidding flow: the customer posts a requirement, an admin approves it,
# matching vendors quote, the customer picks one, then the work runs.
# Placeholders: {tender_code} {tender_id} {tender_title} {category_name}
#               {budget} {amount} {bid_count} {vendor_name} {customer_name}
#               {reason} {milestone_title} {percent}

TENDER_SUBMITTED = _e(
    "tender.submitted", CUSTOMER, CAT_BOOKING,
    "Tender sent for review",
    "{tender_code} is with our team. We will let you know as soon as it goes out to vendors.",
    route="/tenders/{tender_id}",
)
TENDER_APPROVED = _e(
    "tender.approved", CUSTOMER, CAT_BOOKING,
    "Your tender is live",
    "{tender_title} is now open and {vendor_count} vendors can see it. Bids will start arriving soon.",
    route="/tenders/{tender_id}",
)
TENDER_REJECTED = _e(
    "tender.rejected", CUSTOMER, CAT_BOOKING,
    "Tender needs changes",
    "{tender_code} was not published. {reason}",
    route="/tenders/{tender_id}",
)
TENDER_BID_RECEIVED = _e(
    "tender.bid_received", CUSTOMER, CAT_BOOKING,
    "New bid on {tender_title}",
    "{vendor_name} quoted {amount}. You now have {bid_count} bid(s) to compare.",
    route="/tenders/{tender_id}/bids",
)
TENDER_AWARDED = _e(
    "tender.awarded", CUSTOMER, CAT_BOOKING,
    "Deal confirmed",
    "{vendor_name} will take on {tender_title} for {amount}. Reach them on {vendor_phone}.",
    route="/tenders/{tender_id}",
)
TENDER_WORK_STARTED = _e(
    "tender.work_started", CUSTOMER, CAT_BOOKING,
    "Work has started",
    "{vendor_name} has started work on {tender_title}.",
    route="/tenders/{tender_id}",
)
TENDER_PROGRESS_UPDATE = _e(
    "tender.progress_update", CUSTOMER, CAT_BOOKING,
    "Progress update",
    "{vendor_name} posted an update on {tender_title}. {percent}",
    route="/tenders/{tender_id}",
)
TENDER_MILESTONE_REACHED = _e(
    "tender.milestone_reached", CUSTOMER, CAT_PAYMENT,
    "Milestone reached",
    "{vendor_name} marked \"{milestone_title}\" complete on {tender_title}. {amount} is due.",
    route="/tenders/{tender_id}",
)
TENDER_COMPLETED = _e(
    "tender.completed", CUSTOMER, CAT_BOOKING,
    "Project completed",
    "{vendor_name} has finished {tender_title}. Tell us how it went.",
    route="/tenders/{tender_id}",
)

# ---------------------------------------------------------------- vendor app
TENDER_NEW_MATCH = _e(
    "tender.new_match", VENDOR, CAT_BOOKING,
    "New tender: {tender_title}",
    "A {category_name} project in {location} with a budget of {budget}. Submit your bid.",
    route="/tenders/{tender_id}",
)
TENDER_BID_ACCEPTED = _e(
    "tender.bid_accepted", VENDOR, CAT_BOOKING,
    "You won {tender_title}",
    "{customer_name} accepted your bid of {amount}. Reach them on {customer_phone}.",
    route="/tenders/{tender_id}",
)
TENDER_BID_REJECTED = _e(
    "tender.bid_rejected", VENDOR, CAT_BOOKING,
    "Bid not selected",
    "Your bid on {tender_title} was not chosen this time.",
    route="/tenders/{tender_id}",
)
TENDER_CLOSED_TO_VENDOR = _e(
    "tender.closed_vendor", VENDOR, CAT_BOOKING,
    "Tender withdrawn",
    "{tender_title} is no longer accepting bids. {reason}",
    route="/tenders/{tender_id}",
)
TENDER_MILESTONE_PAID = _e(
    "tender.milestone_paid", VENDOR, CAT_PAYMENT,
    "Payment released",
    "{customer_name} released {amount} for \"{milestone_title}\" on {tender_title}.",
    route="/tenders/{tender_id}",
)
TENDER_DEADLINE_SOON = _e(
    "tender.deadline_soon", VENDOR, CAT_BOOKING,
    "Bidding closes tomorrow",
    "{tender_title} stops accepting bids on {bid_deadline}.",
    route="/tenders/{tender_id}",
)

# --------------------------------------------------------------------- admin
ADMIN_TENDER_SUBMITTED = _e(
    "admin.tender_submitted", ADMIN, CAT_BOOKING,
    "Tender awaiting approval",
    "{customer_name} posted \"{tender_title}\" ({category_name}, {budget}).",
    route="/tenders/{tender_id}/",
)
ADMIN_TENDER_AWARDED = _e(
    "admin.tender_awarded", ADMIN, CAT_BOOKING,
    "Tender awarded",
    "{tender_code} went to {vendor_name} for {amount}.",
    route="/tenders/{tender_id}/",
)
ADMIN_TENDER_COMPLETED = _e(
    "admin.tender_completed", ADMIN, CAT_BOOKING,
    "Tender completed",
    "{vendor_name} finished {tender_code}.",
    route="/tenders/{tender_id}/",
)
ADMIN_TENDER_CANCELLED = _e(
    "admin.tender_cancelled", ADMIN, CAT_BOOKING,
    "Tender cancelled",
    "{tender_code} was cancelled. {reason}",
    route="/tenders/{tender_id}/",
)
