"""
Tests for the dashboard's refund and release controls.

The gateway is patched -- these check who is allowed to do what, and that a
refused action leaves the money exactly where it was. The rules worth
protecting: released money cannot be refunded, held money cannot be released
before the work is done, and no logged-out visitor can touch either.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.gateway import PaymentError
from payments.models import Payment
from services.models import ServiceCategory
from vendors.models import Vendor, VendorBankAccount


@override_settings(
    RAZORPAY_KEY_ID='rzp_test_KEY',
    RAZORPAY_KEY_SECRET='secret',
    RAZORPAY_CURRENCY='INR',
    RAZORPAY_IS_LIVE=False,
)
class DashboardPaymentControlsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', password='pw12345', is_staff=True,
        )

        customer_user = User.objects.create_user(
            username='cust1', password='pw12345', role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(user=customer_user)

        vendor_user = User.objects.create_user(
            username='vend1', password='pw12345', role=User.Role.VENDOR,
        )
        self.vendor = Vendor.objects.create(user=vendor_user)

        # Releasing requires somewhere to send the money, so every vendor in
        # these tests has payout details on file.
        VendorBankAccount.objects.create(
            vendor=self.vendor,
            account_holder_name='Ramesh Kumar',
            account_number='123456789012',
            ifsc_code='SBIN0001234',
        )

        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.booking = Booking.objects.create(
            customer=self.customer,
            category=self.category,
            vendor=self.vendor,
            preferred_date='2026-09-01',
            preferred_time='10:00',
            amount=Decimal('2500.00'),
            status=Booking.Status.COMPLETED,
            payment_status=Booking.PaymentStatus.PAID,
        )
        self.payment = Payment.objects.create(
            booking=self.booking,
            customer=self.customer,
            razorpay_order_id='order_TEST1',
            amount=Decimal('2500.00'),
            currency='INR',
        )
        self.payment.mark_captured(payment_id='pay_TEST1', method='upi')

    def login(self):
        session = self.client.session
        session['admin_user_id'] = self.admin.id
        session.save()

    # ------------------------------------------------------------- release

    def test_release_on_completed_booking(self):
        self.login()
        res = self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.assertEqual(res.status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.RELEASED)
        self.assertIsNotNone(self.payment.released_at)

    def test_release_refused_while_work_is_unfinished(self):
        self.booking.status = Booking.Status.IN_PROGRESS
        self.booking.save(update_fields=['status'])
        self.login()

        self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)

    def test_release_is_not_repeatable(self):
        self.login()
        url = reverse('release_payment', args=[self.payment.id])
        self.client.post(url)
        released_at = Payment.objects.get(pk=self.payment.pk).released_at

        self.client.post(url)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.released_at, released_at)

    def test_release_requires_admin_login(self):
        res = self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('dashboard_login'))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)

    def test_get_does_not_release(self):
        """A link-prefetcher or a stray refresh must not move money."""
        self.login()
        self.client.get(reverse('release_payment', args=[self.payment.id]))

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.HELD)

    # -------------------------------------------------------------- refund

    @patch('payments.gateway.refund')
    def test_full_refund_when_amount_is_blank(self, refund):
        refund.return_value = {'id': 'rfnd_1', 'amount': 250000}
        self.login()

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': '', 'reason': 'customer cancelled'})

        self.assertEqual(refund.call_args.kwargs['amount_paise'], 250000)
        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.payment.amount_refunded, Decimal('2500.00'))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.UNPAID)

    @patch('payments.gateway.refund')
    def test_partial_refund(self, refund):
        refund.return_value = {'id': 'rfnd_1', 'amount': 50000}
        self.login()

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': '500.00'})

        self.assertEqual(refund.call_args.kwargs['amount_paise'], 50000)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_REFUNDED)
        self.assertEqual(self.payment.amount_refunded, Decimal('500.00'))

    @patch('payments.gateway.refund')
    def test_two_partial_refunds_accumulate(self, refund):
        """The second refund must add to the first, not replace it."""
        refund.return_value = {'id': 'rfnd_1', 'amount': 50000}
        self.login()
        url = reverse('refund_payment', args=[self.payment.id])

        self.client.post(url, {'amount': '500.00'})
        self.client.post(url, {'amount': '500.00'})

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, Decimal('1000.00'))

    @patch('payments.gateway.refund')
    def test_cannot_refund_more_than_was_paid(self, refund):
        self.login()

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': '9999.00'})

        refund.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, Decimal('0'))

    @patch('payments.gateway.refund')
    def test_cannot_refund_after_release(self, refund):
        """The money is gone; refunding anyway would leave the books short."""
        self.login()
        self.client.post(reverse('release_payment', args=[self.payment.id]))

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': ''})

        refund.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.amount_refunded, Decimal('0'))
        self.assertEqual(self.payment.payout_status, Payment.PayoutStatus.RELEASED)

    @patch('payments.gateway.refund')
    def test_gateway_refusal_changes_nothing(self, refund):
        refund.side_effect = PaymentError('Could not process the refund.')
        self.login()

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': ''})

        self.payment.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.CAPTURED)
        self.assertEqual(self.payment.amount_refunded, Decimal('0'))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)

    @patch('payments.gateway.refund')
    def test_rubbish_amount_is_rejected(self, refund):
        self.login()

        self.client.post(reverse('refund_payment', args=[self.payment.id]),
                         {'amount': 'abc'})

        refund.assert_not_called()

    @patch('payments.gateway.refund')
    def test_refund_requires_admin_login(self, refund):
        res = self.client.post(reverse('refund_payment', args=[self.payment.id]),
                               {'amount': ''})

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('dashboard_login'))
        refund.assert_not_called()

    # ------------------------------------------- manual override is fenced

    def test_manual_payment_edit_blocked_once_razorpay_is_involved(self):
        """
        Hand-editing a gateway-paid booking would put our books out of step
        with Razorpay's, so the old manual form refuses.
        """
        self.login()

        self.client.post(reverse('update_payment', args=[self.booking.id]),
                         {'amount': '1.00', 'payment_status': 'UNPAID'})

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.amount, Decimal('2500.00'))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)

    def test_manual_payment_edit_still_works_without_a_gateway_payment(self):
        """Cash jobs still need the manual switch."""
        cash_booking = Booking.objects.create(
            customer=self.customer,
            category=self.category,
            preferred_date='2026-09-02',
            preferred_time='11:00',
            amount=Decimal('900.00'),
        )
        self.login()

        self.client.post(reverse('update_payment', args=[cash_booking.id]),
                         {'amount': '900.00', 'payment_status': 'PAID'})

        cash_booking.refresh_from_db()
        self.assertEqual(cash_booking.payment_status, Booking.PaymentStatus.PAID)

    # ------------------------------------------------------------- listing

    def test_payments_list_totals_only_count_held_money(self):
        self.login()
        res = self.client.get(reverse('payments_list'))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['totals']['held_count'], 1)
        self.assertEqual(res.context['totals']['held_amount'], Decimal('2500.00'))

    def test_released_money_leaves_the_held_total(self):
        self.login()
        self.client.post(reverse('release_payment', args=[self.payment.id]))

        res = self.client.get(reverse('payments_list'))

        self.assertEqual(res.context['totals']['held_count'], 0)

    def test_payments_list_search_by_booking_number(self):
        self.login()
        res = self.client.get(reverse('payments_list'),
                              {'search': str(self.booking.id)})

        self.assertEqual(len(res.context['payments'].object_list), 1)

    def test_payments_list_requires_admin_login(self):
        res = self.client.get(reverse('payments_list'))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('dashboard_login'))
