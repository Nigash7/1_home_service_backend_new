"""
Tender notifications.

One place that knows who to tell about what, so callers -- the API views and
the admin dashboard -- never have to assemble a context dict themselves.
Everything here is best-effort: notify() already swallows its own errors, and
a tender must never fail to publish because a push did not go out.
"""


def _money(value):
    """Rupee figure the way both apps show it."""
    try:
        return f"Rs {float(value):,.0f}"
    except (TypeError, ValueError):
        return ""


def _context(tender, **extra):
    ctx = {
        'tender_id': tender.id,
        'tender_code': tender.code,
        'tender_title': tender.title,
        'category_name': tender.category.name if tender.category_id else '',
        'budget': _money(tender.expected_budget),
        'location': tender.location_label,
        'customer_name': str(tender.customer),
        'customer_phone': tender.contact_phone or (
            tender.customer.user.phone_number or ''
        ),
        'bid_deadline': tender.bid_deadline.strftime('%d %b') if tender.bid_deadline else '',
    }
    ctx.update(extra)
    return ctx


def _data(tender, **extra):
    """Payload the apps use to deep-link straight to the tender."""
    return dict({'tender_id': tender.id}, **extra)


# ------------------------------------------------------------ customer side
def notify_customer_submitted(tender):
    """Customer published — it is now queued for admin review."""
    from notifications.services import notify

    return notify('tender.submitted', customer=tender.customer,
                  context=_context(tender), data=_data(tender))


def notify_customer_approved(tender, vendor_count):
    """Admin approved it and vendors can now see it."""
    from notifications.services import notify

    return notify('tender.approved', customer=tender.customer,
                  context=_context(tender, vendor_count=vendor_count),
                  data=_data(tender))


def notify_customer_rejected(tender):
    """Admin sent it back. The reason is the whole point of the message."""
    from notifications.services import notify

    reason = tender.rejection_reason or 'Please review the details and post it again.'
    return notify('tender.rejected', customer=tender.customer,
                  context=_context(tender, reason=reason), data=_data(tender))


def notify_customer_new_bid(tender, bid):
    """A vendor quoted — tell the customer there is something to compare."""
    from notifications.services import notify

    return notify(
        'tender.bid_received', customer=tender.customer,
        context=_context(
            tender,
            vendor_name=bid.vendor.display_name,
            amount=_money(bid.amount),
            bid_count=tender.active_bids.count(),
        ),
        data=_data(tender, bid_id=bid.id),
    )


def notify_customer_awarded(tender, bid):
    """Deal confirmed, from the customer's side."""
    from notifications.services import notify

    return notify(
        'tender.awarded', customer=tender.customer,
        context=_context(
            tender,
            vendor_name=bid.vendor.display_name,
            amount=_money(bid.amount),
            vendor_phone=bid.vendor.user.phone_number or '',
        ),
        data=_data(tender, bid_id=bid.id),
    )


def notify_customer_work_started(tender):
    from notifications.services import notify

    vendor = tender.awarded_vendor
    return notify(
        'tender.work_started', customer=tender.customer,
        context=_context(tender, vendor_name=vendor.display_name if vendor else ''),
        data=_data(tender),
    )


def notify_customer_progress(tender, update):
    from notifications.services import notify

    percent = f"{update.percent_complete}% done." if update.percent_complete is not None else ''
    return notify(
        'tender.progress_update', customer=tender.customer,
        context=_context(tender, vendor_name=update.vendor.display_name, percent=percent),
        data=_data(tender, update_id=update.id),
    )


def notify_customer_milestone_reached(tender, milestone):
    from notifications.services import notify

    vendor = tender.awarded_vendor
    return notify(
        'tender.milestone_reached', customer=tender.customer,
        context=_context(
            tender,
            vendor_name=vendor.display_name if vendor else '',
            milestone_title=milestone.title,
            amount=_money(milestone.amount),
        ),
        data=_data(tender, milestone_id=milestone.id),
    )


def notify_customer_completed(tender):
    from notifications.services import notify

    vendor = tender.awarded_vendor
    return notify(
        'tender.completed', customer=tender.customer,
        context=_context(tender, vendor_name=vendor.display_name if vendor else ''),
        data=_data(tender),
    )


# -------------------------------------------------------------- vendor side
def notify_vendors_of_new_tender(tender):
    """
    Fan the freshly approved tender out to every vendor who can bid on it.

    Returns how many vendors were told, which the approval screen reports
    back to the admin and the customer.
    """
    from notifications.services import notify

    vendors = list(tender.matching_vendors())
    ctx = _context(tender)
    for vendor in vendors:
        notify('tender.new_match', vendor=vendor, context=ctx, data=_data(tender))
    return len(vendors)


def notify_vendor_won(tender, bid):
    from notifications.services import notify

    return notify(
        'tender.bid_accepted', vendor=bid.vendor,
        context=_context(tender, amount=_money(bid.amount)),
        data=_data(tender, bid_id=bid.id),
    )


def notify_vendors_lost(tender, losing_bids):
    """Everyone who quoted and did not win. Silence would be worse."""
    from notifications.services import notify

    for bid in losing_bids:
        notify('tender.bid_rejected', vendor=bid.vendor, context=_context(tender),
               data=_data(tender, bid_id=bid.id))


def notify_vendors_tender_closed(tender, bids, reason=''):
    """The customer pulled the tender while bids were live."""
    from notifications.services import notify

    ctx = _context(tender, reason=reason or '')
    for bid in bids:
        notify('tender.closed_vendor', vendor=bid.vendor, context=ctx,
               data=_data(tender))


def notify_vendor_milestone_paid(tender, milestone):
    from notifications.services import notify

    vendor = tender.awarded_vendor
    if vendor is None:
        return None
    return notify(
        'tender.milestone_paid', vendor=vendor,
        context=_context(
            tender, milestone_title=milestone.title, amount=_money(milestone.amount)
        ),
        data=_data(tender, milestone_id=milestone.id),
    )


# --------------------------------------------------------------- admin side
def notify_admins_submitted(tender):
    """A tender is waiting for someone to approve it."""
    from notifications.services import notify_admins

    return notify_admins('admin.tender_submitted', context=_context(tender),
                         data=_data(tender))


def notify_admins_awarded(tender, bid):
    from notifications.services import notify_admins

    return notify_admins(
        'admin.tender_awarded',
        context=_context(tender, vendor_name=bid.vendor.display_name,
                         amount=_money(bid.amount)),
        data=_data(tender),
    )


def notify_admins_completed(tender):
    from notifications.services import notify_admins

    vendor = tender.awarded_vendor
    return notify_admins(
        'admin.tender_completed',
        context=_context(tender, vendor_name=vendor.display_name if vendor else ''),
        data=_data(tender),
    )


def notify_admins_cancelled(tender):
    from notifications.services import notify_admins

    return notify_admins(
        'admin.tender_cancelled',
        context=_context(tender, reason=tender.cancellation_reason or ''),
        data=_data(tender),
    )
