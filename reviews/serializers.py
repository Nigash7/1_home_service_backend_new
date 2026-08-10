from rest_framework import serializers
from .models import Review


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

    def create(self, validated_data):
        booking = validated_data['booking']
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