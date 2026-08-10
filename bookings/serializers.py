from rest_framework import serializers
from .models import Booking, JobStartPhoto


class BookingCreateSerializer(serializers.ModelSerializer):
    """
    Used by the Customer app to create a new booking.
    Vendor is NOT set here -- it stays null until admin assigns one manually.
    Amount is calculated on the backend from services_json minus discount.
    """
    class Meta:
        model = Booking
        fields = [
            'id',
            'category', 'subcategory', 'services_json',
            'preferred_date', 'preferred_time', 'notes',
            'address_text', 'address_state', 'address_district',
            'address_pincode', 'customer_phone',
            'location_lat', 'location_lng',
            'amount',
            'discount_amount', 'coupon_code', 'discount_details',
            'form_submission',
            'status', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at', 'amount']

    def create(self, validated_data):
        customer = self.context['request'].user.customer_profile

        # Calculate subtotal from services_json
        services = validated_data.get('services_json', []) or []
        subtotal = 0
        for svc in services:
            try:
                price = float(svc.get('price', 0) or 0)
            except (ValueError, TypeError):
                price = 0
            try:
                qty = int(svc.get('qty', 1) or 1)
            except (ValueError, TypeError):
                qty = 1
            subtotal += price * qty

        # Subtract discount
        try:
            discount = float(validated_data.get('discount_amount', 0) or 0)
        except (ValueError, TypeError):
            discount = 0

        final_amount = max(subtotal - discount, 0)
        validated_data['amount'] = final_amount

        return Booking.objects.create(customer=customer, **validated_data)

class BookingListSerializer(serializers.ModelSerializer):
    """
    Used to LIST bookings -- shown to both Customer app (their own bookings)
    and Vendor app (their assigned jobs). Includes readable names, not just IDs.
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)
    customer_name = serializers.SerializerMethodField()
    customer_address = serializers.CharField(source='customer.address', read_only=True)
    customer_phone = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'category', 'category_name', 'subcategory', 'subcategory_name',
            'customer_name', 'customer_address', 'customer_phone',
            'vendor', 'vendor_name', 'preferred_date', 'preferred_time', 'status',
            'amount', 'payment_status', 'notes',
           'address_text', 'address_state', 'address_district', 'address_pincode',
            'location_lat', 'location_lng',
            'created_at', 'assigned_at', 'completed_at',
        ]

    def get_customer_name(self, obj):
        u = obj.customer.user
        return u.get_full_name() or u.username

    def get_customer_phone(self, obj):
        """
        Number the vendor should call. Prefers the phone captured on the booking
        itself (the customer may book for someone else's place), falling back to
        the number on their account for bookings made before that field existed.
        """
        return obj.customer_phone or obj.customer.user.phone_number or ''

    def get_vendor_name(self, obj):
        if obj.vendor:
            u = obj.vendor.user
            return u.get_full_name() or u.username
        return None


class JobStartPhotoSerializer(serializers.ModelSerializer):
    """
    Vendor uploads this when they arrive on-site to start the job.
    latitude/longitude come from the phone's GPS at the moment the photo is taken
    (captured client-side in Flutter using the geolocator package).
    """
    class Meta:
        model = JobStartPhoto
        fields = ['id', 'image', 'latitude', 'longitude', 'captured_at']
        read_only_fields = ['id', 'captured_at']