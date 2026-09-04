"""
What choosing a bid means, in one place.

The customer app, the admin dashboard and the Razorpay webhook all reach the
same two moments -- a bid is picked, and a bid is confirmed -- and all three
have to have identical consequences. Splitting them across three callers is
how a tender ends up awarded to a vendor who was never told, so the whole
sequence lives here and the callers only decide when to run it.

The money half is deliberately narrow: the platform charges the customer a
percentage of the bid they picked (TenderSettings.confirmation_fee_percent)
and holds it. Nothing here pays a vendor, and nothing here touches the
milestones -- those are still settled between customer and vendor directly.
"""
import logging

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from payments import gateway

from . import notifications as notify_tender
from .models import (
    Tender,
    TenderBid,
    TenderConfirmationFee,
    TenderSettings,
)

logger = logging.getLogger(__name__)


def _is_live():
    """False for rzp_test_* keys, so test takings never look like real ones."""
    return bool(getattr(django_settings, 'RAZORPAY_IS_LIVE', False))


# --------------------------------------------------------------- the choice
@transaction.atomic
def select_bid(bid):
    """
    Record that the customer has picked `bid`.

    Returns the TenderConfirmationFee they now owe, or None when the fee comes
    to nothing -- a zero rate, or the fee switched off -- in which case the
    tender is awarded here and now, because there is nothing left to confirm.

    Losing bids are deliberately *not* rejected yet and the winning vendor is
    not told. Until the fee is paid the customer has chosen, not committed,
    and a selection they abandon has to leave the tender exactly as it was.
    """
    tender = Tender.objects.select_for_update().get(pk=bid.tender_id)

    if tender.status != Tender.Status.OPEN:
        raise ValueError(
            f"This tender is {tender.get_status_display()} and cannot be awarded."
        )
    if bid.status != TenderBid.Status.SUBMITTED:
        raise ValueError("That bid is no longer available to accept.")

    settings_row = TenderSettings.get_solo()
    amount = settings_row.fee_on(bid.amount)

    if amount <= 0:
        confirm_award(tender, bid)
        return None

    fee = TenderConfirmationFee.objects.create(
        tender=tender,
        bid=bid,
        percent=settings_row.effective_percent,
        bid_amount=bid.amount,
        amount=amount,
        is_live=_is_live(),
    )

    bid.status = TenderBid.Status.SELECTED
    bid.save(update_fields=['status', 'updated_at'])

    tender.status = Tender.Status.PENDING_CONFIRMATION
    tender.save(update_fields=['status', 'updated_at'])

    transaction.on_commit(
        lambda: notify_tender.notify_customer_confirmation_due(tender, bid, fee)
    )
    return fee


@transaction.atomic
def release_selection(tender, *, reason=''):
    """
    Put a held selection back: the bid returns to the pile, the tender
    reopens and the unpaid fee is closed off.

    The way out for a customer who picked the wrong vendor, and the tidy-up
    when a tender is cancelled with a selection still hanging.
    """
    tender = Tender.objects.select_for_update().get(pk=tender.pk)
    if tender.status != Tender.Status.PENDING_CONFIRMATION:
        raise ValueError("There is no held selection on this tender.")

    tender.bids.filter(status=TenderBid.Status.SELECTED).update(
        status=TenderBid.Status.SUBMITTED, decided_at=None
    )
    cancel_open_fees(tender, reason=reason)

    tender.status = Tender.Status.OPEN
    tender.save(update_fields=['status', 'updated_at'])
    return tender


def cancel_open_fees(tender, *, reason=''):
    """Close any fee still owed here. Safe to call when there is none."""
    return tender.confirmation_fees.filter(
        status=TenderConfirmationFee.Status.PENDING
    ).update(
        status=TenderConfirmationFee.Status.CANCELLED,
        closed_at=timezone.now(),
        notes=reason or 'Selection released.',
    )


# ---------------------------------------------------------------- the award
@transaction.atomic
def confirm_award(tender, bid, *, fee=None):
    """
    The deal, done: the bid is accepted, every other live bid is turned down,
    and all four sides are told.

    Called once the confirmation fee is paid -- straight from select_bid when
    there is no fee to pay, and from the dashboard when an admin awards a
    tender on the customer's behalf.
    """
    now = timezone.now()
    live = [TenderBid.Status.SUBMITTED, TenderBid.Status.SELECTED]
    losing_bids = list(
        tender.bids.exclude(pk=bid.pk)
        .filter(status__in=live)
        .select_related('vendor__user')
    )

    bid.status = TenderBid.Status.ACCEPTED
    bid.decided_at = now
    bid.save(update_fields=['status', 'decided_at', 'updated_at'])

    tender.bids.exclude(pk=bid.pk).filter(status__in=live).update(
        status=TenderBid.Status.REJECTED, decided_at=now
    )

    tender.awarded_bid = bid
    tender.status = Tender.Status.AWARDED
    tender.awarded_at = now
    tender.save(update_fields=['awarded_bid', 'status', 'awarded_at', 'updated_at'])

    # After the rows are safely committed, so a push failure can never undo
    # the award the customer has just paid for.
    transaction.on_commit(lambda: notify_tender.notify_customer_awarded(tender, bid))
    transaction.on_commit(lambda: notify_tender.notify_vendor_won(tender, bid))
    transaction.on_commit(lambda: notify_tender.notify_vendors_lost(tender, losing_bids))
    transaction.on_commit(lambda: notify_tender.notify_admins_awarded(tender, bid))
    return tender


@transaction.atomic
def waive_fee(fee, *, reason=''):
    """
    Let a tender through without the fee -- settled off-platform, or forgiven.

    Kept apart from cancelling so the books can tell "they never went ahead"
    from "we let this one go", which would otherwise be the same row.
    """
    fee = TenderConfirmationFee.objects.select_for_update().get(pk=fee.pk)
    if fee.status != TenderConfirmationFee.Status.PENDING:
        return False
    fee.status = TenderConfirmationFee.Status.WAIVED
    fee.closed_at = timezone.now()
    fee.notes = reason or 'Waived by an admin.'
    fee.save(update_fields=['status', 'closed_at', 'notes', 'updated_at'])
    return True


# -------------------------------------------------------------------- money
def open_order_for(fee):
    """
    A Razorpay order for this fee, opening one only if it has none.

    The amount is snapshotted on the fee and never moves, so an order opened
    for an earlier attempt is still exactly right. Reusing it keeps a customer
    who backs out of Checkout and comes back from leaving a trail of orphan
    orders behind them.
    """
    if fee.razorpay_order_id:
        return fee

    order = gateway.create_order(
        amount_paise=fee.amount_paise,
        receipt=f"tenderfee-{fee.pk}",
        notes={
            'kind': 'tender_confirmation_fee',
            'tender_id': str(fee.tender_id),
            'bid_id': str(fee.bid_id),
            'fee_id': str(fee.pk),
        },
    )
    fee.razorpay_order_id = order['id']
    fee.is_live = _is_live()
    fee.save(update_fields=['razorpay_order_id', 'is_live', 'updated_at'])
    return fee


def mark_fee_paid(fee, *, payment_id='', method='', signature=''):
    """
    Record the fee as paid and award the tender.

    Returns True only for the call that actually captured it. The browser
    callback and the webhook routinely arrive together for the same fee, and
    both would otherwise go on to award the tender and push the same four
    notifications a second time.
    """
    with transaction.atomic():
        fee = TenderConfirmationFee.objects.select_for_update().select_related(
            'tender', 'bid__vendor__user'
        ).get(pk=fee.pk)

        if not fee.mark_captured(
            payment_id=payment_id, method=method, signature=signature
        ):
            return False

        tender = fee.tender
        if tender.status != Tender.Status.PENDING_CONFIRMATION:
            # The tender moved on under us -- cancelled, or awarded by an
            # admin -- and the money still arrived. Leave it captured and say
            # so loudly: whether to refund is a decision for a person, not a
            # race.
            logger.error(
                "tenders: confirmation fee %s paid on tender %s in state %s",
                fee.pk, tender.pk, tender.status,
            )
            return True

        confirm_award(tender, fee.bid, fee=fee)

        transaction.on_commit(
            lambda: notify_tender.notify_customer_confirmation_paid(tender, fee.bid, fee)
        )
        transaction.on_commit(
            lambda: notify_tender.notify_admins_confirmation_paid(tender, fee.bid, fee)
        )
    return True


def mark_fee_failed(fee, *, reason='', payment_id=''):
    """Record a failed attempt. The fee stays owed and can be tried again."""
    if fee.status != TenderConfirmationFee.Status.PENDING:
        return False
    fee.failure_reason = (reason or '')[:2000]
    if payment_id:
        fee.razorpay_payment_id = payment_id
    fee.save(update_fields=['failure_reason', 'razorpay_payment_id', 'updated_at'])
    return True


def fee_for_order(order_id):
    """The fee a Razorpay order belongs to, if it is one of ours."""
    if not order_id:
        return None
    return TenderConfirmationFee.objects.select_related(
        'tender', 'bid__vendor__user'
    ).filter(razorpay_order_id=order_id).first()
