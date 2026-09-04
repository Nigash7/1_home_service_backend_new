from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Customer

from .models import EmailOTPRequest, User

SEND_URL = '/api/auth/email/send-otp/'
VERIFY_URL = '/api/auth/email/verify-otp/'
ME_URL = '/api/customers/me/'


class ExplodingEmailBackend:
    """Stands in for SMTP rejecting the recipient."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError('SMTP refused the recipient')

    def open(self):
        pass

    def close(self):
        pass


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='noreply@example.com',
)
class EmailOTPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='9000000001', phone_number='9000000001',
            first_name='Asha', role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        mail.outbox = []

    def _send(self, email='asha@example.com'):
        return self.client.post(SEND_URL, {'email': email}, format='json')

    def _latest_code(self):
        return EmailOTPRequest.objects.latest('created_at').code

    # ---------- sending ----------

    def test_send_emails_a_six_digit_code(self):
        res = self._send()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['asha@example.com'])

        otp = EmailOTPRequest.objects.get()
        self.assertEqual(len(otp.code), 6)
        self.assertTrue(otp.code.isdigit())
        self.assertIn(otp.code, mail.outbox[0].body)

    def test_sending_does_not_save_the_address_yet(self):
        self._send()
        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.user.email, '')
        self.assertFalse(self.customer.email_verified)

    def test_send_requires_a_signed_in_user(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self._send().status_code, 401)

    def test_send_rejects_a_malformed_address(self):
        res = self._send('not-an-email')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_is_rate_limited(self):
        self.assertEqual(self._send().status_code, 200)
        res = self._send()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_allowed_once_the_cooldown_passes(self):
        self._send()
        EmailOTPRequest.objects.update(
            created_at=timezone.now() - timedelta(seconds=120)
        )
        self.assertEqual(self._send().status_code, 200)
        self.assertEqual(len(mail.outbox), 2)

    def test_address_verified_by_someone_else_is_refused(self):
        other = User.objects.create_user(
            username='9000000002', phone_number='9000000002',
            email='asha@example.com', role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=other, email_verified=True)

        res = self._send('asha@example.com')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_address_someone_left_unverified_is_still_available(self):
        other = User.objects.create_user(
            username='9000000002', phone_number='9000000002',
            email='asha@example.com', role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=other, email_verified=False)

        self.assertEqual(self._send('asha@example.com').status_code, 200)

    def test_a_failed_send_leaves_no_row_holding_the_cooldown_open(self):
        with self.settings(EMAIL_BACKEND='accounts.tests.ExplodingEmailBackend'):
            res = self._send()
        self.assertEqual(res.status_code, 400)
        self.assertEqual(EmailOTPRequest.objects.count(), 0)

    # ---------- verifying ----------

    def test_correct_code_saves_and_marks_the_address_verified(self):
        self._send()
        res = self.client.post(
            VERIFY_URL,
            {'email': 'asha@example.com', 'code': self._latest_code()},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['email_verified'])

        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.user.email, 'asha@example.com')
        self.assertTrue(self.customer.email_verified)

    def test_address_is_normalised_to_lower_case(self):
        self._send('Asha@Example.com')
        res = self.client.post(
            VERIFY_URL,
            {'email': 'ASHA@EXAMPLE.COM', 'code': self._latest_code()},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'asha@example.com')

    def test_wrong_code_is_refused_and_counted(self):
        self._send()
        res = self.client.post(
            VERIFY_URL, {'email': 'asha@example.com', 'code': '000000'}, format='json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(EmailOTPRequest.objects.get().attempts, 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_code_is_locked_after_five_wrong_tries(self):
        self._send()
        code = self._latest_code()
        for _ in range(5):
            self.client.post(
                VERIFY_URL,
                {'email': 'asha@example.com', 'code': '000000'},
                format='json',
            )
        # Even the right code no longer works once the tries are spent.
        res = self.client.post(
            VERIFY_URL, {'email': 'asha@example.com', 'code': code}, format='json'
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_expired_code_is_refused(self):
        self._send()
        EmailOTPRequest.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        res = self.client.post(
            VERIFY_URL,
            {'email': 'asha@example.com', 'code': self._latest_code()},
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_code_cannot_be_replayed(self):
        self._send()
        code = self._latest_code()
        self.client.post(
            VERIFY_URL, {'email': 'asha@example.com', 'code': code}, format='json'
        )
        res = self.client.post(
            VERIFY_URL, {'email': 'asha@example.com', 'code': code}, format='json'
        )
        self.assertEqual(res.status_code, 400)

    def test_code_does_not_work_for_a_different_address(self):
        self._send('asha@example.com')
        res = self.client.post(
            VERIFY_URL,
            {'email': 'someone.else@example.com', 'code': self._latest_code()},
            format='json',
        )
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_another_users_code_does_not_work(self):
        self._send()
        code = self._latest_code()

        intruder = User.objects.create_user(
            username='9000000002', phone_number='9000000002',
            role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=intruder)
        other_client = APIClient()
        other_client.force_authenticate(user=intruder)

        res = other_client.post(
            VERIFY_URL, {'email': 'asha@example.com', 'code': code}, format='json'
        )
        self.assertEqual(res.status_code, 400)
        intruder.refresh_from_db()
        self.assertEqual(intruder.email, '')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ProfileEmailGuardTests(TestCase):
    """The profile form must not become a way around the verification step."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='9000000001', phone_number='9000000001',
            first_name='Asha', role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(
            user=self.user, address='1 Main St', state='Kerala',
            district='Ernakulam', pincode='682001',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        mail.outbox = []

    def _patch(self, **fields):
        return self.client.patch(ME_URL, fields, format='json')

    def test_unverified_new_address_is_refused(self):
        res = self._patch(email='asha@example.com')
        self.assertEqual(res.status_code, 400)
        self.assertIn('email', res.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_verified_address_saves(self):
        self.client.post(SEND_URL, {'email': 'asha@example.com'}, format='json')
        self.client.post(
            VERIFY_URL,
            {'email': 'asha@example.com', 'code': EmailOTPRequest.objects.get().code},
            format='json',
        )
        res = self._patch(email='asha@example.com', first_name='Asha K')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['email_verified'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Asha K')

    def test_saving_a_verified_address_keeps_it_normalised(self):
        self.user.email = 'asha@example.com'
        self.user.save(update_fields=['email'])
        self.customer.email_verified = True
        self.customer.save(update_fields=['email_verified'])

        # Different casing is the same address, so it saves -- and stays
        # stored in the one form the verification wrote.
        res = self._patch(email='Asha@Example.COM')
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'asha@example.com')
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.email_verified)

    def test_address_saved_before_this_feature_can_still_be_resaved(self):
        self.user.email = 'legacy@example.com'
        self.user.save(update_fields=['email'])

        res = self._patch(email='legacy@example.com', first_name='Asha K')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['email_verified'])

    def test_clearing_the_address_is_allowed_and_drops_the_badge(self):
        self.user.email = 'asha@example.com'
        self.user.save(update_fields=['email'])
        self.customer.email_verified = True
        self.customer.save(update_fields=['email_verified'])

        res = self._patch(email='')
        self.assertEqual(res.status_code, 200)
        self.customer.refresh_from_db()
        self.customer.user.refresh_from_db()
        self.assertEqual(self.customer.user.email, '')
        self.assertFalse(self.customer.email_verified)

    def test_profile_save_cannot_claim_verification_itself(self):
        res = self._patch(first_name='Asha K', email_verified=True)
        self.assertEqual(res.status_code, 200)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.email_verified)

    def test_profile_reports_the_verified_flag(self):
        res = self.client.get(ME_URL)
        self.assertEqual(res.status_code, 200)
        self.assertIn('email_verified', res.data)
        self.assertFalse(res.data['email_verified'])
