from decimal import Decimal
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from payments.models import Payment
from services.models import ServiceCategory
from vendors.models import Vendor, VendorBankAccount


class BookingDetailRendersTests(TestCase):
    """The payment card is template-only, so it needs an actual render."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='a', password='p', is_staff=True)
        cu = User.objects.create_user(username='c', password='p',
                                      role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=cu)
        vu = User.objects.create_user(username='v', password='p',
                                      role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=vu)

        # Releasing requires somewhere to send the money, so every vendor in
        # these tests has payout details on file.
        VendorBankAccount.objects.create(
            vendor=self.vendor,
            account_holder_name='Ramesh Kumar',
            account_number='123456789012',
            ifsc_code='SBIN0001234',
        )
        self.cat = ServiceCategory.objects.create(name='Plumbing')
        session = self.client.session
        session['admin_user_id'] = self.admin.id
        session.save()

    def booking(self, status=Booking.Status.COMPLETED):
        return Booking.objects.create(
            customer=self.customer, category=self.cat, vendor=self.vendor,
            preferred_date='2026-09-01', preferred_time='10:00',
            amount=Decimal('2500.00'), status=status,
        )

    def test_renders_with_held_payment_and_offers_release(self):
        b = self.booking()
        p = Payment.objects.create(
            booking=b, customer=self.customer, razorpay_order_id='order_1',
            amount=Decimal('2500.00'))
        p.mark_captured(payment_id='pay_1', method='upi')

        res = self.client.get(reverse('booking_detail', args=[b.id]))
        html = res.content.decode()

        self.assertEqual(res.status_code, 200)
        self.assertIn('Release to vendor', html)
        self.assertIn(reverse('release_payment', args=[p.id]), html)
        self.assertIn(reverse('refund_payment', args=[p.id]), html)
        self.assertIn('TEST', html)
        # Manual override must be fenced off once Razorpay is involved.
        self.assertNotIn('Update Payment', html)

    def test_release_button_disabled_before_completion(self):
        b = self.booking(status=Booking.Status.IN_PROGRESS)
        p = Payment.objects.create(
            booking=b, customer=self.customer, razorpay_order_id='order_2',
            amount=Decimal('2500.00'))
        p.mark_captured(payment_id='pay_2')

        html = self.client.get(
            reverse('booking_detail', args=[b.id])).content.decode()

        self.assertIn('Available once the booking is completed.', html)
        self.assertNotIn(reverse('release_payment', args=[p.id]), html)

    def test_released_payment_offers_neither_action(self):
        from payments import services
        b = self.booking()
        p = Payment.objects.create(
            booking=b, customer=self.customer, razorpay_order_id='order_3',
            amount=Decimal('2500.00'))
        p.mark_captured(payment_id='pay_3')
        services.release_to_vendor(p)

        html = self.client.get(
            reverse('booking_detail', args=[b.id])).content.decode()

        self.assertIn('No longer refundable', html)
        self.assertNotIn(reverse('refund_payment', args=[p.id]), html)

    def test_cash_booking_keeps_the_manual_form(self):
        b = self.booking()

        html = self.client.get(
            reverse('booking_detail', args=[b.id])).content.decode()

        self.assertIn('Update Payment', html)
        self.assertNotIn('Razorpay', html)

    def test_shows_where_a_release_would_send_the_money(self):
        b = self.booking()
        p = Payment.objects.create(
            booking=b, customer=self.customer, razorpay_order_id='order_4',
            amount=Decimal('2500.00'))
        p.mark_captured(payment_id='pay_4')

        html = self.client.get(
            reverse('booking_detail', args=[b.id])).content.decode()

        self.assertIn('XXXXXXXX9012', html)
        self.assertIn('SBIN0001234', html)
        self.assertIn('not yet verified', html)
        # Masked only -- the full number must never reach a rendered page.
        self.assertNotIn('123456789012', html)

    def test_release_blocked_when_the_vendor_has_no_payout_account(self):
        self.vendor.bank_account.delete()
        b = self.booking()
        p = Payment.objects.create(
            booking=b, customer=self.customer, razorpay_order_id='order_5',
            amount=Decimal('2500.00'))
        p.mark_captured(payment_id='pay_5')

        html = self.client.get(
            reverse('booking_detail', args=[b.id])).content.decode()

        self.assertIn('No payout account on file', html)
        self.assertNotIn(reverse('release_payment', args=[p.id]), html)


class VendorDetailPayoutTests(TestCase):
    """The admin-facing side of a vendor's payout details."""

    def setUp(self):
        from vendors.models import VendorBankAccount

        self.admin = User.objects.create_user(
            username='a2', password='p', is_staff=True)
        vu = User.objects.create_user(username='v2', password='p',
                                      role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=vu, service_area='N')
        self.account = VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ramesh Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
            bank_name='State Bank of India')
        session = self.client.session
        session['admin_user_id'] = self.admin.id
        session.save()

    def test_page_shows_masked_details_and_a_verify_button(self):
        html = self.client.get(
            reverse('vendor_detail', args=[self.vendor.id])).content.decode()

        self.assertIn('XXXXXXXX9012', html)
        self.assertNotIn('123456789012', html)
        self.assertIn('Mark as verified', html)

    def test_admin_can_verify(self):
        self.client.post(reverse('verify_bank_account', args=[self.vendor.id]))

        self.account.refresh_from_db()
        self.assertTrue(self.account.is_verified)
        self.assertEqual(self.account.verified_by, self.admin)

    def test_verify_requires_login(self):
        self.client.logout()
        session = self.client.session
        session.flush()

        self.client.post(reverse('verify_bank_account', args=[self.vendor.id]))

        self.account.refresh_from_db()
        self.assertFalse(self.account.is_verified)

    def test_vendor_without_an_account_sees_the_empty_state(self):
        self.account.delete()

        html = self.client.get(
            reverse('vendor_detail', args=[self.vendor.id])).content.decode()

        self.assertIn('No payout account yet', html)
        self.assertNotIn('Mark as verified', html)


@override_settings(
    RAZORPAYX_ACCOUNT_NUMBER='2323230000000000',
    RAZORPAYX_ENABLED=True,
    RAZORPAYX_KEY_ID='rzp_test_KEY',
    RAZORPAYX_KEY_SECRET='secret',
)
class PayoutRendersTests(TestCase):
    """The transfer panel is template-only, so it needs a real render."""

    def setUp(self):
        from payments.models import Payout

        self.admin = User.objects.create_user(
            username='a3', password='p', is_staff=True)
        cu = User.objects.create_user(username='c3', password='p',
                                      role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=cu)
        vu = User.objects.create_user(username='v3', password='p',
                                      role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(user=vu, service_area='N')
        VendorBankAccount.objects.create(
            vendor=self.vendor, account_holder_name='Ramesh Kumar',
            account_number='123456789012', ifsc_code='SBIN0001234',
            razorpayx_fund_account_id='fa_1', is_verified=True)
        cat = ServiceCategory.objects.create(name='Wiring')
        self.booking = Booking.objects.create(
            customer=self.customer, category=cat, vendor=self.vendor,
            preferred_date='2026-09-01', preferred_time='10:00',
            amount=Decimal('2500.00'), status=Booking.Status.COMPLETED)
        self.payment = Payment.objects.create(
            booking=self.booking, customer=self.customer,
            razorpay_order_id='order_9', amount=Decimal('2500.00'))
        self.payment.mark_captured(payment_id='pay_9')
        self.payment.payout_status = Payment.PayoutStatus.RELEASED
        self.payment.save(update_fields=['payout_status'])

        session = self.client.session
        session['admin_user_id'] = self.admin.id
        session.save()

    def payout(self, status, **kwargs):
        from payments.models import Payout

        return Payout.objects.create(
            payment=self.payment, vendor=self.vendor,
            amount=Decimal('2500.00'), idempotency_key='payout_test1',
            status=status, **kwargs)

    def html(self):
        return self.client.get(
            reverse('booking_detail', args=[self.booking.id])).content.decode()

    def test_a_processed_transfer_shows_its_utr_and_no_retry(self):
        p = self.payout('processed', utr='UTR12345', mode='IMPS')

        html = self.html()

        self.assertIn('UTR12345', html)
        self.assertIn('Paid', html)
        self.assertNotIn(reverse('retry_payout', args=[self.payment.id]), html)

    def test_a_failed_transfer_offers_a_retry(self):
        self.payout('failed', failure_reason='Invalid account')

        html = self.html()

        self.assertIn('Invalid account', html)
        self.assertIn(reverse('retry_payout', args=[self.payment.id]), html)

    def test_a_transfer_in_flight_offers_no_retry(self):
        self.payout('processing')

        html = self.html()

        self.assertNotIn(reverse('retry_payout', args=[self.payment.id]), html)

    def test_a_queued_transfer_explains_the_balance(self):
        self.payout('queued')

        self.assertIn('balance', self.html())
