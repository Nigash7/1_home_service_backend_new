"""
Simple notification system.
Stores notifications and can send push via FCM later (not now).
For now, notifications appear in customer's app as a badge.
"""
from django.db import models
from django.utils import timezone


def notify_customer(customer, title, body, booking=None):
    """
    Create a notification for a customer.
    Later this can trigger FCM push notifications.
    """
    from dashboard.models import CustomerNotification
    CustomerNotification.objects.create(
        customer=customer,
        title=title,
        body=body,
        booking=booking,
    )