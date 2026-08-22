from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsCustomerOrVendor

from .models import SupportTicket, TicketMessage
from .notifications import notify_admins_of_reply
from .serializers import (
    SupportTicketSerializer,
    SupportTicketCreateSerializer,
)


def own_tickets(user):
    """Every ticket the calling user is allowed to see — customer or vendor."""
    qs = SupportTicket.objects.prefetch_related('messages')
    if user.role == User.Role.VENDOR:
        return qs.filter(vendor=user.vendor_profile)
    return qs.filter(customer=user.customer_profile)


def sender_for(user):
    return (
        TicketMessage.Sender.VENDOR
        if user.role == User.Role.VENDOR
        else TicketMessage.Sender.CUSTOMER
    )


class MyTicketsListView(generics.ListAPIView):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsCustomerOrVendor]

    def get_queryset(self):
        return own_tickets(self.request.user)


class CreateTicketView(generics.CreateAPIView):
    serializer_class = SupportTicketCreateSerializer
    permission_classes = [IsCustomerOrVendor]


class TicketDetailView(generics.RetrieveAPIView):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsCustomerOrVendor]

    def get_queryset(self):
        return own_tickets(self.request.user)


class TicketCategoriesView(APIView):
    """The category list the calling app should offer when opening a ticket."""
    permission_classes = [IsCustomerOrVendor]

    def get(self, request):
        allowed = (
            SupportTicket.VENDOR_CATEGORIES
            if request.user.role == User.Role.VENDOR
            else SupportTicket.CUSTOMER_CATEGORIES
        )
        labels = dict(SupportTicket.Category.choices)
        return Response([
            {'value': str(c), 'label': labels[c]} for c in allowed
        ])


class AddTicketMessageView(APIView):
    permission_classes = [IsCustomerOrVendor]

    def post(self, request, ticket_id):
        ticket = own_tickets(request.user).filter(id=ticket_id).first()
        if ticket is None:
            return Response({'error': 'Ticket not found.'}, status=404)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'error': 'Message is required.'}, status=400)

        TicketMessage.objects.create(
            ticket=ticket, sender=sender_for(request.user), message=message
        )
        # Reopen if the requester comes back after we closed it.
        if ticket.status in [SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED]:
            ticket.status = SupportTicket.Status.OPEN
        ticket.save()

        notify_admins_of_reply(ticket, message)

        # Re-query: `ticket` was loaded with a prefetched `messages` cache that
        # predates the message we just wrote, so serializing it would drop it.
        fresh = SupportTicket.objects.prefetch_related('messages').get(id=ticket.id)
        return Response(SupportTicketSerializer(fresh).data)
