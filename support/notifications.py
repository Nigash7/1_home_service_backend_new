"""
Support-ticket notifications.

One place that knows how to reach the right party for a ticket, so callers
(API views and the admin dashboard) don't have to branch on customer/vendor.
Everything here is best-effort — notify() already swallows its own errors.
"""


def _preview(text, limit=90):
    text = (text or '').strip().replace('\n', ' ')
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _context(ticket, **extra):
    ctx = {
        'ticket_id': ticket.id,
        'subject': ticket.subject,
        'category': ticket.get_category_display(),
        'requester_name': ticket.requester_name,
        'requester_type': ticket.get_raised_by_display(),
    }
    ctx.update(extra)
    return ctx


def notify_requester_of_reply(ticket, message):
    """Admin answered — ping whoever opened the ticket."""
    from notifications.services import notify

    ctx = _context(ticket, preview=_preview(message))
    if ticket.is_from_vendor:
        return notify('vendor.support_reply', vendor=ticket.vendor, context=ctx,
                      data={'ticket_id': ticket.id})
    return notify('support.reply', customer=ticket.customer, context=ctx,
                  data={'ticket_id': ticket.id})


def notify_requester_of_status(ticket):
    """Admin moved the ticket to Resolved/Closed etc."""
    from notifications.services import notify

    ctx = _context(ticket, status=ticket.get_status_display().lower())
    if ticket.is_from_vendor:
        return notify('vendor.support_status_changed', vendor=ticket.vendor,
                      context=ctx, data={'ticket_id': ticket.id})
    return notify('support.status_changed', customer=ticket.customer,
                  context=ctx, data={'ticket_id': ticket.id})


def notify_admins_new_ticket(ticket):
    """A customer or vendor opened a ticket — tell the support team."""
    from notifications.services import notify_admins

    return notify_admins(
        'admin.support_ticket',
        context=_context(ticket),
        data={'ticket_id': ticket.id},
    )


def notify_admins_of_reply(ticket, message):
    """The requester added a message to an existing ticket."""
    from notifications.services import notify_admins

    return notify_admins(
        'admin.support_reply',
        context=_context(ticket, preview=_preview(message)),
        data={'ticket_id': ticket.id},
    )
