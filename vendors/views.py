from rest_framework import generics
from accounts.permissions import IsVendor
from .models import Vendor
from .serializers import VendorProfileSerializer, VendorAvailabilitySerializer


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
