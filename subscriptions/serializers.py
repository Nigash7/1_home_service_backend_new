from rest_framework import serializers

from .models import SubscriptionPlan, SubscriptionUpgradeRequest, VendorSubscription


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """The plan card the Vendor app shows. Read-only -- admins own the tiers."""

    billing_period_display = serializers.CharField(
        source='get_billing_period_display', read_only=True
    )
    is_free = serializers.BooleanField(read_only=True)
    features = serializers.ListField(
        source='feature_list', child=serializers.CharField(), read_only=True
    )

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'description', 'price', 'billing_period',
            'billing_period_display', 'is_free', 'features', 'is_default',
            'sort_order',
        ]


class VendorSubscriptionSerializer(serializers.ModelSerializer):
    """A vendor's own term, current or past."""

    plan = SubscriptionPlanSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_lifetime = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    is_expiring_soon = serializers.BooleanField(read_only=True)

    class Meta:
        model = VendorSubscription
        fields = [
            'id', 'plan', 'status', 'status_display', 'start_date', 'end_date',
            'amount_paid', 'is_active', 'is_lifetime', 'days_remaining',
            'is_expiring_soon', 'created_at',
        ]


class UpgradeRequestSerializer(serializers.ModelSerializer):
    """What the app shows while a vendor waits on an answer."""

    plan = SubscriptionPlanSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = SubscriptionUpgradeRequest
        fields = [
            'id', 'plan', 'status', 'status_display', 'is_open', 'note',
            'quoted_price', 'review_note', 'reviewed_at', 'created_at',
        ]


class UpgradeRequestCreateSerializer(serializers.Serializer):
    """
    Asking to move to a plan. Only the plan and an optional message -- the
    vendor decides nothing else, and approving is what starts a term.
    """

    plan = serializers.PrimaryKeyRelatedField(
        queryset=SubscriptionPlan.objects.filter(is_active=True)
    )
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, default='',
    )
