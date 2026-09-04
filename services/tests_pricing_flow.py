"""
End-to-end check of every pricing type, using the worked examples from the
spec.

Not unit tests of the helpers -- those live in tests_pricing.py. This walks the
whole path each type actually takes:

    admin creates the service on the dashboard form
      -> the customer app reads it from /api/services/categories/
      -> a cart line goes to POST /api/bookings/
      -> the booking is charged rate x quantity

so a type that looks right in isolation but loses its quantity somewhere in
the middle cannot pass.
"""

import sys
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from dashboard.testing import sign_in

from .models import Service, ServiceCategory
from .pricing import PricingType

# One row per pricing type, straight from the spec's "Example" column:
#   type, rate, quantity, expected label, expected amount
def show(text):
    """
    Prints the summary table without letting the console decide whether the
    test passes.

    Windows defaults to cp1252, which cannot encode the rupee sign, and an
    encoding error on a convenience print would fail a run whose assertions
    all held.
    """
    encoding = sys.stdout.encoding or 'utf-8'
    sys.stdout.write(
        text.encode(encoding, 'replace').decode(encoding, 'replace') + '\n'
    )


SPEC = [
    (PricingType.FIXED, '800', 1, '₹800', '800'),
    (PricingType.STARTING_FROM, '499', 1, 'From ₹499', '499'),
    (PricingType.PER_HOUR, '300', 3, '₹300 / hour', '900'),
    (PricingType.PER_DAY, '1000', 2, '₹1,000 / day', '2000'),
    (PricingType.PER_SQ_FT, '15', 1000, '₹15 / sq ft', '15000'),
    (PricingType.PER_SQ_M, '150', 100, '₹150 / m²', '15000'),
    (PricingType.PER_VISIT, '500', 2, '₹500 / visit', '1000'),
    (PricingType.PER_ITEM, '200', 5, '₹200 / item', '1000'),
    (PricingType.PER_UNIT, '100', 20, '₹100 / unit', '2000'),
    (PricingType.PER_KM, '20', 10, '₹20 / km', '200'),
    (PricingType.PER_ROOM, '400', 4, '₹400 / room', '1600'),
    (PricingType.PER_SEAT, '100', 10, '₹100 / seat', '1000'),
    (PricingType.PER_KG, '50', 10, '₹50 / kg', '500'),
]


class PricingFlowTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.category = ServiceCategory.objects.create(name='Home Services')

        admin = User.objects.create_user(
            username='flowadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)

        self.customer_user = User.objects.create_user(
            username='9000000009', phone_number='9000000009',
            first_name='Asha', role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=self.customer_user)

    # ---- the three steps of the flow ----------------------------------

    def _create_on_dashboard(self, name, price, pricing_type):
        """Step 1: an admin fills in the Add Service form."""
        res = self.client.post(
            reverse('service_add_cat', args=[self.category.id]),
            {
                'name': name,
                'description': '',
                'price': price,
                'pricing_type': pricing_type,
                'duration_minutes': '60',
                'is_active': 'on',
            },
        )
        self.assertEqual(res.status_code, 302, f'{name} was not saved')
        return Service.objects.get(name=name)

    def _read_from_api(self, service):
        """Step 2: the customer app reads the category tree."""
        res = self.api.get(reverse('service-category-list'))
        self.assertEqual(res.status_code, 200)

        for category in res.data:
            for entry in category['services']:
                if entry['id'] == service.id:
                    return entry
        self.fail(f'{service.name} never reached the services API')

    def _book(self, service, quantity):
        """Step 3: the cart line becomes a booking."""
        self.api.force_authenticate(user=self.customer_user)
        res = self.api.post(
            reverse('booking-create'),
            {
                'category': self.category.id,
                'preferred_date': '2026-10-01',
                'preferred_time': '10:00',
                'services_json': [{
                    'id': service.id,
                    'name': service.name,
                    'price': str(service.price),
                    'qty': quantity,
                }],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.data)
        from bookings.models import Booking
        return Booking.objects.get(id=res.data['id'])

    # ---- the check itself ---------------------------------------------

    def test_every_pricing_type_survives_the_whole_flow(self):
        rows = []

        for pricing_type, price, quantity, label, expected in SPEC:
            with self.subTest(pricing_type=pricing_type):
                service = self._create_on_dashboard(
                    f'Svc {pricing_type}', price, pricing_type)
                payload = self._read_from_api(service)
                booking = self._book(service, quantity)

                # The label the card shows.
                self.assertEqual(payload['price_label'], label)
                # Whether the app asks for an amount.
                self.assertEqual(
                    payload['needs_quantity'],
                    pricing_type not in (
                        PricingType.FIXED, PricingType.STARTING_FROM),
                )
                self.assertFalse(payload['is_quote_only'])
                # And the money at the end of it.
                self.assertEqual(
                    booking.amount, Decimal(expected),
                    f'{pricing_type}: {price} x {quantity}',
                )

                rows.append(
                    f'  {pricing_type:<14} {label:<18} '
                    f'x {quantity:<6} = ₹{booking.amount:,.0f}'
                )

        show('\n--- pricing flow: dashboard -> API -> booking ---')
        show('\n'.join(rows))

    def test_a_fractional_quantity_survives_the_whole_flow(self):
        """₹50/kg x 2.5 kg. The int(qty) bug would have charged ₹100."""
        service = self._create_on_dashboard('Laundry', '50', PricingType.PER_KG)
        booking = self._book(service, 2.5)

        self.assertEqual(booking.amount, Decimal('125'))

    def test_a_quote_service_is_flagged_and_priced_by_nobody(self):
        service = self._create_on_dashboard(
            'House Painting', '0', PricingType.CUSTOM_QUOTE)
        payload = self._read_from_api(service)

        self.assertTrue(payload['is_quote_only'])
        self.assertFalse(payload['needs_quantity'])
        self.assertEqual(payload['price_label'], 'Price on request')
        show('\n  CUSTOM_QUOTE   Price on request   -> tender flow')

    def test_a_quote_price_left_on_the_record_is_never_shown(self):
        """An admin who typed a number into a quote service must not leak it."""
        service = self._create_on_dashboard(
            'Interior Design', '25000', PricingType.CUSTOM_QUOTE)
        payload = self._read_from_api(service)

        self.assertEqual(payload['price_label'], 'Price on request')
        self.assertNotIn('25,000', payload['price_label'])

    def test_two_lines_of_different_types_add_up(self):
        """The mixed cart from the spec: ₹15 x 1000 sq ft plus a flat ₹800."""
        tiling = self._create_on_dashboard('Tiling', '15', PricingType.PER_SQ_FT)
        ac = self._create_on_dashboard('AC Service', '800', PricingType.FIXED)

        self.api.force_authenticate(user=self.customer_user)
        res = self.api.post(
            reverse('booking-create'),
            {
                'category': self.category.id,
                'preferred_date': '2026-10-01',
                'preferred_time': '10:00',
                'services_json': [
                    {'id': tiling.id, 'price': '15', 'qty': 1000},
                    {'id': ac.id, 'price': '800', 'qty': 1},
                ],
            },
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.data)

        from bookings.models import Booking
        self.assertEqual(
            Booking.objects.get(id=res.data['id']).amount, Decimal('15800'))
