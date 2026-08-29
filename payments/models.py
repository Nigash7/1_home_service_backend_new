from decimal import Decimal

from django.db import models
from django.utils import timezone


def to_paise(amount):
    """
    Rupees -> integer paise, which is the only unit Razorpay accepts.

    Done with Decimal rather than float because `int(19.99 * 100)` is 1998 --
    a rounding bug that silently undercharges. Quantising first keeps the
    half-paise cases (from percentage discounts) honest.
    """
    rupees = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    return int(rupees * 100)


def to_rupees(paise):
    """Integer paise -> Decimal rupees, for display and for storing back."""
    return (Decimal(int(paise or 0)) / 100).quantize(Decimal('0.01'))


class Payment(models.Model):
    """
    One attempt to collect money for a booking, mirrored from Razorpay.

    The platform is the merchant of record: a captured payment sits in *our*
    Razorpay account, never the vendor's. That is what makes it a hold -- the
    vendor is paid later, by a separate payout, and until then the whole
    amount can still be refunded. `payout_status` tracks that second half.

    Nothing here is ever written from a value the client sent us. The amount
    comes from the booking, and the status comes from a signed Razorpay
    payload, because both are things a customer would otherwise be able to
    choose for themselves.
    """

    class Status(models.TextChoices):
        CREATED = 'CREATED', 'Order created'
        ATTEMPTED = 'ATTEMPTED', 'Checkout opened'
        CAPTURED = 'CAPTURED', 'Paid'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'
        PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED', 'Partially refunded'

    # Terminal states -- a webhook arriving later must not walk these back.
    SETTLED = (Status.CAPTURED, Status.REFUNDED, Status.PARTIALLY_REFUNDED)

    class PayoutStatus(models.TextChoices):
        HELD = 'HELD', 'Held by platform'
        RELEASED = 'RELEASED', 'Released to vendor'
        REFUNDED = 'REFUNDED', 'Returned to customer'

    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.PROTECT, related_name='payments'
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='payments'
    )

    # Razorpay's own identifiers. order_id is created by us up front; the rest
    # only exist once the customer has actually been through checkout.
    razorpay_order_id = models.CharField(max_length=64, unique=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True, db_index=True)
    razorpay_signature = models.CharField(max_length=128, blank=True)

    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Rupees, snapshotted from the booking when the order was created",
    )
    amount_refunded = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default='INR')

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True
    )
    payout_status = models.CharField(
        max_length=10, choices=PayoutStatus.choices, default=PayoutStatus.HELD,
        db_index=True,
        help_text="Whether the captured money has left the platform yet",
    )

    method = models.CharField(max_length=30, blank=True, help_text="upi / card / netbanking")
    failure_reason = models.TextField(blank=True)

    # False for rzp_test_* keys, so test takings never inflate real reporting.
    is_live = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['booking', 'status'])]

    def __str__(self):
        return f"{self.razorpay_order_id} — {self.amount} {self.currency} ({self.status})"

    @property
    def is_paid(self):
        return self.status == self.Status.CAPTURED

    @property
    def amount_paise(self):
        return to_paise(self.amount)

    @property
    def refundable_amount(self):
        """What could still be sent back — nothing, once it has been released."""
        if self.status not in (self.Status.CAPTURED, self.Status.PARTIALLY_REFUNDED):
            return Decimal('0.00')
        if self.payout_status == self.PayoutStatus.RELEASED:
            return Decimal('0.00')
        return self.amount - self.amount_refunded

    def mark_captured(self, *, payment_id='', method='', signature='', save=True):
        """
        Move to CAPTURED, unless we are already past it.

        Razorpay delivers the same event more than once by design, and the
        browser callback races the webhook, so this has to be safe to call
        repeatedly with the same payload.
        """
        if self.status in self.SETTLED:
            return False
        self.status = self.Status.CAPTURED
        self.captured_at = self.captured_at or timezone.now()
        if payment_id:
            self.razorpay_payment_id = payment_id
        if method:
            self.method = method
        if signature:
            self.razorpay_signature = signature
        if save:
            self.save(update_fields=[
                'status', 'captured_at', 'razorpay_payment_id',
                'method', 'razorpay_signature', 'updated_at',
            ])
        return True


class WebhookEvent(models.Model):
    """
    Every webhook Razorpay has delivered, kept whole.

    Two jobs. Razorpay retries until it gets a 2xx, so `event_id` is unique and
    a repeat delivery is recognised and skipped instead of being applied twice.
    And when a payment's history is disputed months later, the signed original
    payload is the evidence -- our own status field is only ever a summary of it.
    """

    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)

    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='webhook_events',
    )

    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"{self.event_type} ({self.event_id})"


class Payout(models.Model):
    """
    One transfer of released money out to a vendor, mirrored from RazorpayX.

    A OneToOne on Payment, which is the point: the database refuses a second
    payout for the same payment, so a double-clicked button or a retried
    request cannot pay a vendor twice. `idempotency_key` is the same guard one
    level out -- generated once and replayed on every retry, so RazorpayX
    recognises the repeat and returns the original payout instead of making
    another.

    Statuses are RazorpayX's own, kept verbatim rather than mapped, because
    "what did RazorpayX say" is the question being asked during a dispute.
    """

    class Status(models.TextChoices):
        # Ours, before RazorpayX has been called.
        PENDING = 'pending', 'Not sent yet'
        # Theirs, from here down.
        QUEUED = 'queued', 'Queued (low balance)'
        PROCESSING = 'processing', 'Processing'
        PROCESSED = 'processed', 'Paid'
        REVERSED = 'reversed', 'Reversed'
        CANCELLED = 'cancelled', 'Cancelled'
        REJECTED = 'rejected', 'Rejected'
        FAILED = 'failed', 'Failed'

    # Money is on its way or has arrived. Nothing may be re-sent from here.
    IN_FLIGHT = (Status.QUEUED, Status.PROCESSING, Status.PROCESSED)

    # RazorpayX gave a final no, and the money never left. Safe to try again
    # with a fresh idempotency key.
    RETRYABLE = (Status.FAILED, Status.REJECTED, Status.CANCELLED, Status.REVERSED)

    payment = models.OneToOneField(
        Payment, on_delete=models.PROTECT, related_name='payout'
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.PROTECT, related_name='payouts'
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default='INR')
    mode = models.CharField(max_length=10, blank=True, help_text="IMPS / NEFT / RTGS / UPI")

    razorpay_payout_id = models.CharField(max_length=64, blank=True, db_index=True)
    fund_account_id = models.CharField(max_length=64, blank=True)

    # Generated before the first attempt and never regenerated for it, so a
    # retry is recognised by RazorpayX as the same payout.
    idempotency_key = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    utr = models.CharField(
        max_length=64, blank=True,
        help_text="Bank reference the vendor can quote to their branch",
    )
    failure_reason = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)

    is_live = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"Payout {self.amount} to {self.vendor} ({self.status})"

    @property
    def is_settled(self):
        return self.status == self.Status.PROCESSED

    @property
    def can_retry(self):
        return self.status in self.RETRYABLE

    @property
    def amount_paise(self):
        return to_paise(self.amount)
