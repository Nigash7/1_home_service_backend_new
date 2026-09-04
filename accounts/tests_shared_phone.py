"""
Tests for a phone number that holds both a customer and a vendor account.

Sign-in resolves a phone *within a role*, so one number can carry one of each
and the two never reach for one another. The trap is the username: a new
customer's username is their phone number, and usernames are unique across
every role, so a vendor an admin happened to name after their number must not
break that customer's sign-in.
"""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import OTPRequest, User
from vendors.models import Vendor

PHONE = '9876543210'


class SharedPhoneSignInTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _sign_in(self, phone=PHONE):
        """
        Signs in with a live code.

        The row is made here rather than through send-otp, which holds a
        60-second cooldown between codes that a test signing in twice would
        otherwise trip.
        """
        otp = OTPRequest.objects.create(
            phone_number=phone, code='123456',
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        return self.client.post(
            reverse('verify-otp'),
            {'phone_number': phone, 'code': otp.code},
            format='json',
        )

    def _vendor(self, username, phone=None):
        user = User.objects.create_user(
            username=username, password='pw12345', role=User.Role.VENDOR,
            first_name='Ravi', phone_number=phone,
        )
        return Vendor.objects.create(user=user, service_area='North')

    def test_a_vendor_on_the_number_does_not_become_the_customer(self):
        """Sign-in must make a customer account, not hand back the vendor."""
        vendor = self._vendor('ravi_plumber', phone=PHONE)

        res = self._sign_in()

        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res.json()['user']['id'], vendor.user_id)
        self.assertEqual(
            User.objects.filter(
                phone_number=PHONE, role=User.Role.CUSTOMER).count(), 1)

    def test_a_vendor_named_after_the_number_does_not_break_sign_in(self):
        """Usernames are unique across roles; the customer takes a suffix."""
        self._vendor(PHONE, phone=PHONE)

        res = self._sign_in()

        self.assertEqual(res.status_code, 200)
        customer_user = User.objects.get(
            phone_number=PHONE, role=User.Role.CUSTOMER)
        self.assertNotEqual(customer_user.username, PHONE)
        self.assertTrue(customer_user.username.startswith(PHONE))

    def test_signing_in_again_reuses_the_same_customer_account(self):
        self._vendor(PHONE, phone=PHONE)

        first = self._sign_in()
        second = self._sign_in()

        self.assertEqual(
            first.json()['user']['id'], second.json()['user']['id'])
        self.assertEqual(
            User.objects.filter(
                phone_number=PHONE, role=User.Role.CUSTOMER).count(), 1)


class VendorSignupPhoneTests(TestCase):
    """The same rule from the other side: the vendor app's own signup."""

    def setUp(self):
        self.client = APIClient()

    def test_an_existing_customer_may_register_as_a_vendor(self):
        User.objects.create_user(
            username=PHONE, phone_number=PHONE, role=User.Role.CUSTOMER,
        )

        from vendors.serializers import VendorSignupSerializer

        serializer = VendorSignupSerializer()
        # No exception: a customer on this number is not a vendor clash.
        self.assertEqual(serializer.validate_phone_number(PHONE), PHONE)

    def test_a_second_vendor_on_one_number_is_refused(self):
        from rest_framework.serializers import ValidationError
        from vendors.serializers import VendorSignupSerializer

        User.objects.create_user(
            username='ravi_plumber', phone_number=PHONE,
            role=User.Role.VENDOR,
        )

        with self.assertRaises(ValidationError):
            VendorSignupSerializer().validate_phone_number(PHONE)
