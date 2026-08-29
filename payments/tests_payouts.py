"""
Tests for RazorpayX payouts.

This is the direction where a mistake is expensive: money leaving. The cases
that matter most are the ones where a vendor could be paid twice — a retried
request, a double-clicked button, a webhook arriving mid-flight — so those get
more attention than the happy path.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from services.models import ServiceCategory
from vendors.models import Vendor, VendorBankAccount
from vendors.payout_services import name_match_score, normalise_name

from . import services
from .models import Payment, Payout
from .payoutx import PayoutError

X_SETTINGS = dict(
    RAZORPAY_KEY_ID='rzp_test_KEY',
    RAZORPAY_KEY_SECRET='secret',
    RAZORPAYX_KEY_ID='rzp_test_KEY',
    RAZORPAYX_KEY_SECRET='secret',
    RAZORPAYX_ACCOUNT_NUMBER='2323230000000000',
    RAZORPAYX_ENABLED=True,
    RAZORPAYX_PAYOUT_MODE='IMPS',
    RAZORPAYX_IMPS_LIMIT=200000,
    RAZORPAYX_VALIDATE_ACCOUNTS=False,
    RAZORPAYX_NAME_MATCH_THRESHOLD=0.85,
)


@override_settings(**X_SETTINGS)
class PayoutTestBase(TestCase):
    def setUp(self):
        vendor_user = User.objects.create_user(
            username='v1', password='pw12345', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=vendor_user, service_area='N')
        self.account = VendorBankAccount.objects.create(
            vendor=self.vendor,
            account_holder_name='Ramesh Kumar',
            account_number='123456789012',
            ifsc_code='SBIN0001234',
            razorpayx_contact_id='cont_1',
            razorpayx_fund_account_id='fa_1',
            is_verified=True,
        )

        customer_user = User.objects.create_user(
            username='c1', password='pw12345', role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=customer_user)

        category = ServiceCategory.objects.create(name='Plumbing')
        self.booking = Booking.objects.create(
            customer=self.customer, category=category, vendor=self.vendor,
            preferred_date='2026-09-01', preferred_time='10:00',
            amount=Decimal('2500.00'), status=Booking.Status.COMPLETED)

        self.payment = Payment.objects.create(
            booking=self.booking, customer=self.customer,
            razorpay_order_id='order_1', amount=Decimal('2500.00'))
        self.payment.mark_captured(payment_id='pay_1')

    def release(self):
        services.release_to_vendor(self.payment)
        self.payment.refresh_from_db()


class CreatePayoutTests(PayoutTestBase):
    @patch('payments.payoutx.create_payout')
    def test_sends_the_released_amount(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processing',
                               'mode': 'IMPS'}
        self.release()

        payout = services.create_payout(self.payment)

        self.assertEqual(create.call_args.kwargs['amount_paise'], 250000)
        self.assertEqual(create.call_args.kwargs['fund_account_id'], 'fa_1')
        self.assertEqual(payout.razorpay_payout_id, 'pout_1')
        self.assertEqual(payout.status, Payout.Status.PROCESSING)

    @patch('payments.payoutx.create_payout')
    def test_an_idempotency_key_is_always_sent(self, create):
        """Without it, a retried request is a second transfer."""
        create.return_value = {'id': 'pout_1', 'status': 'processing'}
        self.release()

        services.create_payout(self.payment)

        key = create.call_args.kwargs['idempotency_key']
        self.assertTrue(key.startswith('payout_'))

    @patch('payments.payoutx.create_payout')
    def test_calling_twice_does_not_send_twice(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processing'}
        self.release()

        first = services.create_payout(self.payment)
        second = services.create_payout(self.payment)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(Payout.objects.count(), 1)

    @patch('payments.payoutx.create_payout')
    def test_a_processed_payout_is_never_resent(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processed',
                               'utr': 'UTR123'}
        self.release()
        services.create_payout(self.payment)
        create.reset_mock()

        services.create_payout(self.payment)

        create.assert_not_called()

    @patch('payments.payoutx.create_payout')
    def test_cannot_pay_out_before_release(self, create):
        with self.assertRaises(ValueError):
            services.create_payout(self.payment)

        create.assert_not_called()

    @patch('payments.payoutx.create_payout')
    def test_cannot_pay_out_to_an_unverified_account(self, create):
        self.account.is_verified = False
        self.account.save(update_fields=['is_verified'])
        # Release still works — verification is a payout gate, not a release
        # gate — so this has to be blocked here.
        services.release_to_vendor(self.payment)

        with self.assertRaises(ValueError):
            services.create_payout(self.payment)

        create.assert_not_called()

    @patch('payments.payoutx.create_payout')
    def test_large_amounts_go_neft_not_imps(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processing'}
        self.payment.amount = Decimal('250000.00')
        self.payment.save(update_fields=['amount'])
        self.release()

        services.create_payout(self.payment)

        self.assertEqual(create.call_args.kwargs['mode'], 'NEFT')

    @override_settings(RAZORPAYX_ENABLED=False, RAZORPAYX_ACCOUNT_NUMBER='')
    def test_refused_when_payouts_are_not_configured(self):
        services.release_to_vendor(self.payment)

        with self.assertRaises(ValueError):
            services.create_payout(self.payment)


class PayoutFailureTests(PayoutTestBase):
    @patch('payments.payoutx.create_payout')
    def test_a_definite_refusal_is_recorded_as_failed(self, create):
        create.side_effect = PayoutError('Invalid account', retriable=False)
        self.release()

        with self.assertRaises(PayoutError):
            services.create_payout(self.payment)

        payout = Payout.objects.get()
        self.assertEqual(payout.status, Payout.Status.FAILED)
        self.assertIn('Invalid account', payout.failure_reason)
        self.assertTrue(payout.can_retry)

    @patch('payments.payoutx.create_payout')
    def test_a_timeout_is_not_recorded_as_failed(self, create):
        """
        The money may have moved. Marking it failed would invite a retry that
        pays the vendor a second time.
        """
        create.side_effect = PayoutError('Timed out', retriable=True)
        self.release()

        with self.assertRaises(PayoutError):
            services.create_payout(self.payment)

        payout = Payout.objects.get()
        self.assertEqual(payout.status, Payout.Status.PENDING)
        self.assertFalse(payout.can_retry)
        self.assertIn('Unconfirmed', payout.failure_reason)

    @patch('payments.payoutx.create_payout')
    def test_a_retry_after_a_timeout_replays_the_same_key(self, create):
        create.side_effect = PayoutError('Timed out', retriable=True)
        self.release()
        with self.assertRaises(PayoutError):
            services.create_payout(self.payment)
        first_key = Payout.objects.get().idempotency_key

        create.side_effect = None
        create.return_value = {'id': 'pout_1', 'status': 'processed'}
        services.create_payout(self.payment)

        self.assertEqual(create.call_args.kwargs['idempotency_key'], first_key)

    @patch('payments.payoutx.create_payout')
    def test_a_retry_after_a_definite_failure_uses_a_new_key(self, create):
        """No money moved, so this really is a new transfer."""
        create.side_effect = PayoutError('Invalid account', retriable=False)
        self.release()
        with self.assertRaises(PayoutError):
            services.create_payout(self.payment)
        first_key = Payout.objects.get().idempotency_key

        create.side_effect = None
        create.return_value = {'id': 'pout_1', 'status': 'processed'}
        services.create_payout(self.payment)

        payout = Payout.objects.get()
        self.assertNotEqual(payout.idempotency_key, first_key)
        self.assertEqual(payout.attempts, 2)

    @patch('payments.payoutx.create_payout')
    def test_a_reversal_puts_the_money_back_on_hold(self, create):
        """The bank sent it back, so it is ours again and refundable again."""
        create.return_value = {'id': 'pout_1', 'status': 'processed'}
        self.release()
        payout = services.create_payout(self.payment)

        services.apply_payout_result(payout, {'id': 'pout_1', 'status': 'reversed',
                                              'failure_reason': 'account closed'})

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)
        self.assertIsNone(self.payment.released_at)
        self.assertEqual(self.payment.refundable_amount, Decimal('2500.00'))

    @patch('payments.payoutx.create_payout')
    def test_a_queued_payout_is_not_a_failure(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'queued'}
        self.release()

        payout = services.create_payout(self.payment)

        self.assertEqual(payout.status, Payout.Status.QUEUED)
        self.assertFalse(payout.can_retry)


class NameMatchTests(TestCase):
    def test_identical_names_match(self):
        self.assertEqual(name_match_score('Ramesh Kumar', 'Ramesh Kumar'), 1.0)

    def test_case_and_titles_are_ignored(self):
        self.assertEqual(name_match_score('Ramesh Kumar', 'MR RAMESH KUMAR'), 1.0)

    def test_reordered_names_still_match(self):
        """'Kumar Ramesh' is the same person, not a mismatch."""
        self.assertGreaterEqual(
            name_match_score('Ramesh Kumar', 'KUMAR RAMESH'), 0.85)

    def test_a_different_person_does_not_match(self):
        self.assertLess(name_match_score('Ramesh Kumar', 'Sunita Sharma'), 0.5)

    def test_empty_names_score_zero(self):
        self.assertEqual(name_match_score('Ramesh Kumar', ''), 0.0)

    def test_normalise_strips_punctuation_and_titles(self):
        self.assertEqual(normalise_name('Mr. Ramesh   Kumar!'), 'ramesh kumar')


@override_settings(**X_SETTINGS)
class ValidationTests(PayoutTestBase):
    def apply(self, **results):
        from vendors import payout_services
        return payout_services.apply_validation_result(
            self.account, {'id': 'fav_1', 'results': results})

    def test_a_matching_name_auto_verifies(self):
        self.account.is_verified = False
        self.account.save(update_fields=['is_verified'])

        account = self.apply(account_status='active',
                             registered_name='RAMESH KUMAR')

        self.assertEqual(account.validation_status, account.ValidationStatus.ACTIVE)
        self.assertTrue(account.is_verified)
        self.assertEqual(account.registered_name, 'RAMESH KUMAR')

    def test_a_different_name_does_not_auto_verify(self):
        self.account.is_verified = False
        self.account.save(update_fields=['is_verified'])

        account = self.apply(account_status='active',
                             registered_name='SUNITA SHARMA')

        self.assertEqual(account.validation_status,
                         account.ValidationStatus.NAME_MISMATCH)
        self.assertFalse(account.is_verified)
        self.assertTrue(account.needs_attention)

    def test_an_invalid_account_never_verifies(self):
        self.account.is_verified = False
        self.account.save(update_fields=['is_verified'])

        account = self.apply(account_status='invalid')

        self.assertEqual(account.validation_status,
                         account.ValidationStatus.INVALID)
        self.assertFalse(account.is_verified)

    def test_a_bank_that_returns_no_name_is_not_a_mismatch(self):
        account = self.apply(account_status='active', registered_name='')

        self.assertEqual(account.validation_status,
                         account.ValidationStatus.ACTIVE)
        self.assertIsNone(account.name_match_score)

    def test_a_mismatch_does_not_strip_an_admins_verification(self):
        """A bank that reports names oddly must not undo a human decision."""
        self.assertTrue(self.account.is_verified)

        account = self.apply(account_status='active',
                             registered_name='SUNITA SHARMA')

        self.assertTrue(account.is_verified)

    def test_changing_the_account_clears_the_fund_account_id(self):
        """
        Otherwise the next payout goes to the old bank — the exact failure
        this whole flow exists to prevent.
        """
        from vendors import bank_services

        bank_services.save_bank_account(self.vendor, {
            'account_holder_name': 'Ramesh Kumar',
            'account_number': '999988887777',
            'ifsc_code': 'HDFC0001234',
            'account_type': 'SAVINGS',
            'upi_id': '',
        })

        self.account.refresh_from_db()
        self.assertEqual(self.account.razorpayx_fund_account_id, '')
        self.assertEqual(self.account.validation_status,
                         self.account.ValidationStatus.NOT_CHECKED)
        self.assertFalse(self.account.is_verified)
        # The contact is the vendor, not the account, so it survives.
        self.assertEqual(self.account.razorpayx_contact_id, 'cont_1')


@override_settings(**X_SETTINGS)
class DashboardPayoutTests(PayoutTestBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username='a1', password='pw12345', is_staff=True)
        session = self.client.session
        session['admin_user_id'] = self.admin.id
        session.save()

    @patch('payments.payoutx.create_payout')
    def test_releasing_also_sends_the_transfer(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processing'}

        self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.assertEqual(create.call_count, 1)
        self.assertTrue(Payout.objects.exists())

    @patch('payments.payoutx.create_payout')
    def test_a_failed_transfer_still_leaves_the_payment_released(self, create):
        create.side_effect = PayoutError('Invalid account', retriable=False)

        self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status,
                         Payment.PayoutStatus.RELEASED)
        self.assertEqual(Payout.objects.get().status, Payout.Status.FAILED)

    @patch('payments.payoutx.create_payout')
    def test_retry_endpoint_resends_a_failed_transfer(self, create):
        create.side_effect = PayoutError('Invalid account', retriable=False)
        self.client.post(reverse('release_payment', args=[self.payment.id]))

        create.side_effect = None
        create.return_value = {'id': 'pout_2', 'status': 'processed'}
        self.client.post(reverse('retry_payout', args=[self.payment.id]))

        payout = Payout.objects.get()
        self.assertEqual(payout.status, Payout.Status.PROCESSED)
        self.assertEqual(payout.attempts, 2)

    @patch('payments.payoutx.create_payout')
    def test_retry_does_nothing_to_a_transfer_in_flight(self, create):
        create.return_value = {'id': 'pout_1', 'status': 'processing'}
        self.client.post(reverse('release_payment', args=[self.payment.id]))
        create.reset_mock()

        self.client.post(reverse('retry_payout', args=[self.payment.id]))

        create.assert_not_called()
        self.assertEqual(Payout.objects.count(), 1)

    @patch('payments.payoutx.create_payout')
    def test_retry_requires_admin_login(self, create):
        session = self.client.session
        session.flush()

        self.client.post(reverse('retry_payout', args=[self.payment.id]))

        create.assert_not_called()
