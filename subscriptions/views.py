from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsVendor

from . import services as subscription_services
from .models import SubscriptionPlan, SubscriptionUpgradeRequest, VendorSubscription
from .serializers import (
    SubscriptionPlanSerializer,
    UpgradeRequestCreateSerializer,
    UpgradeRequestSerializer,
    VendorSubscriptionSerializer,
)


class SubscriptionPlanListView(generics.ListAPIView):
    """
    GET /api/subscriptions/plans/

    The tiers on offer. Open, so the signup screen can show them before an
    account exists.
    """
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True)


class MySubscriptionView(APIView):
    """
    GET /api/subscriptions/me/

    Everything the app's subscription screen needs in one call: the plan the
    vendor is on, an upgrade they are waiting on, what else is available, and
    the terms they have finished.

    `current` is null when they hold nothing -- which is not an error, and
    stops being the normal case once the free tier is set as the default.
    """
    permission_classes = [IsVendor]

    def get(self, request):
        vendor = request.user.vendor_profile

        # A term that lapsed while nobody was looking must not still read as
        # live on the vendor's own screen.
        VendorSubscription.objects.expire_due()

        current = VendorSubscription.objects.active_for(vendor)
        history = VendorSubscription.objects.filter(
            vendor=vendor
        ).select_related('plan')
        if current:
            history = history.exclude(pk=current.pk)

        pending = SubscriptionUpgradeRequest.objects.pending_for(vendor)

        return Response({
            'current': (
                VendorSubscriptionSerializer(current).data if current else None
            ),
            'pending_request': (
                UpgradeRequestSerializer(pending).data if pending else None
            ),
            'plans': SubscriptionPlanSerializer(
                SubscriptionPlan.objects.filter(is_active=True), many=True
            ).data,
            'history': VendorSubscriptionSerializer(history, many=True).data,
        })


class UpgradeRequestListCreateView(APIView):
    """
    GET  /api/subscriptions/upgrade-requests/  -- the vendor's own requests
    POST /api/subscriptions/upgrade-requests/  -- ask to move to a plan

    Asking never changes what the vendor holds. An admin answers from the
    dashboard, and approving is what starts the term.
    """
    permission_classes = [IsVendor]

    def get(self, request):
        requests = SubscriptionUpgradeRequest.objects.filter(
            vendor=request.user.vendor_profile
        ).select_related('plan')
        return Response(UpgradeRequestSerializer(requests, many=True).data)

    def post(self, request):
        serializer = UpgradeRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            upgrade_request = subscription_services.request_upgrade(
                request.user.vendor_profile,
                serializer.validated_data['plan'],
                note=serializer.validated_data.get('note', ''),
            )
        except subscription_services.SubscriptionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            UpgradeRequestSerializer(upgrade_request).data,
            status=status.HTTP_201_CREATED,
        )


class UpgradeRequestWithdrawView(APIView):
    """
    POST /api/subscriptions/upgrade-requests/<id>/withdraw/

    Changed their mind before anyone looked at it. Only their own, and only
    while it is still open.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        upgrade_request = SubscriptionUpgradeRequest.objects.filter(
            pk=pk, vendor=request.user.vendor_profile
        ).first()
        if upgrade_request is None:
            return Response(
                {'detail': 'No such request.'}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            subscription_services.withdraw_request(upgrade_request)
        except subscription_services.SubscriptionError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UpgradeRequestSerializer(upgrade_request).data)
