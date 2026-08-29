"""
What a payment's state change means for the rest of the system.

Views and the webhook both land here so a payment captured in the browser and
the same payment captured via webhook have identical consequences.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking

from .models import Payment, Payout, to_paise, to_rupees

logger = logging.getLogger(__name__)


def _notify(event_key, *, customer=None, vendor=None, booking=None, context=None, data=None):
    """Best-effort — a notification must never roll back a captured payment."""
    try:
        from notifications.services import notify
        return notify(event_key, customer=customer, vendor=vendor,
                      booking=booking, context=context, data=data)
    except Exception:
        logger.exception("payments: notification %s failed", event_key)
        return None


def _money(amount, currency='INR'):
    symbol = '₹' if currency == 'INR' else f'{currency} '
    return f"{symbol}{amount:,.2f}"


@transaction.atomic
def mark_paid(payment, *, payment_id='', method='', signature=''):
    """
    Record that money for `payment` is now held by the platform.

    Locks the row first because the browser callback and the webhook routinely
    arrive at the same moment for the same payment; without it both read
    CREATED and both go on to notify the customer.

    Returns True if this call was the one that captured it, False if it had
    already been captured by the other path.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if not payment.mark_captured(payment_id=payment_id, method=method, signature=signature):
        return False

    booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
    if booking.payment_status != Booking.PaymentStatus.PAID:
        booking.payment_status = Booking.PaymentStatus.PAID
        booking.save(update_fields=['payment_status'])

    transaction.on_commit(lambda: _notify(
        'payment.received',
        customer=payment.customer,
        booking=booking,
        context={'amount': _money(payment.amount, payment.currency)},
        data={'booking_id': booking.pk, 'payment_id': payment.pk},
    ))
    return True


@transaction.atomic
def mark_failed(payment, *, reason='', payment_id=''):
    """Record a failed attempt. A later successful attempt gets its own row."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status in Payment.SETTLED:
        return False
    payment.status = Payment.Status.FAILED
    payment.failure_reason = (reason or '')[:2000]
    if payment_id:
        payment.razorpay_payment_id = payment_id
    payment.save(update_fields=[
        'status', 'failure_reason', 'razorpay_payment_id', 'updated_at',
    ])
    return True


@transaction.atomic
def apply_refund(payment, *, amount_refunded_rupees):
    """
    Record a refund Razorpay has already made.

    Called from the webhook rather than from our own refund call, so a refund
    issued by hand in the Razorpay dashboard shows up here too.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    payment.amount_refunded = amount_refunded_rupees
    payment.status = (
        Payment.Status.REFUNDED if payment.amount_refunded >= payment.amount
        else Payment.Status.PARTIALLY_REFUNDED
    )
    if payment.status == Payment.Status.REFUNDED:
        payment.payout_status = Payment.PayoutStatus.REFUNDED
    payment.save(update_fields=[
        'amount_refunded', 'status', 'payout_status', 'updated_at',
    ])

    booking = Booking.objects.select_for_update().get(pk=payment.booking_id)
    if payment.status == Payment.Status.REFUNDED:
        booking.payment_status = Booking.PaymentStatus.UNPAID
        booking.save(update_fields=['payment_status'])

    transaction.on_commit(lambda: _notify(
        'payment.refund_initiated',
        customer=payment.customer,
        booking=booking,
        context={'amount': _money(payment.amount_refunded, payment.currency)},
        data={'booking_id': booking.pk, 'payment_id': payment.pk},
    ))
    return payment


def refund_payment(payment, *, amount_rupees=None, reason=''):
    """
    Send money back to the customer, in full or in part.

    Refuses once the payment has been released to the vendor: at that point the
    platform no longer has the money to give back, and refunding anyway would
    leave the books short without anyone noticing.

    Razorpay is called first and our records follow, so a refund that the
    gateway rejects leaves nothing behind. The matching webhook arrives later
    and is harmless -- `apply_refund` writes the cumulative total either way.
    """
    from . import gateway

    if payment.status not in (Payment.Status.CAPTURED,
                              Payment.Status.PARTIALLY_REFUNDED):
        raise ValueError("Only a captured payment can be refunded.")
    if payment.payout_status == Payment.PayoutStatus.RELEASED:
        raise ValueError(
            "This payment was released to the vendor and can no longer be "
            "refunded."
        )

    refundable = payment.refundable_amount
    if refundable <= 0:
        raise ValueError("This payment has already been fully refunded.")

    amount = refundable if amount_rupees is None else Decimal(str(amount_rupees))
    if amount <= 0:
        raise ValueError("Enter a refund amount greater than zero.")
    if amount > refundable:
        raise ValueError(
            f"The most that can be refunded on this payment is {refundable}."
        )

    result = gateway.refund(
        payment.razorpay_payment_id,
        amount_paise=to_paise(amount),
        notes={'reason': reason[:255]} if reason else None,
    )

    # Razorpay reports this refund's own amount, so add it to what has already
    # gone back rather than overwriting the running total.
    applied = to_rupees(result.get('amount') or to_paise(amount))
    return apply_refund(
        payment, amount_refunded_rupees=payment.amount_refunded + applied
    )


@transaction.atomic
def release_to_vendor(payment, *, by=None):
    """
    Mark held money as owed to the vendor.

    This is the escrow release. It does not move funds -- vendor payouts are
    still made outside the platform -- but it is the record of the decision,
    and after it the money is no longer treated as refundable.

    Kept deliberately narrow: only a captured, un-released payment on a
    completed booking can be released, so nobody can release a booking that is
    still in progress or under dispute.
    """
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.CAPTURED:
        raise ValueError("Only a captured payment can be released.")
    if payment.payout_status != Payment.PayoutStatus.HELD:
        raise ValueError("This payment has already been released or refunded.")
    if payment.booking.status != Booking.Status.COMPLETED:
        raise ValueError("The booking is not completed yet.")

    # Releasing to a vendor with nowhere to send money records a debt that
    # cannot be settled, and nobody notices until the vendor asks. An
    # unverified account is only warned about in the dashboard -- a missing
    # one is refused here.
    from vendors.bank_services import payout_target

    vendor = payment.booking.vendor
    if vendor is None:
        raise ValueError("This booking has no vendor to release to.")
    if payout_target(vendor) is None:
        raise ValueError(
            "This vendor has not added payout details yet, so there is "
            "nowhere to send the money."
        )

    payment.payout_status = Payment.PayoutStatus.RELEASED
    payment.released_at = timezone.now()
    payment.save(update_fields=['payout_status', 'released_at', 'updated_at'])

    if vendor is not None:
        transaction.on_commit(lambda: _notify(
            'vendor.payout_processed',
            vendor=vendor,
            booking=payment.booking,
            context={'amount': _money(payment.amount, payment.currency)},
            data={'booking_id': payment.booking_id, 'payment_id': payment.pk},
        ))
    return payment


def open_payment_for(booking):
    """
    The order still awaiting payment on this booking, if there is one.

    Reused rather than replaced so that a customer who backs out of checkout
    and comes back does not leave a trail of orphan orders behind them.
    """
    return booking.payments.filter(
        status__in=[Payment.Status.CREATED, Payment.Status.ATTEMPTED]
    ).order_by('-created_at').first()


def amount_due_paise(booking):
    """What the booking is worth right now, in paise, from the server's own record."""
    return to_paise(booking.amount)


# ---------------------------------------------------------------- payouts out

def _payout_notify(payout, event_key, **context):
    return _notify(
        event_key,
        vendor=payout.vendor,
        booking=payout.payment.booking,
        context={'amount': _money(payout.amount, payout.currency), **context},
        data={'payout_id': payout.pk, 'booking_id': payout.payment.booking_id},
    )


def create_payout(payment, *, by=None):
    """
    Send a released payment out to the vendor through RazorpayX.

    Deliberately NOT wrapped in a single transaction. The Payout row, and the
    idempotency key on it, must be committed *before* RazorpayX is called --
    if the whole thing were atomic, a timeout would roll the row away, the
    retry would mint a fresh key, and the vendor would be paid twice.

    Safe to call more than once:

      * The OneToOne on Payment means two concurrent calls cannot create two
        payouts; the row is locked while the first decides what to do.
      * `pending` means the last attempt's outcome is unknown, so a retry
        replays the *same* idempotency key and RazorpayX returns the original
        payout rather than making a second one.
      * A definite failure means no money moved, so that retry -- and only
        that one -- gets a new key.

    Returns the Payout. Read `.status`: a queued payout is waiting on our own
    balance and has not reached the vendor yet.
    """
    from vendors.bank_services import payout_target
    from . import payoutx

    if not payoutx.is_enabled():
        raise ValueError("Payouts are not configured.")

    # --- phase 1: decide, and commit the key before anything leaves ---
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        if payment.status != Payment.Status.CAPTURED:
            raise ValueError("Only a captured payment can be paid out.")
        if payment.payout_status != Payment.PayoutStatus.RELEASED:
            raise ValueError("Release the payment before paying it out.")

        vendor = payment.booking.vendor
        account = payout_target(vendor)
        if account is None:
            raise ValueError("This vendor has no payout account.")
        if not account.can_receive_payout:
            raise ValueError(
                "This vendor's payout account is not verified yet, so money "
                "cannot be sent to it."
            )

        payout = Payout.objects.select_for_update().filter(
            payment=payment
        ).first()

        if payout is not None:
            if payout.status in Payout.IN_FLIGHT:
                # Already on its way. Returning rather than raising keeps a
                # double-clicked button harmless.
                return payout
            if payout.status == Payout.Status.PENDING:
                # Outcome unknown. Replay the same key -- RazorpayX will hand
                # back the original payout if one was made.
                pass
            elif payout.can_retry:
                # Definitively refused, so nothing moved and this is a new
                # transfer that needs its own key.
                payout.idempotency_key = payoutx.new_idempotency_key()
                payout.failure_reason = ''
            else:
                raise ValueError(
                    f"This payout is {payout.get_status_display().lower()}."
                )
        else:
            payout = Payout(
                payment=payment,
                vendor=vendor,
                amount=payment.amount,
                currency=payment.currency,
                idempotency_key=payoutx.new_idempotency_key(),
                is_live=payment.is_live,
            )

        payout.fund_account_id = account.razorpayx_fund_account_id
        payout.mode = payoutx.choose_mode(payout.amount)
        payout.attempts += 1
        payout.status = Payout.Status.PENDING
        payout.save()

    # --- phase 2: the call itself, outside any transaction ---
    try:
        result = payoutx.create_payout(
            fund_account_id=payout.fund_account_id,
            amount_paise=payout.amount_paise,
            idempotency_key=payout.idempotency_key,
            mode=payout.mode,
            reference_id=f"booking-{payment.booking_id}",
            narration=f"Booking {payment.booking_id}",
            notes={
                'booking_id': str(payment.booking_id),
                'payment_id': str(payment.pk),
                'vendor_id': str(payout.vendor_id),
            },
        )
    except payoutx.PayoutError as exc:
        # A retriable error means the outcome is unknown, so the row stays
        # PENDING with its key intact and the next attempt replays it. Only a
        # definite refusal is recorded as failed.
        with transaction.atomic():
            row = Payout.objects.select_for_update().get(pk=payout.pk)
            if exc.retriable:
                row.failure_reason = f"Unconfirmed: {exc}"[:2000]
            else:
                row.status = Payout.Status.FAILED
                row.failure_reason = str(exc)[:2000]
            row.save(update_fields=['status', 'failure_reason', 'updated_at'])
        raise

    return apply_payout_result(payout, result)


@transaction.atomic
def apply_payout_result(payout, result):
    """
    Record what RazorpayX says about a payout.

    Shared by the create call and the webhook, so a payout that finishes
    while nobody is looking ends up in exactly the same state.
    """
    payout = Payout.objects.select_for_update().get(pk=payout.pk)

    payout.razorpay_payout_id = result.get('id') or payout.razorpay_payout_id
    payout.utr = result.get('utr') or payout.utr
    payout.mode = result.get('mode') or payout.mode

    status = (result.get('status') or '').lower()
    if status in Payout.Status.values:
        payout.status = status

    failure = result.get('failure_reason') or result.get('status_details', {}).get('description')
    if failure:
        payout.failure_reason = str(failure)[:2000]

    if payout.status == Payout.Status.PROCESSED and payout.processed_at is None:
        payout.processed_at = timezone.now()

    payout.save()

    if payout.status == Payout.Status.PROCESSED:
        transaction.on_commit(lambda: _payout_notify(
            payout, 'vendor.payout_processed'))
    elif payout.status in (Payout.Status.FAILED, Payout.Status.REJECTED):
        transaction.on_commit(lambda: _payout_notify(
            payout, 'vendor.payout_failed',
            reason=payout.failure_reason or 'the bank rejected it'))
    elif payout.status == Payout.Status.REVERSED:
        # The bank sent it back. The money is ours again, so the payment
        # returns to held rather than staying released against a transfer
        # that did not stick.
        payment = Payment.objects.select_for_update().get(pk=payout.payment_id)
        payment.payout_status = Payment.PayoutStatus.HELD
        payment.released_at = None
        payment.save(update_fields=['payout_status', 'released_at', 'updated_at'])
        transaction.on_commit(lambda: _payout_notify(
            payout, 'vendor.payout_failed',
            reason='the transfer was reversed by the bank'))

    return payout


def payout_for(payment):
    return Payout.objects.filter(payment=payment).first()
