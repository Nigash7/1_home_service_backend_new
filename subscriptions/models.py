from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.Model):
    """
    A membership tier an admin can put a vendor on -- Free, Silver, Gold.

    The price is recorded here so the tiers read correctly to everyone, but
    nothing on the platform charges for one: subscriptions are granted by an
    admin from the dashboard, and any money that changed hands is typed in by
    hand on the subscription row. Same arrangement as the rest of the payments
    side, which keeps no float of its own.
    """

    class BillingPeriod(models.TextChoices):
        MONTHLY = 'MONTHLY', 'Monthly'
        QUARTERLY = 'QUARTERLY', 'Quarterly (3 months)'
        HALF_YEARLY = 'HALF_YEARLY', 'Half-yearly (6 months)'
        YEARLY = 'YEARLY', 'Yearly'
        LIFETIME = 'LIFETIME', 'Lifetime (never expires)'

    # How long one term of each period runs. LIFETIME is absent on purpose --
    # it has no end date at all, which `term_end_date` reads back as None.
    PERIOD_DAYS = {
        BillingPeriod.MONTHLY: 30,
        BillingPeriod.QUARTERLY: 90,
        BillingPeriod.HALF_YEARLY: 180,
        BillingPeriod.YEARLY: 365,
    }

    name = models.CharField(
        max_length=100, unique=True, help_text="e.g. Free, Silver, Gold"
    )
    description = models.TextField(
        blank=True, help_text="One-line pitch shown under the plan name"
    )
    price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Amount per billing period. 0 = free plan.",
    )
    billing_period = models.CharField(
        max_length=15,
        choices=BillingPeriod.choices,
        default=BillingPeriod.MONTHLY,
    )
    features = models.TextField(
        blank=True,
        help_text="One benefit per line. Shown as bullets on the plan card.",
    )

    is_active = models.BooleanField(
        default=True, help_text="Inactive plans cannot be assigned to new vendors"
    )
    is_default = models.BooleanField(
        default=False,
        help_text="The plan a vendor lands on by default. Only one plan holds this.",
    )
    sort_order = models.PositiveIntegerField(
        default=0, help_text="Lower number = shown first"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'price', 'id']

    def __str__(self):
        if self.is_free:
            return f"{self.name} - Free"
        return f"{self.name} - {self.price} / {self.get_billing_period_display()}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # "Default" is a single seat. Setting it on one plan takes it off
        # whichever plan held it before, so the dashboard can never end up
        # with two plans both claiming to be the fallback.
        if self.is_default:
            SubscriptionPlan.objects.filter(is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)

    @property
    def is_free(self):
        return self.price <= 0

    @property
    def duration_days(self):
        """Days in one term, or None for a plan that never expires."""
        return self.PERIOD_DAYS.get(self.billing_period)

    @property
    def feature_list(self):
        """`features` split into the bullets a template loops over."""
        return [line.strip() for line in self.features.splitlines() if line.strip()]

    def term_end_date(self, start_date=None):
        """
        When a term starting on `start_date` runs out, or None for a lifetime
        plan. The last day is inclusive -- a 30-day term started today ends 29
        days from today, so the vendor gets the full 30.
        """
        days = self.duration_days
        if days is None:
            return None
        return (start_date or timezone.localdate()) + timedelta(days=days - 1)

    @property
    def active_subscriber_count(self):
        """Vendors on this plan right now. Prefers the annotation if present."""
        if hasattr(self, 'active_subscribers'):
            return self.active_subscribers
        return VendorSubscription.objects.active().filter(plan=self).count()


class VendorSubscriptionQuerySet(models.QuerySet):
    """Reusable filters shared by the dashboard and the vendor API."""

    def active(self):
        """
        Subscriptions live right now: marked ACTIVE, started, and either
        open-ended or still inside their term. A row whose end date has passed
        stays ACTIVE in the database until something sweeps it (see
        `expire_due`), so the window is always checked here too.
        """
        today = timezone.localdate()
        return self.filter(
            status=VendorSubscription.Status.ACTIVE,
            start_date__lte=today,
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        )

    def queued(self):
        """
        ACTIVE terms that have not started yet -- an early renewal waiting its
        turn. They take over on their own once the running term lapses and
        `expire_due` closes it.
        """
        return self.filter(
            status=VendorSubscription.Status.ACTIVE,
            start_date__gt=timezone.localdate(),
        )

    def due_to_expire(self):
        """ACTIVE rows whose term ran out -- what `expire_due` sweeps."""
        return self.filter(
            status=VendorSubscription.Status.ACTIVE,
            end_date__isnull=False,
            end_date__lt=timezone.localdate(),
        )

    def expiring_within(self, days):
        """Live subscriptions ending within the next `days` days."""
        today = timezone.localdate()
        return self.active().filter(
            end_date__isnull=False, end_date__lte=today + timedelta(days=days)
        )


class VendorSubscriptionManager(
    models.Manager.from_queryset(VendorSubscriptionQuerySet)
):

    def active_for(self, vendor):
        """
        The vendor's live subscription, or None.

        The single place anything should ask "is this vendor subscribed?".
        Nothing is gated on it today -- making a subscription mean something
        later is a matter of calling this and acting on the answer.
        """
        return self.active().filter(vendor=vendor).select_related('plan').first()

    def queued_for(self, vendor):
        """The vendor's next term, if a renewal is already lined up."""
        return (
            self.queued().filter(vendor=vendor)
            .select_related('plan').order_by('start_date').first()
        )

    def expire_due(self):
        """
        Flips subscriptions past their end date to EXPIRED. Safe to call as
        often as you like; returns how many rows moved.
        """
        return self.due_to_expire().update(
            status=VendorSubscription.Status.EXPIRED
        )


class VendorSubscription(models.Model):
    """
    One vendor's term on one plan, granted by an admin.

    A vendor collects these over time -- the history is kept -- but only one
    is live at a time. Putting a vendor on a new plan ends the current term.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        EXPIRED = 'EXPIRED', 'Expired'
        CANCELLED = 'CANCELLED', 'Cancelled'

    EXPIRING_SOON_DAYS = 7

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='subscriptions'
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions'
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(
        null=True, blank=True, help_text="Blank = never expires"
    )

    # Money, if any, changed hands outside the platform. Recorded so the
    # dashboard can show what a vendor paid; nothing reconciles it.
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="What the vendor actually paid, if anything. Recorded by hand.",
    )
    payment_reference = models.CharField(
        max_length=100, blank=True,
        help_text="UPI ref / receipt number, if you took payment offline",
    )
    notes = models.TextField(blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='granted_subscriptions',
        help_text="Admin who granted this subscription",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = VendorSubscriptionManager()

    class Meta:
        ordering = ['-start_date', '-created_at']
        indexes = [
            models.Index(fields=['vendor', 'status']),
        ]

    def __str__(self):
        return f"{self.vendor} - {self.plan.name} ({self.get_status_display()})"

    @property
    def is_active(self):
        """Live right now -- the row-level twin of the `active()` filter."""
        if self.status != self.Status.ACTIVE:
            return False
        today = timezone.localdate()
        if self.start_date > today:
            return False
        return self.end_date is None or self.end_date >= today

    @property
    def is_lifetime(self):
        return self.end_date is None

    @property
    def days_remaining(self):
        """Days left including today, or None for a term that never ends."""
        if self.end_date is None:
            return None
        return max((self.end_date - timezone.localdate()).days + 1, 0)

    @property
    def is_expiring_soon(self):
        remaining = self.days_remaining
        return (
            self.is_active
            and remaining is not None
            and remaining <= self.EXPIRING_SOON_DAYS
        )

    def cancel(self, reason=''):
        """Ends this subscription now. A cancelled term is never revived."""
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.cancel_reason = reason
        self.save(update_fields=['status', 'cancelled_at', 'cancel_reason'])
        return self


class SubscriptionUpgradeRequestManager(models.Manager):

    def pending_for(self, vendor):
        """The request this vendor is waiting on, or None."""
        return (
            self.filter(
                vendor=vendor,
                status=SubscriptionUpgradeRequest.Status.PENDING,
            )
            .select_related('plan')
            .first()
        )


class SubscriptionUpgradeRequest(models.Model):
    """
    A vendor asking to be moved onto a plan.

    Vendors pick a tier in the app but never grant themselves one: nothing
    charges them, so a self-served upgrade would be a giveaway, and whoever
    sits on Gold the day payments go live would be sitting there for free.
    They ask; an admin decides. Approving is what actually starts the term.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        WITHDRAWN = 'WITHDRAWN', 'Withdrawn'

    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        related_name='subscription_requests',
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='upgrade_requests'
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    note = models.TextField(blank=True, help_text="What the vendor said when asking")

    # What the plan cost when they asked. A later price change must not
    # rewrite the offer they were looking at.
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_subscription_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    granted_subscription = models.ForeignKey(
        VendorSubscription, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='from_request',
        help_text="The term approving this request started",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = SubscriptionUpgradeRequestManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.vendor} wants {self.plan.name} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status == self.Status.PENDING
