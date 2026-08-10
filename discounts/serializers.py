from rest_framework import serializers
from .models import Discount, Coupon


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = [
            'id', 'name', 'description', 'discount_type', 'value',
            'max_discount', 'min_order_amount', 'valid_until',
        ]


class CouponValidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'description', 'discount_type', 'value',
            'max_discount', 'min_order_amount',
        ]