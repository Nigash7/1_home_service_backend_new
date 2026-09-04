"""
Tests for the "where this vendor can serve" half of the Add/Edit Vendor form.

The dashboard's vendor form is a full-form save: it posts every place the
vendor covers, so unticking a state has to drop it and clearing a districts
box has to widen that state back out. These check that it does, and that a
vendor saved with nothing ticked goes back to covering everywhere rather than
disappearing from every customer's search.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from services.models import ServiceCategory
from vendors.models import Vendor, set_vendor_service_regions

from .testing import sign_in


class VendorFormRegionTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(
            username='statesadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(name='Plumbing')

    def _vendor(self, regions):
        user = User.objects.create_user(
            username='ravi', password='pw12345', role=User.Role.VENDOR,
            first_name='Ravi',
        )
        vendor = Vendor.objects.create(user=user, service_area='North')
        vendor.categories.set([self.category])
        set_vendor_service_regions(vendor, regions)
        return vendor

    def _edit_payload(self, vendor, **overrides):
        """Every field the edit form posts — a partial POST blanks the rest."""
        payload = {
            'username': vendor.user.username,
            'first_name': vendor.user.first_name,
            'last_name': vendor.user.last_name,
            'email': vendor.user.email,
            'phone_number': '',
            'service_area': vendor.service_area,
            'address': vendor.address,
            'state': vendor.state,
            'district': vendor.district,
            'verification_status': vendor.verification_status,
            'status': vendor.status,
            'is_available': 'on',
            'categories': [self.category.id],
            'service_states': [],
        }
        # The form posts one districts box per ticked state, named after it.
        for row in vendor.service_regions.all():
            if row.state not in payload['service_states']:
                payload['service_states'].append(row.state)
            if row.district:
                key = f'districts__{row.state}'
                payload[key] = ', '.join(
                    part for part in (payload.get(key, ''), row.district) if part
                )
        payload.update(overrides)
        return payload

    def test_adding_a_vendor_records_where_they_work(self):
        res = self.client.post(reverse('vendor_add'), {
            'username': 'newvendor',
            'password': 'pw123456',
            'first_name': 'New',
            'last_name': '',
            'email': '',
            'phone_number': '',
            'service_area': 'South',
            'address': '',
            'state': 'Kerala',
            'district': 'Ernakulam',
            'verification_status': 'VERIFIED',
            'status': 'AVAILABLE',
            'is_available': 'on',
            'categories': [self.category.id],
            'service_states': ['Kerala', 'Tamil Nadu'],
            'districts__Kerala': 'Ernakulam, Thrissur',
            'districts__Tamil Nadu': '',
        })
        self.assertEqual(res.status_code, 302)

        vendor = Vendor.objects.get(user__username='newvendor')
        self.assertEqual(vendor.state, 'Kerala')
        self.assertEqual(vendor.district, 'Ernakulam')
        self.assertEqual(
            sorted(vendor.service_region_labels),
            ['Kerala — Ernakulam, Thrissur', 'Tamil Nadu'],
        )

    def test_unticking_a_state_drops_it(self):
        vendor = self._vendor(['Kerala', 'Goa'])

        self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, service_states=['Kerala']),
        )

        vendor.refresh_from_db()
        self.assertEqual(vendor.service_region_labels, ['Kerala'])

    def test_naming_districts_narrows_a_state(self):
        vendor = self._vendor(['Kerala'])

        payload = self._edit_payload(vendor, service_states=['Kerala'])
        payload['districts__Kerala'] = 'Ernakulam, Thrissur'
        self.client.post(reverse('vendor_edit', args=[vendor.id]), payload)

        vendor.refresh_from_db()
        self.assertEqual(
            vendor.service_region_labels, ['Kerala — Ernakulam, Thrissur'])
        self.assertFalse(vendor.serves('Kerala', 'Kollam'))

    def test_clearing_the_districts_box_widens_the_state_again(self):
        vendor = self._vendor([('Kerala', 'Ernakulam')])

        payload = self._edit_payload(vendor, service_states=['Kerala'])
        payload['districts__Kerala'] = ''
        self.client.post(reverse('vendor_edit', args=[vendor.id]), payload)

        vendor.refresh_from_db()
        self.assertEqual(vendor.service_region_labels, ['Kerala'])
        self.assertTrue(vendor.serves('Kerala', 'Kollam'))

    def test_ticking_nothing_puts_the_vendor_back_everywhere(self):
        vendor = self._vendor(['Kerala'])

        self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor, service_states=[]),
        )

        vendor.refresh_from_db()
        self.assertEqual(vendor.service_region_labels, [])
        self.assertTrue(vendor.serves('Goa'))

    def test_saving_the_form_unchanged_leaves_the_coverage_alone(self):
        vendor = self._vendor(['Goa', ('Kerala', 'Ernakulam')])

        self.client.post(
            reverse('vendor_edit', args=[vendor.id]),
            self._edit_payload(vendor),
        )

        vendor.refresh_from_db()
        self.assertEqual(
            sorted(vendor.service_region_labels), ['Goa', 'Kerala — Ernakulam'])

    def test_the_form_ticks_the_states_the_vendor_already_covers(self):
        vendor = self._vendor([('Kerala', 'Ernakulam'), ('Kerala', 'Thrissur')])

        res = self.client.get(reverse('vendor_edit', args=[vendor.id]))

        ticked = {
            option['name']: option['districts']
            for option in res.context['state_options']
            if option['checked']
        }
        self.assertEqual(ticked, {'Kerala': 'Ernakulam, Thrissur'})
