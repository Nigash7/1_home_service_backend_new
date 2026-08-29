"""
The only module that talks to Razorpay.

Views go through here so signature checking lives in exactly one place, and so
the whole app can be exercised in tests by swapping this out rather than by
reaching the network.
"""
import hashlib
import hmac
import logging

import razorpay
from django.conf import settings

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Razorpay refused or could not be reached. Carries a customer-safe message."""


def is_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def get_client():
    if not is_configured():
        raise PaymentError("Online payment is not set up yet.")
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(*, amount_paise, receipt, notes=None):
    """
    Open a Razorpay order. Returns the order dict.

    `receipt` is our own reference and comes back on every webhook, which is
    how a delivery is tied to a booking even if our records are mid-write.
    """
    try:
        return get_client().order.create({
            'amount': amount_paise,
            'currency': settings.RAZORPAY_CURRENCY,
            'receipt': receipt,
            'notes': notes or {},
            # Capture immediately. Authorise-only would leave money in limbo
            # that expires after five days if nobody remembers to capture it.
            'payment_capture': 1,
        })
    except Exception as exc:
        logger.exception("Razorpay order.create failed for receipt %s", receipt)
        raise PaymentError("Could not start the payment. Please try again.") from exc


def verify_checkout_signature(*, order_id, payment_id, signature):
    """
    True when the browser's success callback really came from Razorpay.

    The customer's own device hands us this, so without the check anyone could
    POST a made-up payment id and have the booking marked paid.
    """
    if not (order_id and payment_id and signature):
        return False
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(*, body: bytes, signature: str):
    """
    True when a webhook body was signed with our webhook secret.

    Deliberately returns False when no secret is configured: an unsigned
    webhook endpoint is a public "mark this booking paid" button.
    """
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def fetch_payment(payment_id):
    """
    Ask Razorpay what it thinks the state of a payment is.

    Used as the tie-breaker when a client claims success -- their word plus a
    valid signature still gets checked against the source of truth.
    """
    try:
        return get_client().payment.fetch(payment_id)
    except Exception as exc:
        logger.exception("Razorpay payment.fetch failed for %s", payment_id)
        raise PaymentError("Could not confirm the payment.") from exc


def refund(payment_id, *, amount_paise=None, notes=None):
    """Refund in full, or partially when amount_paise is given."""
    data = {'notes': notes or {}}
    if amount_paise is not None:
        data['amount'] = amount_paise
    try:
        return get_client().payment.refund(payment_id, data)
    except Exception as exc:
        logger.exception("Razorpay refund failed for %s", payment_id)
        raise PaymentError("Could not process the refund.") from exc
