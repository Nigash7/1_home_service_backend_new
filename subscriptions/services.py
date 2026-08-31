"""
The rules behind granting a vendor a subscription.

Kept out of the views so the dashboard, the Django admin and anything added
later all end a vendor's old term the same way.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import notifications as subscription_notify
from .models import (
    SubscriptionPlan,
    SubscriptionUpgradeRequest,
    VendorSubscription,
)


class SubscriptionError(Exception):
    """Raised when a subscription cannot be granted as asked."""


@transaction.atomic
def assign_plan(
    vendor,
    plan,
    *,
    start_date=None,
    end_date=None,
    amount_paid=None,
    payment_reference='',
    notes='',
    granted_by=None,
    notify=True,
):
    """
    Puts `vendor` on `plan` and returns the new subscription.

    Everything the vendor is holding is cancelled first -- the term they are
    serving and any renewal queued behind it. One live subscription per
    vendor is the whole point, and a queued term left in place would quietly
    put them back on the old plan weeks later.

    `end_date` is worked out from the plan's billing period unless one is
    passed in, so a lifetime plan gets no end date and a monthly one gets 30
    days. Pass `end_date` explicitly to grant an odd-length term.
    """
    if plan is None:
        raise SubscriptionError('Pick a plan.')

    start_date = start_date or timezone.localdate()

    if end_date is None:
        end_date = plan.term_end_date(start_date)
    elif end_date < start_date:
        raise SubscriptionError('The end date cannot fall before the start date.')

    held = [
        VendorSubscription.objects.active_for(vendor),
        *VendorSubscription.objects.queued().filter(vendor=vendor),
    ]
    for subscription in held:
        if subscription:
            subscription.cancel(reason=f'Replaced by {plan.name}')

    subscription = VendorSubscription.objects.create(
        vendor=vendor,
        plan=plan,
        status=VendorSubscription.Status.ACTIVE,
        start_date=start_date,
        end_date=end_date,
        amount_paid=plan.price if amount_paid is None else amount_paid,
        payment_reference=payment_reference,
        notes=notes,
        created_by=granted_by,
    )
    # An approved upgrade tells the vendor its own, better story, so callers
    # that follow up with their own message turn this one off.
    if notify:
        subscription_notify.notify_subscription_started(subscription)
    return subscription


@transaction.atomic
def renew(subscription, *, granted_by=None, amount_paid=None, payment_reference=''):
    """
    Adds another term on the same plan.

    A term still running is picked up the day after it ends and left queued,
    so renewing early neither costs the vendor the days they have left nor
    drops them off the plan in the meantime -- the running term stays live
    and the new one takes over on its own. A term that has already ended
    restarts from today.

    This deliberately does not go through `assign_plan`: that one clears
    whatever the vendor holds, which is right for a plan *change* and wrong
    for a continuation of the plan they are already on.
    """
    vendor = subscription.vendor
    plan = subscription.plan

    if subscription.is_active and subscription.is_lifetime:
        raise SubscriptionError('A plan with no expiry has nothing to renew.')

    # Renewing an old term while the vendor sits on something else would
    # quietly hand them two live plans. Changing plans is assign_plan's job.
    current = VendorSubscription.objects.active_for(vendor)
    if current and current.id != subscription.id:
        raise SubscriptionError(
            f'This vendor is on {current.plan.name} now. Change their plan '
            f'instead of renewing an older term.'
        )

    queued = VendorSubscription.objects.queued_for(vendor)
    if queued:
        raise SubscriptionError(
            f'A {queued.plan.name} term is already queued from {queued.start_date}.'
        )

    if subscription.is_active and subscription.end_date:
        start_date = subscription.end_date + timedelta(days=1)
    else:
        start_date = timezone.localdate()

    renewed = VendorSubscription.objects.create(
        vendor=vendor,
        plan=plan,
        status=VendorSubscription.Status.ACTIVE,
        start_date=start_date,
        end_date=plan.term_end_date(start_date),
        amount_paid=plan.price if amount_paid is None else amount_paid,
        payment_reference=payment_reference,
        notes=f'Renewal of #{subscription.id}',
        created_by=granted_by,
    )
    subscription_notify.notify_subscription_started(renewed)
    return renewed


def default_plan():
    """
    The plan a vendor lands on when nobody picked one, or None if an admin
    has not nominated a default yet.
    """
    return SubscriptionPlan.objects.filter(is_default=True, is_active=True).first()


def ensure_default_subscription(vendor, granted_by=None):
    """
    Puts a vendor on the default plan if they hold nothing live.

    Called when a vendor signs up, and again by the backfill command for the
    vendors who registered before plans existed. Safe to call twice, and a
    no-op when no default plan has been nominated -- a missing plan must
    never be the reason a signup fails.
    """
    if VendorSubscription.objects.active_for(vendor):
        return None

    plan = default_plan()
    if plan is None:
        return None

    return assign_plan(vendor, plan, granted_by=granted_by)


# ---------------------------------------------------------------------------
# Upgrade requests -- a vendor asks, an admin decides.
# ---------------------------------------------------------------------------

def request_upgrade(vendor, plan, note=''):
    """
    Records a vendor's interest in `plan` and returns the request.

    Deliberately does not touch their subscription: approving is what starts
    a term. Refused when the vendor is already on the plan, when the plan is
    not on offer, or when they are already waiting on an answer -- one open
    question at a time keeps the admin queue meaningful.
    """
    if plan is None:
        raise SubscriptionError('Pick a plan.')
    if not plan.is_active:
        raise SubscriptionError(f'{plan.name} is not on offer right now.')

    current = VendorSubscription.objects.active_for(vendor)
    if current and current.plan_id == plan.id:
        raise SubscriptionError(f'You are already on {plan.name}.')

    pending = SubscriptionUpgradeRequest.objects.pending_for(vendor)
    if pending:
        raise SubscriptionError(
            f'Your request for {pending.plan.name} is still being reviewed.'
        )

    return SubscriptionUpgradeRequest.objects.create(
        vendor=vendor, plan=plan, note=note, quoted_price=plan.price,
    )


@transaction.atomic
def approve_request(
    upgrade_request,
    *,
    reviewed_by=None,
    amount_paid=None,
    payment_reference='',
    review_note='',
):
    """Grants the plan the vendor asked for and closes the request."""
    if not upgrade_request.is_open:
        raise SubscriptionError('That request has already been answered.')

    subscription = assign_plan(
        upgrade_request.vendor,
        upgrade_request.plan,
        amount_paid=amount_paid,
        payment_reference=payment_reference,
        notes=f'Approved upgrade request #{upgrade_request.id}',
        granted_by=reviewed_by,
        notify=False,
    )

    upgrade_request.status = SubscriptionUpgradeRequest.Status.APPROVED
    upgrade_request.reviewed_by = reviewed_by
    upgrade_request.reviewed_at = timezone.now()
    upgrade_request.review_note = review_note
    upgrade_request.granted_subscription = subscription
    upgrade_request.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'review_note',
        'granted_subscription',
    ])
    subscription_notify.notify_upgrade_approved(subscription, upgrade_request)
    return subscription


def reject_request(upgrade_request, *, reviewed_by=None, reason=''):
    """Turns the request down. The vendor stays on whatever they hold."""
    if not upgrade_request.is_open:
        raise SubscriptionError('That request has already been answered.')

    upgrade_request.status = SubscriptionUpgradeRequest.Status.REJECTED
    upgrade_request.reviewed_by = reviewed_by
    upgrade_request.reviewed_at = timezone.now()
    upgrade_request.review_note = reason
    upgrade_request.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'review_note',
    ])
    subscription_notify.notify_upgrade_rejected(upgrade_request)
    return upgrade_request


def withdraw_request(upgrade_request):
    """The vendor changed their mind before anyone looked at it."""
    if not upgrade_request.is_open:
        raise SubscriptionError('That request has already been answered.')

    upgrade_request.status = SubscriptionUpgradeRequest.Status.WITHDRAWN
    upgrade_request.save(update_fields=['status'])
    return upgrade_request
