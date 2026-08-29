"""
Tests for vendor payout details.

The rules being protected: a vendor only ever reaches their own account, the
full number never leaves the server, changing the details clears verification,
and money cannot be released to a vendor with nowhere to send it.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment
from services.models import ServiceCategory

from . import bank_services
from .bank_models import VendorBankAccount, VendorBankAccountChange
from .models import Vendor

GOOD = {
    'account_holder_name': 'Ramesh Kumar',
    'account_number': '123456789012',
    'confirm_account_number': '123456789012',
    'ifsc_code': 'SBIN0001234',
    'bank_name': 'State Bank of India',
    'account_type': 'SAVINGS',
}


class BankAccountTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='vend1', password='pw12345', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=self.user, service_area='North')

        self.other_user = User.objects.create_user(
            username='vend2', password='pw12345', role=User.Role.VENDOR)
        self.other_vendor = Vendor.objects.create(
            user=self.other_user, service_area='South')

        self.url = reverse('vendor-bank-account')

    def auth(self, user=None):
        self.client.force_authenticate(user=user or self.user)


class SaveBankAccountTests(BankAccountTestBase):
    def test_vendor_adds_payout_details(self):
        self.auth()
        res = self.client.put(self.url, GOOD, format='json')

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['changed'])
        account = VendorBankAccount.objects.get(vendor=self.vendor)
        self.assertEqual(account.account_number, '123456789012')
        self.assertEqual(account.ifsc_code, 'SBIN0001234')
        self.assertFalse(account.is_verified)

    def test_response_never_carries_the_full_number(self):
        self.auth()
        res = self.client.put(self.url, GOOD, format='json')

        self.assertNotIn('123456789012', str(res.data))
        self.assertEqual(res.data['account']['account_number'], 'XXXXXXXX9012')

    def test_get_returns_masked_number_only(self):
        self.auth()
        self.client.put(self.url, GOOD, format='json')

        res = self.client.get(self.url)

        self.assertTrue(res.data['has_account'])
        self.assertEqual(res.data['account']['account_number'], 'XXXXXXXX9012')
        self.assertNotIn('123456789012', str(res.data))

    def test_get_without_an_account_is_not_an_error(self):
        self.auth()
        res = self.client.get(self.url)

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['has_account'])
        self.assertIsNone(res.data['account'])

    def test_ifsc_is_upper_cased(self):
        self.auth()
        self.client.put(self.url, {**GOOD, 'ifsc_code': 'sbin0001234'},
                        format='json')

        self.assertEqual(
            VendorBankAccount.objects.get(vendor=self.vendor).ifsc_code,
            'SBIN0001234',
        )

    def test_spaces_in_the_account_number_are_tolerated(self):
        self.auth()
        self.client.put(self.url, {
            **GOOD,
            'account_number': '1234 5678 9012',
            'confirm_account_number': '123456789012',
        }, format='json')

        self.assertEqual(
            VendorBankAccount.objects.get(vendor=self.vendor).account_number,
            '123456789012',
        )

    def test_requires_vendor_login(self):
        res = self.client.put(self.url, GOOD, format='json')
        self.assertIn(res.status_code, (401, 403))

    def test_a_customer_cannot_reach_this(self):
        customer_user = User.objects.create_user(
            username='c1', password='pw12345', role=User.Role.CUSTOMER)
        Customer.objects.create(user=customer_user)
        self.auth(customer_user)

        res = self.client.get(self.url)

        self.assertEqual(res.status_code, 403)

    def test_one_vendor_cannot_see_anothers_details(self):
        """There is no id in the URL, so this is scoped by construction."""
        self.auth()
        self.client.put(self.url, GOOD, format='json')

        self.auth(self.other_user)
        res = self.client.get(self.url)

        self.assertFalse(res.data['has_account'])


class ValidationTests(BankAccountTestBase):
    def setUp(self):
        super().setUp()
        self.auth()

    def assert_rejected(self, payload, field):
        res = self.client.put(self.url, {**GOOD, **payload}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn(field, res.data)
        self.assertFalse(VendorBankAccount.objects.exists())

    def test_mismatched_confirmation_is_rejected(self):
        """The typo this whole second field exists to catch."""
        self.assert_rejected(
            {'confirm_account_number': '123456789099'},
            'confirm_account_number',
        )

    def test_bad_ifsc_is_rejected(self):
        self.assert_rejected({'ifsc_code': 'NOTANIFSC'}, 'ifsc_code')

    def test_ifsc_without_the_fifth_zero_is_rejected(self):
        self.assert_rejected({'ifsc_code': 'SBIN1001234'}, 'ifsc_code')

    def test_letters_in_the_account_number_are_rejected(self):
        self.assert_rejected({
            'account_number': '12345678ABCD',
            'confirm_account_number': '12345678ABCD',
        }, 'account_number')

    def test_too_short_an_account_number_is_rejected(self):
        self.assert_rejected({
            'account_number': '12345',
            'confirm_account_number': '12345',
        }, 'account_number')

    def test_bad_upi_is_rejected(self):
        self.assert_rejected({'upi_id': 'not-a-upi-id'}, 'upi_id')

    def test_good_upi_is_accepted(self):
        res = self.client.put(
            self.url, {**GOOD, 'upi_id': 'Ramesh@OKAXIS'}, format='json')

        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            VendorBankAccount.objects.get(vendor=self.vendor).upi_id,
            'ramesh@okaxis',
        )

    def test_one_letter_name_is_rejected(self):
        self.assert_rejected({'account_holder_name': 'R'},
                             'account_holder_name')


class ChangingDetailsTests(BankAccountTestBase):
    def setUp(self):
        super().setUp()
        self.auth()
        self.client.put(self.url, GOOD, format='json')
        self.account = VendorBankAccount.objects.get(vendor=self.vendor)
        bank_services.verify_bank_account(self.vendor)

    def test_changing_the_account_clears_verification(self):
        """
        Otherwise a stolen session could redirect payouts to another bank and
        keep the verified badge that makes them look safe to pay.
        """
        self.client.put(self.url, {
            **GOOD,
            'account_number': '999988887777',
            'confirm_account_number': '999988887777',
        }, format='json')

        self.account.refresh_from_db()
        self.assertFalse(self.account.is_verified)
        self.assertIsNone(self.account.verified_at)

    def test_resaving_identical_details_keeps_verification(self):
        """Opening the form and saving unchanged is not a real change."""
        res = self.client.put(self.url, GOOD, format='json')

        self.account.refresh_from_db()
        self.assertFalse(res.data['changed'])
        self.assertTrue(self.account.is_verified)

    def test_a_change_is_recorded_with_masked_numbers_only(self):
        self.client.put(self.url, {
            **GOOD,
            'account_number': '999988887777',
            'confirm_account_number': '999988887777',
        }, format='json')

        change = VendorBankAccountChange.objects.filter(
            vendor=self.vendor).first()
        self.assertEqual(change.old_account_masked, 'XXXXXXXX9012')
        self.assertEqual(change.new_account_masked, 'XXXXXXXX7777')
        self.assertNotIn('999988887777', str(change.__dict__))

    def test_first_save_is_recorded_as_first_time(self):
        change = VendorBankAccountChange.objects.filter(
            vendor=self.vendor).last()
        self.assertTrue(change.is_first_time)

    def test_history_endpoint_shows_the_vendors_own_changes(self):
        self.client.put(self.url, {
            **GOOD,
            'account_number': '999988887777',
            'confirm_account_number': '999988887777',
        }, format='json')

        res = self.client.get(reverse('vendor-bank-account-history'))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 2)
        self.assertTrue(res.data[0]['by_you'])

    def test_a_vendor_only_ever_has_one_account(self):
        self.client.put(self.url, {
            **GOOD,
            'account_number': '999988887777',
            'confirm_account_number': '999988887777',
        }, format='json')

        self.assertEqual(
            VendorBankAccount.objects.filter(vendor=self.vendor).count(), 1)


class ReleaseNeedsAPayoutAccountTests(TestCase):
    """Money cannot be released to a vendor with nowhere to send it."""

    def setUp(self):
        vendor_user = User.objects.create_user(
            username='v1', password='pw12345', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=vendor_user, service_area='N')

        customer_user = User.objects.create_user(
            username='c1', password='pw12345', role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=customer_user)

        category = ServiceCategory.objects.create(name='Plumbing')
        self.booking = Booking.objects.create(
            customer=self.customer, category=category, vendor=self.vendor,
            preferred_date='2026-09-01', preferred_time='10:00',
            amount=Decimal('2500.00'), status=Booking.Status.COMPLETED,
        )
        self.payment = Payment.objects.create(
            booking=self.booking, customer=self.customer,
            razorpay_order_id='order_1', amount=Decimal('2500.00'))
        self.payment.mark_captured(payment_id='pay_1')

    def add_account(self):
        return VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ramesh Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234')

    def test_release_refused_without_payout_details(self):
        from payments import services

        with self.assertRaises(ValueError) as ctx:
            services.release_to_vendor(self.payment)

        self.assertIn('payout details', str(ctx.exception))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)

    def test_release_works_once_details_exist(self):
        from payments import services

        self.add_account()
        services.release_to_vendor(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status,
                         Payment.PayoutStatus.RELEASED)

    def test_unverified_details_do_not_block_release(self):
        """Verification is a warning in the dashboard, not a hard gate."""
        from payments import services

        account = self.add_account()
        self.assertFalse(account.is_verified)

        services.release_to_vendor(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status,
                         Payment.PayoutStatus.RELEASED)
