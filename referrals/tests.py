from datetime import date, time

from django.test import TestCase

from accounts.models import User
from bookings.models import Booking
from customers.models import Customer
from services.models import ServiceCategory

from .models import Referral, ReferralCode, ReferralProgram


def make_customer(phone, first_name):
    user = User.objects.create_user(
        username=phone, phone_number=phone, first_name=first_name,
        role=User.Role.CUSTOMER,
    )
    return Customer.objects.create(user=user)


class ReferralRewardTests(TestCase):
    def setUp(self):
        self.program = ReferralProgram.get_solo()
        self.referrer = make_customer('9000000001', 'Asha')
        self.friend = make_customer('9000000002', 'Bala')
        self.category = ServiceCategory.objects.create(name='Plumbing')

    def _booking(self, customer, status=Booking.Status.PENDING):
        return Booking.objects.create(
            customer=customer,
            category=self.category,
            preferred_date=date(2026, 1, 1),
            preferred_time=time(10, 0),
            amount=500,
            status=status,
        )

    def _referral(self):
        code = ReferralCode.for_customer(self.referrer)
        return Referral.objects.create(
            referrer=self.referrer, referred_customer=self.friend, code_used=code.code,
        )

    def test_code_is_stable_per_customer(self):
        first = ReferralCode.for_customer(self.referrer)
        second = ReferralCode.for_customer(self.referrer)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(len(first.code), 8)

    def test_completed_booking_marks_referral_earned(self):
        referral = self._referral()
        booking = self._booking(self.friend)

        booking.status = Booking.Status.COMPLETED
        booking.save()

        referral.refresh_from_db()
        self.assertEqual(referral.status, Referral.Status.EARNED)
        self.assertEqual(referral.reward_amount, self.program.referrer_reward)
        self.assertEqual(referral.first_booking, booking)
        self.assertIsNotNone(referral.earned_at)

    def test_uncompleted_booking_leaves_referral_pending(self):
        referral = self._referral()
        booking = self._booking(self.friend)

        booking.status = Booking.Status.IN_PROGRESS
        booking.save()

        referral.refresh_from_db()
        self.assertEqual(referral.status, Referral.Status.PENDING)

    def test_second_completed_booking_does_not_pay_twice(self):
        referral = self._referral()
        first = self._booking(self.friend, Booking.Status.COMPLETED)
        referral.refresh_from_db()
        self.assertEqual(referral.first_booking, first)

        second = self._booking(self.friend, Booking.Status.COMPLETED)

        referral.refresh_from_db()
        self.assertEqual(referral.status, Referral.Status.EARNED)
        self.assertEqual(referral.first_booking, first)
        self.assertNotEqual(referral.first_booking, second)

    def test_inactive_program_does_not_pay_out(self):
        self.program.is_active = False
        self.program.save()

        referral = self._referral()
        self._booking(self.friend, Booking.Status.COMPLETED)

        referral.refresh_from_db()
        self.assertEqual(referral.status, Referral.Status.PENDING)

    def test_someone_elses_booking_does_not_pay_out(self):
        referral = self._referral()
        self._booking(self.referrer, Booking.Status.COMPLETED)

        referral.refresh_from_db()
        self.assertEqual(referral.status, Referral.Status.PENDING)


class ReferralSignupTests(TestCase):
    def setUp(self):
        ReferralProgram.get_solo()
        self.referrer = make_customer('9000000001', 'Asha')
        self.code = ReferralCode.for_customer(self.referrer).code

    def _signup(self, phone, referral_code):
        """Runs the same path VerifyOTPSerializer takes for a new customer."""
        from accounts.otp_serializers import VerifyOTPSerializer

        serializer = VerifyOTPSerializer()
        serializer._validated_data = {'referral_code': referral_code}
        customer = make_customer(phone, 'New')
        serializer._attach_referral(customer)
        return customer

    def test_valid_code_records_referral(self):
        friend = self._signup('9000000003', self.code.lower())
        referral = Referral.objects.get(referred_customer=friend)
        self.assertEqual(referral.referrer, self.referrer)
        self.assertEqual(referral.status, Referral.Status.PENDING)

    def test_unknown_code_is_ignored(self):
        friend = self._signup('9000000004', 'NOTACODE')
        self.assertFalse(Referral.objects.filter(referred_customer=friend).exists())

    def test_blank_code_is_ignored(self):
        friend = self._signup('9000000005', '')
        self.assertFalse(Referral.objects.filter(referred_customer=friend).exists())
