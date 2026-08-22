from rest_framework import serializers
from .models import Review, service_ids_in_booking


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['id', 'booking', 'rating', 'comment', 'service', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_booking(self, value):
        request = self.context['request']
        customer = request.user.customer_profile

        if value.customer != customer:
            raise serializers.ValidationError("This is not your booking.")
        if value.status != 'COMPLETED':
            raise serializers.ValidationError("You can only review completed bookings.")
        if not value.vendor:
            raise serializers.ValidationError("No vendor assigned to this booking.")
        if hasattr(value, 'review'):
            raise serializers.ValidationError("You have already reviewed this booking.")
        return value

    def validate(self, attrs):
        """A review may only point at a service the booking actually included."""
        service = attrs.get('service')
        booking = attrs.get('booking')
        if service and booking and service.id not in service_ids_in_booking(booking):
            raise serializers.ValidationError(
                {'service': 'That service was not part of this booking.'}
            )
        return attrs

    def create(self, validated_data):
        booking = validated_data['booking']

        # The app posts only booking/rating/comment, so without this every
        # customer review lands with service=NULL and never surfaces on the
        # service page. Booked exactly one service? Then it's unambiguous.
        if not validated_data.get('service'):
            service_ids = service_ids_in_booking(booking)
            if len(service_ids) == 1:
                validated_data.pop('service', None)
                validated_data['service_id'] = service_ids[0]

        return Review.objects.create(
            customer=booking.customer,
            vendor=booking.vendor,
            service_category=booking.category,
            **validated_data
        )


class ReviewListSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='service_category.name', default=None)

    class Meta:
        model = Review
        fields = [
            'id', 'booking', 'customer_name', 'vendor_name',
            'category_name', 'rating', 'comment', 'created_at',
        ]

    def get_customer_name(self, obj):
        if obj.reviewer_name:
            return obj.reviewer_name
        if obj.customer:
            u = obj.customer.user
            return u.get_full_name() or u.username
        return 'Customer'

    def get_vendor_name(self, obj):
        if obj.vendor:
            u = obj.vendor.user
            return u.get_full_name() or u.username
        return None


class VendorRatingSummarySerializer(serializers.Serializer):
    average_rating = serializers.FloatField()
    total_reviews = serializers.IntegerField()
    rating_breakdown = serializers.DictField()
    reviews = ReviewListSerializer(many=True)


class ServiceRatingSummarySerializer(serializers.Serializer):
    average_rating = serializers.FloatField()
    total_reviews = serializers.IntegerField()
    reviews = ReviewListSerializer(many=True)