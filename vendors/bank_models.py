"""
Where a vendor's money is sent.

Kept in its own module rather than piled into `models.py`, because payout
details have different rules from the rest of a vendor profile: they are
never returned in full over the API, and every change is recorded.
"""
import re

from django.conf import settings
from django.db import models

# Indian bank IFSC: four letters, a zero, then six alphanumerics.
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')

# Indian account numbers run 9-18 digits depending on the bank.
ACCOUNT_NUMBER_RE = re.compile(r'^\d{9,18}$')

# UPI ids look like name@bank. Deliberately loose -- handles vary a lot.
UPI_RE = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$')


def mask_account_number(number):
    """
    '123456789012' -> 'XXXXXXXX9012'

    Everything the app and the dashboard show goes through this. A vendor
    recognises their own account from the last four; nobody else gains
    anything from seeing them.
    """
    number = (number or '').strip()
    if len(number) <= 4:
        return 'X' * len(number)
    return 'X' * (len(number) - 4) + number[-4:]


class VendorBankAccount(models.Model):
    """
    A vendor's payout destination, entered by the vendor in their own app.

    One per vendor -- changing where money goes replaces what was there and
    leaves a `VendorBankAccountChange` row behind, so "the payout went to the
    wrong account" is a question with an answer.

    `is_verified` exists because a bank account nobody has checked is a typo
    waiting to send money to a stranger. It is cleared automatically whenever
    the details change: without that, someone who got hold of a vendor's login
    could point payouts at their own bank and keep the verified badge.
    """

    class AccountType(models.TextChoices):
        SAVINGS = 'SAVINGS', 'Savings'
        CURRENT = 'CURRENT', 'Current'

    vendor = models.OneToOneField(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='bank_account'
    )

    account_holder_name = models.CharField(
        max_length=120,
        help_text="Exactly as it appears on the bank's records",
    )
    account_number = models.CharField(max_length=18)
    ifsc_code = models.CharField(max_length=11)
    bank_name = models.CharField(max_length=120, blank=True)
    branch_name = models.CharField(max_length=120, blank=True)
    account_type = models.CharField(
        max_length=10, choices=AccountType.choices, default=AccountType.SAVINGS
    )

    # Many vendors would rather be paid by UPI than by transfer. Optional, and
    # kept alongside rather than instead of the account -- UPI limits mean a
    # large payout still has to go to the bank.
    upi_id = models.CharField(max_length=64, blank=True)

    # ---------- RazorpayX ----------
    # Money is sent to a fund account id, not to a raw account number, so
    # these two are what payouts actually use. Cleared whenever the details
    # change, because they describe the old account.
    razorpayx_contact_id = models.CharField(max_length=64, blank=True)
    razorpayx_fund_account_id = models.CharField(max_length=64, blank=True)

    class ValidationStatus(models.TextChoices):
        NOT_CHECKED = 'NOT_CHECKED', 'Not checked'
        PENDING = 'PENDING', 'Check in progress'
        ACTIVE = 'ACTIVE', 'Account is real'
        INVALID = 'INVALID', 'Account is not valid'
        NAME_MISMATCH = 'NAME_MISMATCH', 'Name does not match'
        FAILED = 'FAILED', 'Check could not be completed'

    validation_status = models.CharField(
        max_length=15, choices=ValidationStatus.choices,
        default=ValidationStatus.NOT_CHECKED,
        help_text="Result of the penny-drop check against the bank",
    )
    validation_id = models.CharField(max_length=64, blank=True)
    registered_name = models.CharField(
        max_length=160, blank=True,
        help_text="The name the bank holds against this account",
    )
    name_match_score = models.FloatField(
        null=True, blank=True,
        help_text="0-1, how closely registered_name matches what was entered",
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    is_verified = models.BooleanField(
        default=False,
        help_text="An admin has confirmed these details belong to this vendor",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='verified_bank_accounts',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'vendor bank account'

    def __str__(self):
        # Never the full number -- this string ends up in admin logs.
        return f"{self.vendor} — {self.masked_account_number}"

    @property
    def masked_account_number(self):
        return mask_account_number(self.account_number)

    @property
    def is_payable(self):
        """Whether money can actually be sent here."""
        return bool(self.account_number and self.ifsc_code and self.is_verified)

    @property
    def can_receive_payout(self):
        """
        Whether RazorpayX has everything it needs to send here.

        Verification is a human saying the details look right; this is the
        machine having a fund account to pay into. Both are required.
        """
        return bool(self.razorpayx_fund_account_id and self.is_verified)

    @property
    def is_validated(self):
        """The bank confirmed the account exists and the name lines up."""
        return self.validation_status == self.ValidationStatus.ACTIVE

    @property
    def needs_attention(self):
        """A check that came back bad -- an admin should look before paying."""
        return self.validation_status in (
            self.ValidationStatus.INVALID,
            self.ValidationStatus.NAME_MISMATCH,
        )

    def snapshot(self):
        """The comparable part of these details, for spotting a real change."""
        return (
            self.account_holder_name.strip(),
            self.account_number.strip(),
            self.ifsc_code.strip().upper(),
            self.account_type,
            self.upi_id.strip().lower(),
        )


class VendorBankAccountChange(models.Model):
    """
    An append-only record of every edit to a payout destination.

    Only masked numbers are kept. The point is to answer "when did this
    change, and to what" during a payment dispute -- storing the old number in
    full would spread it across another table for no extra answer.
    """

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='bank_account_changes',
    )

    old_account_masked = models.CharField(max_length=32, blank=True)
    new_account_masked = models.CharField(max_length=32, blank=True)
    old_ifsc = models.CharField(max_length=11, blank=True)
    new_ifsc = models.CharField(max_length=11, blank=True)
    old_upi = models.CharField(max_length=64, blank=True)
    new_upi = models.CharField(max_length=64, blank=True)

    # Blank when the vendor changed it themselves in the app.
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='vendor_bank_changes',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.vendor} bank change at {self.changed_at:%Y-%m-%d %H:%M}"

    @property
    def is_first_time(self):
        return not self.old_account_masked
