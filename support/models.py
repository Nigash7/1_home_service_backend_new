from django.db import models


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        RESOLVED = 'RESOLVED', 'Resolved'
        CLOSED = 'CLOSED', 'Closed'

    class Category(models.TextChoices):
        BOOKING = 'BOOKING', 'Booking Issue'
        PAYMENT = 'PAYMENT', 'Payment Issue'
        VENDOR = 'VENDOR', 'Vendor Issue'
        ACCOUNT = 'ACCOUNT', 'Account Issue'
        OTHER = 'OTHER', 'Other'

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='support_tickets'
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

    def __str__(self):
        return f"#{self.id} — {self.subject} ({self.status})"


class TicketMessage(models.Model):
    class Sender(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
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