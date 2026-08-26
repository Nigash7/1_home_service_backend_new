from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User


class VendorNotApproved(APIException):
    """
    Correct credentials, but the vendor is not cleared to work yet.

    Deliberately distinct from a 401: the app needs to tell "wrong password"
    apart from "waiting on the admin" so it can show the right screen instead
    of sending the vendor back to re-type a password that was already correct.
    """
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'vendor_not_approved'


class AppTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    The shared login for both apps, with one extra rule: a vendor may only
    receive tokens once an admin has set their profile to VERIFIED.
    """

    PENDING_MESSAGE = (
        'Your profile is waiting for admin verification. '
        'You will be able to log in once it is approved.'
    )
    REJECTED_MESSAGE = (
        'Your application was not approved. Please contact support for details.'
    )
    NO_PROFILE_MESSAGE = (
        'This vendor account has no profile yet. Please contact support.'
    )

    def validate(self, attrs):
        data = super().validate(attrs)

        if self.user.role == User.Role.VENDOR:
            self._check_vendor_approved()

        return data

    def _check_vendor_approved(self):
        from vendors.models import Vendor

        vendor = getattr(self.user, 'vendor_profile', None)
        if vendor is None:
            raise VendorNotApproved({
                'code': 'VENDOR_NO_PROFILE',
                'verification_status': None,
                'detail': self.NO_PROFILE_MESSAGE,
            })

        if vendor.verification_status == Vendor.VerificationStatus.VERIFIED:
            return

        rejected = vendor.verification_status == Vendor.VerificationStatus.REJECTED
        raise VendorNotApproved({
            'code': 'VENDOR_NOT_APPROVED',
            'verification_status': vendor.verification_status,
            'detail': self.REJECTED_MESSAGE if rejected else self.PENDING_MESSAGE,
        })


class AppTokenObtainPairView(TokenObtainPairView):
    serializer_class = AppTokenObtainPairSerializer
