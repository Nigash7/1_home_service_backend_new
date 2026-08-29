"""
Registering a vendor's bank account with RazorpayX, and checking it is real.

Two jobs. Getting a fund account id, which is what payouts are actually sent
to. And the penny drop -- sending a rupee to see whose name the bank has on
the account, which is the only automatic way to catch a vendor typing someone
else's account number.
"""
import logging
import re
from difflib import SequenceMatcher

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from payments import payoutx

from .bank_models import VendorBankAccount

logger = logging.getLogger(__name__)

# Titles and suffixes banks add that say nothing about identity.
NAME_NOISE = re.compile(
    r'\b(mr|mrs|ms|miss|dr|shri|smt|sri|kumari|m/s|messrs)\b\.?',
    re.IGNORECASE,
)


def normalise_name(name):
    """
    Strip a name down to the part worth comparing.

    Banks return names in their own house style -- 'RAMESH KUMAR S',
    'Mr. Ramesh Kumar', 'KUMAR RAMESH'. Comparing raw strings would reject
    almost every genuine account.
    """
    name = NAME_NOISE.sub(' ', name or '')
    name = re.sub(r'[^a-zA-Z\s]', ' ', name)
    return ' '.join(name.lower().split())


def name_match_score(entered, registered):
    """
    0-1, how confident we are these are the same person.

    Word-set overlap first, because reordered names ('Kumar Ramesh' against
    'Ramesh Kumar') are common and are not a mismatch. Falls back to a
    character-level ratio, which catches initials and small spellings.
    """
    left = normalise_name(entered)
    right = normalise_name(registered)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_words = set(left.split())
    right_words = set(right.split())
    overlap = len(left_words & right_words) / max(
        len(left_words), len(right_words)
    )
    ratio = SequenceMatcher(None, left, right).ratio()
    return round(max(overlap, ratio), 4)


@transaction.atomic
def sync_fund_account(account, *, force=False):
    """
    Make sure RazorpayX knows about this bank account, and return its id.

    Cheap to call repeatedly: an account that already has an id is left
    alone unless `force` is set. The ids describe one specific account
    number, so `save_bank_account` clears them when the details change and
    this then creates fresh ones.
    """
    if not payoutx.is_enabled():
        return None

    account = VendorBankAccount.objects.select_for_update().get(pk=account.pk)
    if account.razorpayx_fund_account_id and not force:
        return account.razorpayx_fund_account_id

    vendor = account.vendor
    user = vendor.user

    if not account.razorpayx_contact_id:
        contact = payoutx.create_contact(
            name=user.get_full_name() or user.username,
            reference_id=f"vendor-{vendor.pk}",
            email=getattr(user, 'email', '') or '',
            phone=getattr(user, 'phone_number', '') or '',
        )
        account.razorpayx_contact_id = contact['id']

    fund_account = payoutx.create_fund_account(
        contact_id=account.razorpayx_contact_id,
        name=account.account_holder_name,
        ifsc=account.ifsc_code,
        account_number=account.account_number,
    )
    account.razorpayx_fund_account_id = fund_account['id']
    account.save(update_fields=[
        'razorpayx_contact_id', 'razorpayx_fund_account_id', 'updated_at',
    ])
    return account.razorpayx_fund_account_id


@transaction.atomic
def validate_account(account):
    """
    Penny drop, then decide what the answer means.

    Three outcomes worth telling apart:

      ACTIVE         the account is real and the name lines up. Auto-verified,
                     because a human re-checking this adds nothing.
      NAME_MISMATCH  real account, different name. Not necessarily fraud --
                     joint accounts and maiden names do this -- so it is put
                     in front of an admin rather than rejected.
      INVALID        the account does not exist. Never auto-verified.

    Verification is only ever granted here, never taken away, so a bank that
    does not return names cannot un-verify an account an admin approved.
    """
    if not payoutx.is_enabled():
        raise ValueError("Payouts are not configured, so accounts cannot be checked.")

    account = VendorBankAccount.objects.select_for_update().get(pk=account.pk)

    fund_account_id = account.razorpayx_fund_account_id
    if not fund_account_id:
        fund_account_id = sync_fund_account(account)
        account.refresh_from_db()

    account.validation_status = VendorBankAccount.ValidationStatus.PENDING
    account.save(update_fields=['validation_status', 'updated_at'])

    try:
        result = payoutx.validate_fund_account(
            fund_account_id=fund_account_id,
            notes={'vendor_id': str(account.vendor_id)},
        )
    except payoutx.PayoutError as exc:
        account.validation_status = VendorBankAccount.ValidationStatus.FAILED
        account.save(update_fields=['validation_status', 'updated_at'])
        logger.warning("vendors: penny drop failed for vendor %s: %s",
                       account.vendor_id, exc)
        raise

    return apply_validation_result(account, result)


@transaction.atomic
def apply_validation_result(account, result):
    """
    Record a validation outcome.

    Split out from `validate_account` because the same payload arrives by
    webhook when the bank answers slowly, and both paths must reach the same
    conclusion.
    """
    account = VendorBankAccount.objects.select_for_update().get(pk=account.pk)
    Status = VendorBankAccount.ValidationStatus

    results = result.get('results') or {}
    account.validation_id = result.get('id') or account.validation_id
    account.validated_at = timezone.now()

    bank_status = (results.get('account_status') or '').lower()
    registered = results.get('registered_name') or ''
    account.registered_name = registered[:160]

    if bank_status != 'active':
        account.validation_status = Status.INVALID
        account.name_match_score = None
        account.save()
        return account

    # No name back from the bank is not a mismatch -- some banks simply do
    # not return one. Treat it as checked-but-unnamed and let a human decide.
    if not registered:
        account.validation_status = Status.ACTIVE
        account.name_match_score = None
        account.save()
        return account

    score = name_match_score(account.account_holder_name, registered)
    account.name_match_score = score

    if score >= settings.RAZORPAYX_NAME_MATCH_THRESHOLD:
        account.validation_status = Status.ACTIVE
        # The bank has confirmed both the account and the name. That is a
        # stronger check than the manual one, so it stands in for it.
        if not account.is_verified:
            account.is_verified = True
            account.verified_at = timezone.now()
    else:
        account.validation_status = Status.NAME_MISMATCH

    account.save()
    return account
