from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'booking', 'razorpay_order_id', 'razorpay_payment_id',
            'amount', 'amount_refunded', 'currency', 'status', 'payout_status',
            'method', 'is_paid', 'created_at', 'captured_at',
        ]
        read_only_fields = fields


class CreateOrderSerializer(serializers.Serializer):
    """
    Only the booking is accepted. The amount is read from the booking on the
    server -- taking it from the request would let a customer name their price.
    """
    booking_id = serializers.IntegerField()


class VerifyPaymentSerializer(serializers.Serializer):
    """The three values Razorpay Checkout hands back to the app on success."""
    razorpay_order_id = serializers.CharField(max_length=64)
    razorpay_payment_id = serializers.CharField(max_length=64)
    razorpay_signature = serializers.CharField(max_length=128)
