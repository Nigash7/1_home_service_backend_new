"""
Tests for one person holding both a customer and a vendor account.

That is a normal thing here: somebody books work in the customer app and takes
work in the vendor app, on the one phone. Customer sign-in finds its account
by phone *and* role, so the two never reach for each other -- which means a
customer on the number must not stop an admin saving the vendor, and only a
second *vendor* on it is a real clash.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from services.models import ServiceCategory
from vendors.models import Vendor

from .testing import sign_in

PHONE = '9876543210'


class VendorPhoneTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(
            username='phoneadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(name='Plumbing')

        # The same human, already booking work on this number.
        self.customer = Customer.objects.create(
            user=User.objects.create_user(
                username=PHONE, phone_number=PHONE, first_name='Ravi',
                role=User.Role.CUSTOMER,
            )
        )

    def _vendor(self, username='ravi_plumber', phone=None):
        user = User.objects.create_user(
            username=username, password='pw12345', role=User.Role.VENDOR,
            first_name='Ravi', phone_number=phone,
        )
        vendor = Vendor.objects.create(user=user, service_area='North')
        vendor.categories.set([self.category])
        return vendor

    def _edit_payload(self, vendor, **overrides):
        payload = {
            'username': vendor.user.username,
            'first_name': vendor.user.first_name,
            'last_name': '',
            'email': '',
            'phone_number': vendor.user.phone_number or '',
            'service_area': vendor.service_area,
            'address': '',
            'state': '',
            'district': '',
            'verification_status': vendor.verification_status,
            'status': vendor.status,
            'is_available': 'on',
            'categories': [self.category.id],
            'service_states': [],
        }
        payload.update(overrides)
        return payload

    # ---------- editing ----------

    def test_a_customer_on_the_number_does_not_block_the_vendor_save(self):
        vendor = self._vendor(phone=PHONE)

        res = self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, first_name='Ravi Kumar'),
        )

        self.assertEqual(res.status_code, 302)
        vendor.user.refresh_from_db()
        self.assertEqual(vendor.user.first_name, 'Ravi Kumar')
        self.assertEqual(vendor.user.phone_number, PHONE)

    def test_giving_a_vendor_a_customers_number_is_allowed(self):
        vendor = self._vendor(phone=None)

        res = self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, phone_number=PHONE),
        )

        self.assertEqual(res.status_code, 302)
        vendor.user.refresh_from_db()
        self.assertEqual(vendor.user.phone_number, PHONE)

    def test_another_vendor_on_the_number_is_still_refused(self):
        self._vendor(username='other_plumber', phone=PHONE)
        vendor = self._vendor(username='ravi_plumber', phone=None)

        res = self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, phone_number=PHONE),
        )

        self.assertEqual(res.status_code, 200)
        vendor.user.refresh_from_db()
        self.assertIsNone(vendor.user.phone_number)

    def test_the_refusal_names_the_vendor_holding_the_number(self):
        self._vendor(username='other_plumber', phone=PHONE)
        vendor = self._vendor(username='ravi_plumber', phone=None)

        res = self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, phone_number=PHONE),
            follow=True,
        )

        self.assertContains(res, 'already uses this phone number')
        self.assertContains(res, 'Ravi')

    def test_a_vendor_keeps_their_own_number_on_save(self):
        """The vendor's own number must not read as a clash with themselves."""
        vendor = self._vendor(phone=PHONE)

        res = self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor),
        )

        self.assertEqual(res.status_code, 302)

    # ---------- adding ----------

    def test_adding_a_vendor_on_a_customers_number_is_allowed(self):
        res = self.client.post(reverse('vendor_add'), {
            'username': 'ravi_plumber',
            'password': 'pw123456',
            'first_name': 'Ravi',
            'last_name': '',
            'email': '',
            'phone_number': PHONE,
            'service_area': 'South',
            'address': '',
            'state': '',
            'district': '',
            'verification_status': 'VERIFIED',
            'status': 'AVAILABLE',
            'is_available': 'on',
            'categories': [self.category.id],
            'service_states': [],
        })

        self.assertEqual(res.status_code, 302)
        vendor = Vendor.objects.get(user__username='ravi_plumber')
        self.assertEqual(vendor.user.phone_number, PHONE)
        # And the customer account on that number is untouched.
        self.assertEqual(
            User.objects.filter(phone_number=PHONE).count(), 2)

    def test_adding_a_second_vendor_on_one_number_is_refused(self):
        self._vendor(username='other_plumber', phone=PHONE)

        res = self.client.post(reverse('vendor_add'), {
            'username': 'ravi_plumber',
            'password': 'pw123456',
            'first_name': 'Ravi',
            'last_name': '',
            'email': '',
            'phone_number': PHONE,
            'service_area': 'South',
            'address': '',
            'verification_status': 'VERIFIED',
            'status': 'AVAILABLE',
            'is_available': 'on',
            'categories': [self.category.id],
            'service_states': [],
        })

        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            Vendor.objects.filter(user__username='ravi_plumber').exists())
