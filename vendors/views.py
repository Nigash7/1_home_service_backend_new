from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from accounts.permissions import IsVendor
from .models import Vendor
from .serializers import (
    VendorAvailabilitySerializer,
    VendorProfileSerializer,
    VendorSignupSerializer,
)


class VendorSignupView(generics.CreateAPIView):
    """
    POST /api/vendors/signup/  (multipart/form-data — documents are attached)

    Open registration for the Vendor app. The account is created straight away
    but sits on PENDING, so logging in is refused until an admin verifies the
    profile from the dashboard.
    """
    serializer_class = VendorSignupSerializer
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor = serializer.save()
        return Response(
            {
                'detail': (
                    'Your application has been submitted. You can log in once an '
                    'admin has verified your profile.'
                ),
                'username': vendor.user.username,
                'verification_status': vendor.verification_status,
            },
            status=status.HTTP_201_CREATED,
        )


class VendorMeView(generics.RetrieveAPIView):
    """
    GET /api/vendors/me/
    Vendor's own profile: categories assigned, verification status, service area.
    """
    serializer_class = VendorProfileSerializer
    permission_classes = [IsVendor]

    def get_object(self):
        return self.request.user.vendor_profile


class VendorAvailabilityUpdateView(generics.UpdateAPIView):
    """
    PATCH /api/vendors/me/availability/
    Body: { "is_available": true/false }
    Vendor toggles this when they go on/off duty.
    """
    serializer_class = VendorAvailabilitySerializer
    permission_classes = [IsVendor]

    def get_object(self):
        return self.request.user.vendor_profile


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions


class UpdateVendorLocationView(APIView):
    """POST /api/vendors/update-location/ — vendor updates their GPS location."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            vendor = request.user.vendor_profile
        except Exception:
            return Response(
                {'error': 'Not a vendor account.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')

        if latitude is None or longitude is None:
            return Response(
                {'error': 'Latitude and longitude are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        vendor.latitude = latitude
        vendor.longitude = longitude
        vendor.save(update_fields=['latitude', 'longitude'])

        return Response({
            'success': True,
            'latitude': str(vendor.latitude),
            'longitude': str(vendor.longitude),
        })


class VendorProfileView(APIView):
    """GET /api/vendors/me/ — vendor's own profile including location."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            vendor = request.user.vendor_profile
        except Exception:
            return Response(
                {'error': 'Not a vendor account.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response({
            'id': vendor.id,
            'name': request.user.get_full_name() or request.user.username,
            'service_area': vendor.service_area,
            'status': vendor.status,
            'is_available': vendor.is_available,
            'verification_status': vendor.verification_status,
            'latitude': str(vendor.latitude) if vendor.latitude else None,
            'longitude': str(vendor.longitude) if vendor.longitude else None,
        })        


# ---------------------------------------------------------------------------
# Pro Vendors — the admin-curated vendors the Customer app puts on show.
# All read-only and open: a customer browses these before logging in.
# ---------------------------------------------------------------------------

from django.db.models import F
from services.models import Service
from .serializers import ProVendorCardSerializer, ProVendorDetailSerializer


def _pro_vendor_queryset():
    """Listed pro vendors, rating figures annotated, in the admin's order."""
    return (
        Vendor.objects.pro()
        .select_related('user')
        .prefetch_related('categories', 'subcategories', 'services')
        .with_review_stats()
        .order_by('pro_sort_order', F('avg_rating').desc(nulls_last=True), 'id')
    )


class ProVendorListView(generics.ListAPIView):
    """
    GET /api/vendors/pro/

    Optional filters:
      ?category=<id>  pros who cover that service category
      ?service=<id>   pros who cover the category the service sits in — what
                      the row at the bottom of a service page asks for
    """
    serializer_class = ProVendorCardSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = _pro_vendor_queryset()

        category_id = self.request.query_params.get('category')
        service_id = self.request.query_params.get('service')

        if service_id:
            service = Service.objects.filter(id=service_id).first()
            # An unknown service must show nothing, not every pro on the books.
            if service is None:
                return queryset.none()
            # Per-service, so a vendor who only does part of a category is
            # offered for their part and nobody else's.
            return queryset.for_service(service)

        if category_id:
            queryset = queryset.for_category(category_id)
        return queryset


class ProVendorDetailView(generics.RetrieveAPIView):
    """GET /api/vendors/pro/<id>/ — the customer app's vendor profile screen."""
    serializer_class = ProVendorDetailSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return _pro_vendor_queryset()
