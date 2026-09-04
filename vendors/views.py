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

        # A customer only wants pros who work where they live. Vendors who
        # named nowhere cover everywhere and stay in the list.
        state = self.request.query_params.get('state')
        if state:
            queryset = queryset.serving_area(
                state, self.request.query_params.get('district', ''),
            )

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


# ---------------------------------------------------------------------------
# "Can I have this service where I live?" — what the customer app asks the
# moment a service is opened, before it lets the booking go any further.
# ---------------------------------------------------------------------------

from rest_framework.generics import get_object_or_404 as _get_object_or_404  # noqa: E402
from .regions import (  # noqa: E402
    INDIAN_STATES, canonical_state, district_label, districts_for,
)

# How many out-of-state vendors the fallback list offers. Enough to give the
# customer a real choice, few enough that it stays a fallback.
ELSEWHERE_LIMIT = 10


class StateListView(APIView):
    """
    GET /api/vendors/states/

    The states the forms offer, so the vendor app and the dashboard spell them
    the same way. Open: the signup screen reads it before anyone has an account.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({'states': INDIAN_STATES})


class RegionListView(APIView):
    """
    GET /api/vendors/regions/

    Every state with the districts under it, so a form can offer both without
    a request per keystroke. Around 20KB, fetched once when a profile screen
    opens.

    A state whose `districts` come back empty is one we hold no list for; the
    form should let that district be typed rather than picked, because
    refusing to save over a gap in our own data would stop somebody booking.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            'states': [
                {'name': name, 'districts': districts_for(name)}
                for name in INDIAN_STATES
            ],
        })


class ServiceAvailabilityView(APIView):
    """
    GET /api/vendors/availability/?service=<id>&state=<name>&district=<name>

    Whether anyone can actually do this service where the customer lives, and
    who is around if not.

      available        can the booking go ahead here
      vendor_count     how many vendors cover it here
      vendors_elsewhere  vendors who do this service in *other* places, each
                       carrying the state and district their card shows

    `district` is optional and narrows the answer: a vendor who covers only
    part of a state is counted for their part and nobody else's. Leave it off
    and the question is asked of the state alone.

    A blank or unknown state answers `available: true` with
    `state_known: false`: not knowing where somebody is is not a reason to
    stop them booking. Guests, and customers who have not filled in a profile
    yet, come through here.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        service = _get_object_or_404(
            Service, id=request.query_params.get('service'), is_active=True
        )

        state = (request.query_params.get('state') or '').strip()
        district = (request.query_params.get('district') or '').strip()
        if not state:
            return Response({
                'service': service.id,
                'state': '',
                'district': '',
                'state_known': False,
                'available': True,
                'vendor_count': 0,
                'vendors_elsewhere': [],
            })

        # Everyone who could actually be put on this job, anywhere.
        candidates = (
            Vendor.objects.bookable()
            .for_service(service)
            .select_related('user')
            .prefetch_related('categories', 'subcategories', 'services',
                              'service_regions')
        )

        here = candidates.serving_area(state, district)
        vendor_count = here.count()

        elsewhere = []
        if not vendor_count:
            # Pros first -- they are the ones with a photo and a profile to
            # open -- then the best reviewed of everybody else.
            others = (
                candidates.outside_area(state, district)
                .with_review_stats()
                .order_by('-is_pro', 'pro_sort_order',
                          F('avg_rating').desc(nulls_last=True), 'id')[:ELSEWHERE_LIMIT]
            )
            elsewhere = ProVendorCardSerializer(
                others, many=True, context={'request': request}
            ).data

        return Response({
            'service': service.id,
            'state': canonical_state(state),
            'district': district_label(district),
            'state_known': True,
            'available': bool(vendor_count),
            'vendor_count': vendor_count,
            'vendors_elsewhere': elsewhere,
        })
