"""
Tests for the Razorpay integration, driven through the real API.

The gateway module is patched throughout -- these check our own rules, not
Razorpay's. Most of the risk here is a customer getting a booking marked paid
without paying, so the forgery paths get as much attention as the happy one.
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from services.models import ServiceCategory
from vendors.models import Vendor, VendorBankAccount

from .models import Payment, WebhookEvent, to_paise, to_rupees

KEY_ID = 'rzp_test_TESTKEY'
KEY_SECRET = 'test-secret'
WEBHOOK_SECRET = 'test-webhook-secret'


def checkout_signature(order_id, payment_id, secret=KEY_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(),
                    hashlib.sha256).hexdigest()


def webhook_signature(body: bytes, secret=WEBHOOK_SECRET):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def captured_payload(order_id, payment_id='pay_TEST1', amount=250000,
                     event='payment.captured'):
    return {
        'event': event,
        'payload': {'payment': {'entity': {
            'id': payment_id, 'order_id': order_id, 'amount': amount,
            'status': 'captured', 'method': 'upi',
        }}},
    }


@override_settings(
    RAZORPAY_KEY_ID=KEY_ID,
    RAZORPAY_KEY_SECRET=KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET,
    RAZORPAY_CURRENCY='INR',
    RAZORPAY_IS_LIVE=False,
)
class PaymentTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = User.objects.create_user(
            username='cust1', password='pw12345', role=User.Role.CUSTOMER
        )
        self.customer = Customer.objects.create(user=self.user)

        self.other_user = User.objects.create_user(
            username='cust2', password='pw12345', role=User.Role.CUSTOMER
        )
        self.other_customer = Customer.objects.create(user=self.other_user)

        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.booking = Booking.objects.create(
            customer=self.customer,
            category=self.category,
            preferred_date='2026-09-01',
            preferred_time='10:00',
            amount=Decimal('2500.00'),
        )

    def auth(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def make_payment(self, order_id='order_TEST1', **kwargs):
        defaults = dict(
            booking=self.booking, customer=self.customer,
            razorpay_order_id=order_id, amount=self.booking.amount,
            currency='INR',
        )
        defaults.update(kwargs)
        return Payment.objects.create(**defaults)


class MoneyConversionTests(TestCase):
    def test_rupees_to_paise_does_not_lose_a_paisa(self):
        # int(19.99 * 100) is 1998 in float arithmetic -- the bug this guards.
        self.assertEqual(to_paise(Decimal('19.99')), 1999)
        self.assertEqual(to_paise(Decimal('2500.00')), 250000)
        self.assertEqual(to_paise(0), 0)

    def test_paise_round_trip(self):
        self.assertEqual(to_rupees(1999), Decimal('19.99'))
        self.assertEqual(to_rupees(250000), Decimal('2500.00'))


class CreateOrderTests(PaymentTestBase):
    @patch('payments.gateway.create_order')
    def test_creates_order_for_own_booking(self, create_order):
        create_order.return_value = {'id': 'order_TEST1'}
        self.auth()

        res = self.client.post(reverse('payment-create-order'),
                               {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['order_id'], 'order_TEST1')
        self.assertEqual(res.data['amount'], 250000)      # paise
        self.assertEqual(res.data['key_id'], KEY_ID)
        self.assertFalse(res.data['is_live'])
        self.assertEqual(Payment.objects.count(), 1)

    @patch('payments.gateway.create_order')
    def test_amount_comes_from_booking_not_request(self, create_order):
        """A customer naming their own price must be ignored entirely."""
        create_order.return_value = {'id': 'order_TEST1'}
        self.auth()

        res = self.client.post(
            reverse('payment-create-order'),
            {'booking_id': self.booking.pk, 'amount': 1, 'amount_paise': 1},
            format='json',
        )

        self.assertEqual(res.status_code, 201)
        self.assertEqual(create_order.call_args.kwargs['amount_paise'], 250000)
        self.assertEqual(Payment.objects.get().amount, Decimal('2500.00'))

    @patch('payments.gateway.create_order')
    def test_cannot_pay_for_someone_elses_booking(self, create_order):
        create_order.return_value = {'id': 'order_TEST1'}
        self.auth(self.other_user)

        res = self.client.post(reverse('payment-create-order'),
                               {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(res.status_code, 404)
        create_order.assert_not_called()

    @patch('payments.gateway.create_order')
    def test_reuses_open_order_at_same_amount(self, create_order):
        create_order.return_value = {'id': 'order_TEST1'}
        self.auth()
        url = reverse('payment-create-order')

        first = self.client.post(url, {'booking_id': self.booking.pk}, format='json')
        second = self.client.post(url, {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(first.data['order_id'], second.data['order_id'])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(create_order.call_count, 1)

    @patch('payments.gateway.create_order')
    def test_reprice_starts_a_new_order(self, create_order):
        create_order.side_effect = [{'id': 'order_A'}, {'id': 'order_B'}]
        self.auth()
        url = reverse('payment-create-order')

        self.client.post(url, {'booking_id': self.booking.pk}, format='json')
        self.booking.amount = Decimal('3000.00')
        self.booking.save(update_fields=['amount'])
        res = self.client.post(url, {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(res.data['order_id'], 'order_B')
        self.assertEqual(res.data['amount'], 300000)

    @patch('payments.gateway.create_order')
    def test_rejects_already_paid_booking(self, create_order):
        self.booking.payment_status = Booking.PaymentStatus.PAID
        self.booking.save(update_fields=['payment_status'])
        self.auth()

        res = self.client.post(reverse('payment-create-order'),
                               {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(res.status_code, 400)
        create_order.assert_not_called()

    @patch('payments.gateway.create_order')
    def test_rejects_cancelled_booking(self, create_order):
        self.booking.status = Booking.Status.CANCELLED
        self.booking.save(update_fields=['status'])
        self.auth()

        res = self.client.post(reverse('payment-create-order'),
                               {'booking_id': self.booking.pk}, format='json')

        self.assertEqual(res.status_code, 400)
        create_order.assert_not_called()

    def test_requires_authentication(self):
        res = self.client.post(reverse('payment-create-order'),
                               {'booking_id': self.booking.pk}, format='json')
        self.assertIn(res.status_code, (401, 403))


class VerifyPaymentTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.payment = self.make_payment()
        self.auth()

    def post_verify(self, signature=None, payment_id='pay_TEST1'):
        return self.client.post(reverse('payment-verify'), {
            'razorpay_order_id': self.payment.razorpay_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature or checkout_signature(
                self.payment.razorpay_order_id, payment_id
            ),
        }, format='json')

    @patch('payments.gateway.fetch_payment')
    def test_valid_signature_marks_booking_paid(self, fetch):
        fetch.return_value = {'id': 'pay_TEST1', 'order_id': 'order_TEST1',
                              'amount': 250000, 'status': 'captured',
                              'method': 'upi'}

        res = self.post_verify()

        self.assertEqual(res.status_code, 200)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.CAPTURED)
        self.assertEqual(self.payment.method, 'upi')
        self.assertIsNotNone(self.payment.captured_at)
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)

    @patch('payments.gateway.fetch_payment')
    def test_forged_signature_is_rejected(self, fetch):
        res = self.post_verify(signature='deadbeef')

        self.assertEqual(res.status_code, 400)
        fetch.assert_not_called()
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertNotEqual(self.booking.payment_status,
                            Booking.PaymentStatus.PAID)

    @patch('payments.gateway.fetch_payment')
    def test_signature_valid_but_razorpay_says_not_captured(self, fetch):
        """A real signature on a payment that never completed must not pass."""
        fetch.return_value = {'id': 'pay_TEST1', 'order_id': 'order_TEST1',
                              'amount': 250000, 'status': 'failed',
                              'error_description': 'insufficient funds'}

        res = self.post_verify()

        self.assertEqual(res.status_code, 400)
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.payment_status,
                            Booking.PaymentStatus.PAID)

    @patch('payments.gateway.fetch_payment')
    def test_underpayment_is_rejected(self, fetch):
        fetch.return_value = {'id': 'pay_TEST1', 'order_id': 'order_TEST1',
                              'amount': 100, 'status': 'captured'}

        res = self.post_verify()

        self.assertEqual(res.status_code, 400)
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.payment_status,
                            Booking.PaymentStatus.PAID)

    @patch('payments.gateway.fetch_payment')
    def test_payment_belonging_to_another_order_is_rejected(self, fetch):
        fetch.return_value = {'id': 'pay_TEST1', 'order_id': 'order_SOMEONE_ELSE',
                              'amount': 250000, 'status': 'captured'}

        res = self.post_verify()

        self.assertEqual(res.status_code, 400)

    @patch('payments.gateway.fetch_payment')
    def test_cannot_verify_another_customers_order(self, fetch):
        self.auth(self.other_user)
        res = self.post_verify()

        self.assertEqual(res.status_code, 404)
        fetch.assert_not_called()


class WebhookTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.payment = self.make_payment()
        self.url = reverse('payment-webhook-razorpay')

    def post_webhook(self, payload, signature=None, event_id='evt_1'):
        body = json.dumps(payload).encode()
        return self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature or webhook_signature(body),
            HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )

    def test_captured_webhook_marks_paid(self):
        res = self.post_webhook(captured_payload('order_TEST1'))

        self.assertEqual(res.status_code, 200)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.CAPTURED)
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertTrue(WebhookEvent.objects.get(event_id='evt_1').processed)

    def test_unsigned_webhook_is_rejected(self):
        body = json.dumps(captured_payload('order_TEST1')).encode()
        res = self.client.post(self.url, data=body,
                               content_type='application/json')

        self.assertEqual(res.status_code, 400)
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.payment_status,
                            Booking.PaymentStatus.PAID)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_forged_signature_is_rejected(self):
        res = self.post_webhook(captured_payload('order_TEST1'),
                                signature='deadbeef')

        self.assertEqual(res.status_code, 400)
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.payment_status,
                            Booking.PaymentStatus.PAID)

    @override_settings(RAZORPAY_WEBHOOK_SECRET='')
    def test_webhook_refused_when_no_secret_configured(self):
        """An unsigned endpoint would be a public 'mark this paid' button."""
        body = json.dumps(captured_payload('order_TEST1')).encode()
        res = self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=webhook_signature(body),
        )

        self.assertEqual(res.status_code, 400)

    def test_replayed_delivery_is_processed_once(self):
        payload = captured_payload('order_TEST1')
        first = self.post_webhook(payload, event_id='evt_dup')
        second = self.post_webhook(payload, event_id='evt_dup')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WebhookEvent.objects.filter(event_id='evt_dup').count(), 1)

    def test_webhook_after_browser_verify_does_not_double_capture(self):
        """The two paths race by design; the second must be a no-op."""
        self.payment.mark_captured(payment_id='pay_TEST1', method='card')
        captured_at = Payment.objects.get(pk=self.payment.pk).captured_at

        res = self.post_webhook(captured_payload('order_TEST1'))

        self.assertEqual(res.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.captured_at, captured_at)
        self.assertEqual(self.payment.method, 'card')

    def test_failed_webhook_records_reason(self):
        payload = {
            'event': 'payment.failed',
            'payload': {'payment': {'entity': {
                'id': 'pay_X', 'order_id': 'order_TEST1', 'amount': 250000,
                'status': 'failed', 'error_description': 'card declined',
            }}},
        }
        res = self.post_webhook(payload)

        self.assertEqual(res.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertIn('card declined', self.payment.failure_reason)

    def test_refund_webhook_reverses_the_booking(self):
        self.payment.mark_captured(payment_id='pay_TEST1')
        self.booking.payment_status = Booking.PaymentStatus.PAID
        self.booking.save(update_fields=['payment_status'])

        payload = {
            'event': 'refund.processed',
            'payload': {'payment': {'entity': {
                'id': 'pay_TEST1', 'order_id': 'order_TEST1',
                'amount': 250000, 'amount_refunded': 250000,
            }}},
        }
        res = self.post_webhook(payload, event_id='evt_refund')

        self.assertEqual(res.status_code, 200)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.REFUNDED)
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.UNPAID)

    def test_partial_refund_keeps_booking_paid(self):
        self.payment.mark_captured(payment_id='pay_TEST1')
        self.booking.payment_status = Booking.PaymentStatus.PAID
        self.booking.save(update_fields=['payment_status'])

        payload = {
            'event': 'refund.processed',
            'payload': {'payment': {'entity': {
                'id': 'pay_TEST1', 'order_id': 'order_TEST1',
                'amount': 250000, 'amount_refunded': 50000,
            }}},
        }
        self.post_webhook(payload, event_id='evt_partial')

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(self.payment.amount_refunded, Decimal('500.00'))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)

    def test_webhook_for_unknown_order_is_acknowledged(self):
        """Answer 200 or Razorpay retries an order we will never have."""
        res = self.post_webhook(captured_payload('order_NEVER_SEEN'))
        self.assertEqual(res.status_code, 200)


class EscrowReleaseTests(PaymentTestBase):
    def setUp(self):
        super().setUp()
        self.vendor_user = User.objects.create_user(
            username='vend1', password='pw12345', role=User.Role.VENDOR
        )
        self.vendor = Vendor.objects.create(user=self.vendor_user)

        # Releasing requires somewhere to send the money, so every vendor in
        # these tests has payout details on file.
        VendorBankAccount.objects.create(
            vendor=self.vendor,
            account_holder_name='Ramesh Kumar',
            account_number='123456789012',
            ifsc_code='SBIN0001234',
        )
        self.payment = self.make_payment()
        self.payment.mark_captured(payment_id='pay_TEST1')

    def test_captured_money_is_held_by_default(self):
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)
        self.assertEqual(self.payment.refundable_amount, Decimal('2500.00'))

    def test_cannot_release_before_booking_is_completed(self):
        from . import services

        self.booking.status = Booking.Status.IN_PROGRESS
        self.booking.vendor = self.vendor
        self.booking.save(update_fields=['status', 'vendor'])

        with self.assertRaises(ValueError):
            services.release_to_vendor(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)

    def test_release_on_completed_booking(self):
        from . import services

        self.booking.status = Booking.Status.COMPLETED
        self.booking.vendor = self.vendor
        self.booking.save(update_fields=['status', 'vendor'])

        services.release_to_vendor(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.RELEASED)
        self.assertIsNotNone(self.payment.released_at)

    def test_released_money_is_no_longer_refundable(self):
        from . import services

        self.booking.status = Booking.Status.COMPLETED
        self.booking.vendor = self.vendor
        self.booking.save(update_fields=['status', 'vendor'])
        services.release_to_vendor(self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refundable_amount, Decimal('0.00'))

    def test_cannot_release_twice(self):
        from . import services

        self.booking.status = Booking.Status.COMPLETED
        self.booking.vendor = self.vendor
        self.booking.save(update_fields=['status', 'vendor'])
        services.release_to_vendor(self.payment)

        with self.assertRaises(ValueError):
            services.release_to_vendor(self.payment)


class BookingPaymentStatusTests(PaymentTestBase):
    def test_reports_true_state_after_a_lost_callback(self):
        self.make_payment().mark_captured(payment_id='pay_TEST1')
        self.auth()

        res = self.client.get(
            reverse('payment-booking-status', args=[self.booking.pk])
        )

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['is_paid'])
        self.assertEqual(len(res.data['payments']), 1)

    def test_cannot_read_another_customers_booking(self):
        self.make_payment()
        self.auth(self.other_user)

        res = self.client.get(
            reverse('payment-booking-status', args=[self.booking.pk])
        )

        self.assertEqual(res.status_code, 404)
