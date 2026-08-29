from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsVendor

from . import bank_services
from .bank_models import VendorBankAccount
from .bank_serializers import (
    VendorBankAccountSerializer, VendorBankAccountWriteSerializer,
)


class VendorBankAccountView(APIView):
    """
    GET  /api/vendors/me/bank-account/   -- the vendor's own payout details
    PUT  /api/vendors/me/bank-account/   -- add or replace them

    Scoped to `request.user.vendor_profile` throughout, so there is no id in
    the URL for anyone to walk. A vendor can only ever reach their own.

    The response never includes the full account number, only the last four.
    """
    permission_classes = [IsVendor]

    def get(self, request):
        account = VendorBankAccount.objects.filter(
            vendor=request.user.vendor_profile
        ).first()

        if account is None:
            # Not an error -- most vendors simply have not added one yet, and
            # the app needs to tell those two states apart to show the right
            # screen.
            return Response({'has_account': False, 'account': None})

        return Response({
            'has_account': True,
            'account': VendorBankAccountSerializer(account).data,
        })

    def put(self, request):
        serializer = VendorBankAccountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account, changed = bank_services.save_bank_account(
            request.user.vendor_profile,
            serializer.validated_data,
            changed_by=request.user,
        )

        return Response({
            'detail': (
                'Payout details saved. Our team will verify them before your '
                'next payout.'
                if changed else 'No changes to save.'
            ),
            'changed': changed,
            'account': VendorBankAccountSerializer(account).data,
        }, status=status.HTTP_200_OK)


class VendorBankAccountHistoryView(APIView):
    """
    GET /api/vendors/me/bank-account/history/

    Shown to the vendor so a change they did not make is visible to them
    rather than only to an admin.
    """
    permission_classes = [IsVendor]

    def get(self, request):
        changes = request.user.vendor_profile.bank_account_changes.all()[:20]
        return Response([
            {
                'changed_at': change.changed_at,
                'from_account': change.old_account_masked,
                'to_account': change.new_account_masked,
                'is_first_time': change.is_first_time,
                'by_you': change.changed_by_id == request.user.id,
            }
            for change in changes
        ])
