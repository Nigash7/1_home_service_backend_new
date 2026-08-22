from rest_framework import serializers
from services.serializers import ServiceCategorySerializer
from .models import Vendor


class VendorProfileSerializer(serializers.ModelSerializer):
    """
    Read-only view of a vendor's own profile for the Vendor app's home/profile screen.
    Vendor CANNOT edit their own verification_status or categories -- only admin can.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    categories = ServiceCategorySerializer(many=True, read_only=True)

    class Meta:
        model = Vendor
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number', 'email',
            'categories', 'service_area', 'address', 'verification_status', 'is_available',
            # The app reads these back to show whether a work location is on
            # file; without them the location screen can never confirm a save.
            'latitude', 'longitude',
        ]
        read_only_fields = ['verification_status', 'categories', 'latitude', 'longitude']


class VendorAvailabilitySerializer(serializers.ModelSerializer):
    """Lets a vendor toggle their own availability (busy/free) from the app."""
    class Meta:
        model = Vendor
        fields = ['is_available']
