from collections import Counter

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCustomer
from bookings.models import Booking
from services.models import Service
from services.serializers import ServiceCardSerializer
from .models import Customer, ServiceView
from .serializers import CustomerRegisterSerializer, CustomerProfileSerializer

# How many cards each personalised row shows.
RECENTLY_VIEWED_LIMIT = 10
BOOK_AGAIN_LIMIT = 10


class CustomerRegisterView(generics.CreateAPIView):
    """
    POST /api/customers/register/
    Public signup endpoint for the Customer app.
    Body: username, password, first_name, last_name, phone_number, address, latitude, longitude
    """
    serializer_class = CustomerRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        # Return the newly created profile using the PROFILE serializer,
        # not the registration input serializer (which has no `username`
        # attribute directly on the Customer model).
        output = CustomerProfileSerializer(customer)
        return Response(output.data, status=status.HTTP_201_CREATED)


class CustomerMeView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/customers/me/  -> view own profile
    PATCH /api/customers/me/ -> update own profile
    Requires a logged-in customer (JWT token in Authorization header).
    """
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsCustomer]

    def get_object(self):
        return self.request.user.customer_profile


class RecentlyViewedView(APIView):
    """
    GET  /api/customers/recently-viewed/  -> services this customer opened, newest first
    POST /api/customers/recently-viewed/  -> record a view, body: { "service_id": 12 }
    """
    permission_classes = [IsCustomer]

    def get(self, request):
        customer = request.user.customer_profile
        views = (
            ServiceView.objects
            .filter(customer=customer, service__is_active=True)
            .select_related('service__category', 'service__subcategory')[:RECENTLY_VIEWED_LIMIT]
        )
        services = [v.service for v in views]
        return Response(
            ServiceCardSerializer(services, many=True, context={'request': request}).data
        )

    def post(self, request):
        service_id = request.data.get('service_id')
        if not service_id:
            return Response(
                {'detail': 'service_id is required.'}, status=status.HTTP_400_BAD_REQUEST
            )

        service = Service.objects.filter(id=service_id, is_active=True).first()
        if service is None:
            return Response(
                {'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND
            )

        customer = request.user.customer_profile
        # auto_now on viewed_at means saving an existing row just bumps it to
        # the top instead of adding a duplicate.
        view, created = ServiceView.objects.get_or_create(
            customer=customer, service=service
        )
        if not created:
            view.save(update_fields=['viewed_at'])

        return Response(status=status.HTTP_204_NO_CONTENT)


class BookAgainView(APIView):
    """
    GET /api/customers/book-again/
    Services this customer has booked before, most-booked first, so repeat
    orders are one tap away. Each card carries `times_booked`.
    """
    permission_classes = [IsCustomer]

    def get(self, request):
        customer = request.user.customer_profile

        # Bookings record what was ordered in services_json:
        # [{id, name, price, qty}, ...]
        counts = Counter()
        bookings = Booking.objects.filter(customer=customer).exclude(
            status=Booking.Status.CANCELLED
        ).values_list('services_json', flat=True)

        for entry in bookings:
            for item in entry or []:
                if not isinstance(item, dict):
                    continue
                service_id = item.get('id')
                if service_id is None:
                    continue
                try:
                    counts[int(service_id)] += int(item.get('qty') or 1)
                except (TypeError, ValueError):
                    continue

        if not counts:
            return Response([])

        services = Service.objects.filter(
            id__in=counts.keys(), is_active=True
        ).select_related('category', 'subcategory')
        by_id = {s.id: s for s in services}

        # Most booked first, then by how recently the service was added.
        ordered_ids = sorted(
            (sid for sid in counts if sid in by_id),
            key=lambda sid: (-counts[sid], -sid),
        )[:BOOK_AGAIN_LIMIT]

        data = ServiceCardSerializer(
            [by_id[sid] for sid in ordered_ids], many=True, context={'request': request}
        ).data
        for card in data:
            card['times_booked'] = counts[card['service_id']]
        return Response(data)
