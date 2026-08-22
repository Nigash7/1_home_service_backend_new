from django.db import models


class SupportTicket(models.Model):
    """
    One help request raised from either app.

    A ticket belongs to exactly one requester: a customer *or* a vendor.
    `raised_by` records which, so the admin dashboard can filter without
    testing both foreign keys everywhere.
    """

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        RESOLVED = 'RESOLVED', 'Resolved'
        CLOSED = 'CLOSED', 'Closed'

    class RaisedBy(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        VENDOR = 'VENDOR', 'Vendor'

    class Category(models.TextChoices):
        # Shared
        BOOKING = 'BOOKING', 'Booking Issue'
        PAYMENT = 'PAYMENT', 'Payment Issue'
        ACCOUNT = 'ACCOUNT', 'Account Issue'
        OTHER = 'OTHER', 'Other'
        # Customer-only
        VENDOR = 'VENDOR', 'Vendor Issue'
        # Vendor-only
        JOB = 'JOB', 'Job / Assignment Issue'
        PAYOUT = 'PAYOUT', 'Payout Issue'
        APP = 'APP', 'App / Technical Issue'

    # Categories each app is allowed to pick from.
    CUSTOMER_CATEGORIES = [
        Category.BOOKING, Category.PAYMENT, Category.VENDOR,
        Category.ACCOUNT, Category.OTHER,
    ]
    VENDOR_CATEGORIES = [
        Category.JOB, Category.PAYOUT, Category.PAYMENT,
        Category.ACCOUNT, Category.APP, Category.OTHER,
    ]

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE,
        null=True, blank=True, related_name='support_tickets'
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE,
        null=True, blank=True, related_name='support_tickets'
    )
    raised_by = models.CharField(
        max_length=10, choices=RaisedBy.choices,
        default=RaisedBy.CUSTOMER, db_index=True
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='support_tickets'
    )
    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(customer__isnull=False, vendor__isnull=True)
                | models.Q(customer__isnull=True, vendor__isnull=False),
                name='support_ticket_has_exactly_one_requester',
            ),
        ]

    def __str__(self):
        return f"#{self.id} — {self.subject} ({self.status})"

    def save(self, *args, **kwargs):
        # Keep raised_by honest even if a caller forgets to set it.
        self.raised_by = self.RaisedBy.VENDOR if self.vendor_id else self.RaisedBy.CUSTOMER
        super().save(*args, **kwargs)

    # ------------------------------------------------------------- requester
    @property
    def requester(self):
        """The Customer or Vendor profile that opened this ticket."""
        return self.vendor if self.raised_by == self.RaisedBy.VENDOR else self.customer

    @property
    def requester_user(self):
        requester = self.requester
        return getattr(requester, 'user', None)

    @property
    def requester_name(self):
        user = self.requester_user
        if user is None:
            return 'Unknown'
        return user.get_full_name() or user.username

    @property
    def requester_phone(self):
        return getattr(self.requester_user, 'phone_number', '') or ''

    @property
    def requester_email(self):
        return getattr(self.requester_user, 'email', '') or ''

    @property
    def is_from_vendor(self):
        return self.raised_by == self.RaisedBy.VENDOR

    @property
    def last_message(self):
        return self.messages.last()

    @property
    def awaiting_admin_reply(self):
        """True when the requester spoke last — i.e. the ball is with support."""
        last = self.last_message
        return bool(last and last.sender != TicketMessage.Sender.ADMIN)


class TicketMessage(models.Model):
    class Sender(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        VENDOR = 'VENDOR', 'Vendor'
        ADMIN = 'ADMIN', 'Admin'

    ticket = models.ForeignKey(
        SupportTicket, on_delete=models.CASCADE, related_name='messages'
    )
    sender = models.CharField(max_length=10, choices=Sender.choices)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender} on ticket #{self.ticket_id}"
