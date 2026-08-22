from django.db.models import Avg, Count, Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsCustomer
from bookings.models import Booking
from .models import Review, service_ids_in
from .serializers import (
    ReviewCreateSerializer,
    ReviewListSerializer,
    VendorRatingSummarySerializer,
    ServiceRatingSummarySerializer,
)


class ReviewCreateView(generics.CreateAPIView):
    serializer_class = ReviewCreateSerializer
    permission_classes = [IsCustomer]


class MyReviewsListView(generics.ListAPIView):
    serializer_class = ReviewListSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return Review.objects.filter(
            customer=self.request.user.customer_profile
        )


class VendorReviewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, vendor_id):
        reviews = Review.objects.filter(vendor_id=vendor_id)

        if not reviews.exists():
            return Response({
                'average_rating': 0,
                'total_reviews': 0,
                'rating_breakdown': {str(i): 0 for i in range(1, 6)},
                'reviews': [],
            })

        avg = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        total = reviews.count()

        breakdown = {}
        for i in range(1, 6):
            breakdown[str(i)] = reviews.filter(rating=i).count()

        serializer = ReviewListSerializer(reviews[:20], many=True)

        return Response({
            'average_rating': round(avg, 2),
            'total_reviews': total,
            'rating_breakdown': breakdown,
            'reviews': serializer.data,
        })


class ServiceReviewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, category_id):
        reviews = Review.objects.filter(service_category_id=category_id)

        if not reviews.exists():
            return Response({
                'average_rating': 0,
                'total_reviews': 0,
                'reviews': [],
            })

        avg = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        total = reviews.count()

        serializer = ReviewListSerializer(reviews[:20], many=True)

        return Response({
            'average_rating': round(avg, 2),
            'total_reviews': total,
            'reviews': serializer.data,
        })
def _bookings_including_service(service_id):
    """
    Reviewed bookings whose basket contained this service.

    Covers multi-service bookings, where one review legitimately spans several
    services and so can't be pinned to a single `service` FK. Scoped to
    reviewed bookings that have no FK of their own, so the scan stays small.
    """
    candidates = Booking.objects.filter(
        review__isnull=False, review__service__isnull=True
    ).values_list('id', 'services_json')

    return [
        booking_id for booking_id, services_json in candidates
        if service_id in service_ids_in(services_json)
    ]


class IndividualServiceReviewsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, service_id):
        reviews = Review.objects.filter(
            Q(service_id=service_id)
            | Q(booking_id__in=_bookings_including_service(service_id))
        ).distinct()

        if not reviews.exists():
            return Response({
                'average_rating': 0,
                'total_reviews': 0,
                'reviews': [],
            })

        avg = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        total = reviews.count()
        serializer = ReviewListSerializer(reviews[:20], many=True)

        return Response({
            'average_rating': round(avg, 2),
            'total_reviews': total,
            'reviews': serializer.data,
        })


class BookingReviewView(APIView):
    """Check if a booking has been reviewed."""
    permission_classes = [IsCustomer]

    def get(self, request, booking_id):
        try:
            review = Review.objects.get(booking_id=booking_id)
            return Response(ReviewListSerializer(review).data)
        except Review.DoesNotExist:
            return Response({'reviewed': False})