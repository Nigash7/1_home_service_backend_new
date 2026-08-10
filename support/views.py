from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsCustomer
from .models import SupportTicket, TicketMessage
from .serializers import (
    SupportTicketSerializer,
    SupportTicketCreateSerializer,
)


class MyTicketsListView(generics.ListAPIView):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return SupportTicket.objects.filter(
            customer=self.request.user.customer_profile
        ).prefetch_related('messages')


class CreateTicketView(generics.CreateAPIView):
    serializer_class = SupportTicketCreateSerializer
    permission_classes = [IsCustomer]


class TicketDetailView(generics.RetrieveAPIView):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return SupportTicket.objects.filter(
            customer=self.request.user.customer_profile
        ).prefetch_related('messages')


class AddTicketMessageView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, ticket_id):
        try:
            ticket = SupportTicket.objects.get(
                id=ticket_id, customer=request.user.customer_profile
            )
        except SupportTicket.DoesNotExist:
            return Response({'error': 'Ticket not found.'}, status=404)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'error': 'Message is required.'}, status=400)

        TicketMessage.objects.create(
            ticket=ticket, sender='CUSTOMER', message=message
        )
        # Reopen if resolved
        if ticket.status in ['RESOLVED', 'CLOSED']:
            ticket.status = 'OPEN'
        ticket.save()

        return Response(SupportTicketSerializer(ticket).data)