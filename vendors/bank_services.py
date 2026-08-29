"""
Applying a change to where a vendor gets paid.

One place, because the two rules that matter here are easy to forget at a
call site and expensive to get wrong: verification must be cleared whenever
the details move, and every move must leave a trace.
"""
import logging

from django.conf import settings
from django.db import transaction

from . import payout_services
from .bank_models import (
    VendorBankAccount, VendorBankAccountChange, mask_account_number,
)

logger = logging.getLogger(__name__)


def _notify_vendor(vendor, *, is_first_time, masked):
    """
    Tell the vendor their payout account changed.

    Sent even when they made the change themselves -- if someone else did it
    with a stolen session, this message is how the real vendor finds out.
    """
    try:
        from notifications.services import notify
        return notify(
            'vendor.bank_account_changed',
            vendor=vendor,
            context={
                'account': masked,
                'action': 'added' if is_first_time else 'updated',
            },
            data={'screen': 'bank_account'},
        )
    except Exception:
        logger.exception("vendors: bank-change notification failed")
        return None


@transaction.atomic
def save_bank_account(vendor, data, *, changed_by=None):
    """
    Create or replace a vendor's payout details.

    Returns (account, changed) -- `changed` is False when the submitted
    details are identical to what was already stored, which happens whenever
    someone opens the form and saves without editing. Treating that as a real
    change would clear their verified badge for nothing.

    Account numbers are never written to the log here, deliberately.
    """
    account = VendorBankAccount.objects.select_for_update().filter(
        vendor=vendor
    ).first()

    before = account.snapshot() if account else None
    old_masked = account.masked_account_number if account else ''
    old_ifsc = account.ifsc_code if account else ''
    old_upi = account.upi_id if account else ''

    if account is None:
        account = VendorBankAccount(vendor=vendor)

    for field, value in data.items():
        setattr(account, field, value)

    if before is not None and account.snapshot() == before:
        account.save()
        return account, False

    # The details moved, so any previous verification no longer applies to
    # this account. Re-checking is the whole point of the flag.
    account.is_verified = False
    account.verified_at = None
    account.verified_by = None

    # The fund account id points at the bank account that was here before.
    # Keeping it would send the next payout to the old bank -- exactly the
    # failure this whole flow exists to prevent. The contact id is kept: it
    # identifies the vendor, not the account, and outlives any change.
    account.razorpayx_fund_account_id = ''
    account.validation_status = VendorBankAccount.ValidationStatus.NOT_CHECKED
    account.validation_id = ''
    account.registered_name = ''
    account.name_match_score = None
    account.validated_at = None
    account.save()

    VendorBankAccountChange.objects.create(
        vendor=vendor,
        old_account_masked=old_masked,
        new_account_masked=account.masked_account_number,
        old_ifsc=old_ifsc,
        new_ifsc=account.ifsc_code,
        old_upi=old_upi,
        new_upi=account.upi_id,
        changed_by=changed_by,
    )

    logger.info(
        "vendors: payout account %s for vendor %s",
        'added' if not old_masked else 'changed', vendor.pk,
    )

    masked = account.masked_account_number
    is_first = not old_masked
    account_pk = account.pk
    transaction.on_commit(
        lambda: _notify_vendor(vendor, is_first_time=is_first, masked=masked)
    )
    transaction.on_commit(lambda: _check_with_bank(account_pk))
    return account, True


def _check_with_bank(account_pk):
    """
    Register the account with RazorpayX and penny-drop it.

    Best-effort and after commit: the vendor's details are saved either way,
    and a RazorpayX outage must not lose them. A failed check just leaves the
    account needing the manual verification that was the only option before.
    """
    from payments import payoutx

    if not (payoutx.is_enabled() and settings.RAZORPAYX_VALIDATE_ACCOUNTS):
        return
    try:
        account = VendorBankAccount.objects.get(pk=account_pk)
        payout_services.validate_account(account)
    except Exception:
        logger.exception("vendors: could not check account %s with the bank",
                         account_pk)


@transaction.atomic
def verify_bank_account(vendor, *, by=None):
    """Admin confirms these details belong to this vendor."""
    from django.utils import timezone

    account = VendorBankAccount.objects.select_for_update().filter(
        vendor=vendor
    ).first()
    if account is None:
        raise ValueError("This vendor has not added payout details yet.")

    account.is_verified = True
    account.verified_at = timezone.now()
    account.verified_by = by
    account.save(update_fields=['is_verified', 'verified_at', 'verified_by',
                                'updated_at'])
    return account


def payout_target(vendor):
    """
    Where this vendor's money would go, or None.

    Used before releasing held money: releasing to a vendor with nowhere to
    send it records a debt with no way to settle it.
    """
    if vendor is None:
        return None
    return getattr(vendor, 'bank_account', None)
