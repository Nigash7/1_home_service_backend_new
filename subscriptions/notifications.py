"""
Subscription notifications.

One place that knows what a vendor is told about their plan, so the API views,
the dashboard and the services layer never assemble a context dict themselves.
Everything here is best-effort: notify() swallows its own errors, and a plan
must never fail to start because a push did not go out.
"""


def _term(subscription):
    """The tail of the sentence: ' until 30 Sep 2026', or '' for no expiry."""
    if subscription is None or subscription.end_date is None:
        return ''
    return f" until {subscription.end_date.strftime('%d %b %Y')}"


def _context(subscription, **extra):
    ctx = {
        'plan_name': subscription.plan.name,
        'term': _term(subscription),
        'start_date': subscription.start_date.strftime('%d %b %Y'),
        'end_date': (
            subscription.end_date.strftime('%d %b %Y')
            if subscription.end_date else ''
        ),
    }
    ctx.update(extra)
    return ctx


def _data(subscription):
    return {
        'subscription_id': subscription.id,
        'plan_id': subscription.plan_id,
    }


def notify_subscription_started(subscription):
    """A term has begun -- assigned by an admin, or the free tier on signup."""
    from notifications.services import notify

    return notify(
        'vendor.subscription_started',
        vendor=subscription.vendor,
        context=_context(subscription),
        data=_data(subscription),
    )


def notify_upgrade_approved(subscription, upgrade_request):
    """The vendor asked to move up and an admin said yes."""
    from notifications.services import notify

    return notify(
        'vendor.subscription_upgrade_approved',
        vendor=subscription.vendor,
        context=_context(subscription, request_id=upgrade_request.id),
        data=_data(subscription),
    )


def notify_upgrade_rejected(upgrade_request):
    """Turned down. The reason is the admin's, verbatim, if they gave one."""
    from notifications.services import notify

    return notify(
        'vendor.subscription_upgrade_rejected',
        vendor=upgrade_request.vendor,
        context={
            'plan_name': upgrade_request.plan.name,
            'reason': upgrade_request.review_note or '',
        },
        data={'request_id': upgrade_request.id, 'plan_id': upgrade_request.plan_id},
    )


def notify_subscription_ended(subscription):
    """A term was cancelled or has run out."""
    from notifications.services import notify

    return notify(
        'vendor.subscription_ended',
        vendor=subscription.vendor,
        context=_context(subscription),
        data=_data(subscription),
    )
