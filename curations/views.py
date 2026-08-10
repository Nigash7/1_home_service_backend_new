from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import CurationSection
from .serializers import CurationSectionSerializer

from dashboard.models import CustomerNotification
from accounts.permissions import IsCustomer  # adjust path if you put it elsewhere


class CurationSectionListView(generics.ListAPIView):
    serializer_class = CurationSectionSerializer
    permission_classes = [permissions.AllowAny]
    queryset = CurationSection.objects.filter(is_active=True).prefetch_related(
        'items__service__category', 'items__service__subcategory'
    )


class CustomerRegisterView(APIView):
    """POST /api/customers/register/ — placeholder, needs real implementation"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # TODO: implement actual customer registration logic
        return Response({'detail': 'Not implemented yet.'}, status=501)


class CustomerMeView(APIView):
    """GET /api/customers/me/ — placeholder, needs real implementation"""
    permission_classes = [IsCustomer]

    def get(self, request):
        customer = request.user.customer_profile
        return Response({
            'id': customer.id,
            'user_id': request.user.id,
            # TODO: add real fields from your Customer model/serializer
        })


class MyNotificationsView(generics.ListAPIView):
    """GET /api/customers/me/notifications/"""
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return self.request.user.customer_profile.notifications.all()[:50]

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        data = [{
            'id': n.id,
            'title': n.title,
            'body': n.body,
            'is_read': n.is_read,
            'booking_id': n.booking_id,
            'created_at': n.created_at.isoformat(),
        } for n in qs]
        unread = self.get_queryset().filter(is_read=False).count()
        return Response({'notifications': data, 'unread_count': unread})


class MarkNotificationsReadView(APIView):
    """POST /api/customers/me/notifications/read/"""
    permission_classes = [IsCustomer]

    def post(self, request):
        request.user.customer_profile.notifications.filter(is_read=False).update(is_read=True)
        return Response({'success': True})