"""
Tests for how a service's price becomes an amount.

`Service.price` is only ever a rate. The rule these protect is that the rate
and the thing it is a rate of stay together everywhere: the label a card
shows, the subtotal a booking is charged, and the total a discount is worked
out against. A per-sq-ft line that displayed ₹15 and charged ₹15 would be the
bug.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from customers.models import Customer
from dashboard.testing import sign_in

from .models import Service, ServiceCategory
from .pricing import (
    PricingType, line_total, parse_quantity, price_label,
)


class PriceLabelTests(TestCase):
    """One line per pricing type, as the cards show it."""

    def test_every_type_from_the_spec(self):
        cases = [
            (PricingType.FIXED, 800, '₹800'),
            (PricingType.STARTING_FROM, 499, 'From ₹499'),
            (PricingType.PER_HOUR, 300, '₹300 / hour'),
            (PricingType.PER_DAY, 1000, '₹1,000 / day'),
            (PricingType.PER_SQ_FT, 15, '₹15 / sq ft'),
            (PricingType.PER_SQ_M, 150, '₹150 / m²'),
            (PricingType.PER_VISIT, 500, '₹500 / visit'),
            (PricingType.PER_ITEM, 200, '₹200 / item'),
            (PricingType.PER_UNIT, 100, '₹100 / unit'),
            (PricingType.PER_KM, 20, '₹20 / km'),
            (PricingType.PER_ROOM, 400, '₹400 / room'),
            (PricingType.PER_SEAT, 100, '₹100 / seat'),
            (PricingType.PER_KG, 50, '₹50 / kg'),
            (PricingType.CUSTOM_QUOTE, 0, 'Price on request'),
        ]
        for pricing_type, price, expected in cases:
            with self.subTest(pricing_type=pricing_type):
                self.assertEqual(price_label(price, pricing_type), expected)

    def test_a_quote_never_shows_a_figure(self):
        """Even when a price was left on the record, it is not for showing."""
        self.assertEqual(
            price_label(9999, PricingType.CUSTOM_QUOTE), 'Price on request')

    def test_whole_rupees_carry_no_decimals(self):
        self.assertEqual(price_label(800, PricingType.FIXED), '₹800')
        self.assertEqual(price_label(Decimal('800.00'), PricingType.FIXED), '₹800')

    def test_paise_survive_when_there_are_any(self):
        self.assertEqual(
            price_label(Decimal('12.50'), PricingType.PER_KG), '₹12.50 / kg')


class QuantityParsingTests(TestCase):
    """
    The quantity on a cart line is a Decimal, not an int.

    1000 sq ft and 2.5 kg both have to survive, because the customer was shown
    a total worked out from them.
    """

    def test_a_measurement_is_not_truncated(self):
        self.assertEqual(parse_quantity('2.5'), Decimal('2.5'))
        self.assertEqual(parse_quantity(1000), Decimal('1000'))

    def test_missing_or_unreadable_means_one(self):
        self.assertEqual(parse_quantity(None), Decimal('1'))
        self.assertEqual(parse_quantity(''), Decimal('1'))
        self.assertEqual(parse_quantity('abc'), Decimal('1'))

    def test_zero_and_negative_mean_one(self):
        """What a missing quantity has always meant here, and no free money."""
        self.assertEqual(parse_quantity(0), Decimal('1'))
        self.assertEqual(parse_quantity('-5'), Decimal('1'))

    def test_a_line_total_is_the_two_multiplied(self):
        self.assertEqual(
            line_total({'price': '15', 'qty': '1000'}), Decimal('15000'))
        self.assertEqual(
            line_total({'price': '50', 'qty': '2.5'}), Decimal('125.0'))


class BookingSubtotalTests(TestCase):
    """The amount a booking is actually charged."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Tiling')
        user = User.objects.create_user(
            username='cust', password='pw12345', role=User.Role.CUSTOMER,
            phone_number='9990001111',
        )
        Customer.objects.create(user=user)
        self.user = user

    def _book(self, services, discount='0'):
        from bookings.serializers import BookingCreateSerializer

        class _Request:
            pass

        request = _Request()
        request.user = self.user

        serializer = BookingCreateSerializer(
            data={
                'category': self.category.id,
                'preferred_date': '2026-10-01',
                'preferred_time': '10:00',
                'services_json': services,
                'discount_amount': discount,
            },
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def test_a_measured_line_is_charged_in_full(self):
        """The regression this guards: int(qty) would have charged ₹15."""
        booking = self._book([{'id': 1, 'price': '15', 'qty': 1000}])
        self.assertEqual(booking.amount, Decimal('15000'))

    def test_a_fractional_quantity_is_not_rounded_away(self):
        booking = self._book([{'id': 1, 'price': '50', 'qty': 2.5}])
        self.assertEqual(booking.amount, Decimal('125'))

    def test_lines_add_up(self):
        booking = self._book([
            {'id': 1, 'price': '15', 'qty': 1000},
            {'id': 2, 'price': '800', 'qty': 1},
        ])
        self.assertEqual(booking.amount, Decimal('15800'))

    def test_the_discount_comes_off_the_subtotal(self):
        booking = self._book(
            [{'id': 1, 'price': '15', 'qty': 1000}], discount='500')
        self.assertEqual(booking.amount, Decimal('14500'))

    def test_a_discount_larger_than_the_bill_does_not_go_negative(self):
        booking = self._book(
            [{'id': 1, 'price': '100', 'qty': 1}], discount='500')
        self.assertEqual(booking.amount, Decimal('0'))


class ServicePricingApiTests(TestCase):
    """What the apps read to render a price."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Tiling')

    def test_the_serializer_sends_everything_a_card_needs(self):
        from .serializers import ServiceSerializer

        service = Service.objects.create(
            category=self.category, name='Floor tiling', price=15,
            pricing_type=PricingType.PER_SQ_FT,
        )
        data = ServiceSerializer(service).data

        self.assertEqual(data['pricing_type'], 'PER_SQ_FT')
        self.assertEqual(data['price_label'], '₹15 / sq ft')
        self.assertEqual(data['unit_label'], 'sq ft')
        self.assertEqual(data['measure_label'], 'Area (sq ft)')
        self.assertTrue(data['needs_quantity'])
        self.assertTrue(data['allows_decimal_quantity'])
        self.assertFalse(data['is_quote_only'])

    def test_a_service_defaults_to_a_flat_price(self):
        """Every service that predates pricing types keeps behaving as one."""
        service = Service.objects.create(
            category=self.category, name='AC service', price=800,
        )
        self.assertEqual(service.pricing_type, PricingType.FIXED)
        self.assertEqual(service.price_label, '₹800')
        self.assertFalse(service.needs_quantity)
        self.assertFalse(service.is_quote_only)

    def test_a_quote_service_says_so(self):
        service = Service.objects.create(
            category=self.category, name='Painting', price=0,
            pricing_type=PricingType.CUSTOM_QUOTE,
        )
        self.assertTrue(service.is_quote_only)
        self.assertFalse(service.needs_quantity)
        self.assertEqual(service.price_label, 'Price on request')


class ServiceFormTests(TestCase):
    """The dashboard's Add/Edit Service form."""

    def setUp(self):
        admin = User.objects.create_user(
            username='priceadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(name='Tiling')

    def test_adding_a_service_records_its_pricing_type(self):
        res = self.client.post(
            reverse('service_add_cat', args=[self.category.id]),
            {
                'name': 'Floor tiling',
                'description': '',
                'price': '15',
                'pricing_type': 'PER_SQ_FT',
                'duration_minutes': '60',
                'is_active': 'on',
            },
        )
        self.assertEqual(res.status_code, 302)

        service = Service.objects.get(name='Floor tiling')
        self.assertEqual(service.pricing_type, 'PER_SQ_FT')
        self.assertEqual(service.price_label, '₹15 / sq ft')

    def test_editing_a_service_can_change_its_pricing_type(self):
        service = Service.objects.create(
            category=self.category, name='Floor tiling', price=15,
            pricing_type=PricingType.FIXED,
        )

        self.client.post(
            reverse('service_edit', args=[service.id]),
            {
                'name': service.name,
                'description': '',
                'price': '15',
                'pricing_type': 'PER_SQ_FT',
                'duration_minutes': '60',
                'is_active': 'on',
            },
        )

        service.refresh_from_db()
        self.assertEqual(service.pricing_type, 'PER_SQ_FT')

    def test_a_form_posted_without_a_pricing_type_stays_flat(self):
        res = self.client.post(
            reverse('service_add_cat', args=[self.category.id]),
            {
                'name': 'AC service',
                'description': '',
                'price': '800',
                'duration_minutes': '60',
                'is_active': 'on',
            },
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(
            Service.objects.get(name='AC service').pricing_type, 'FIXED')


class DurationVisibilityTests(TestCase):
    """
    "How long it takes" is only a fact about the flat types.

    On a per-hour service the customer chooses the hours, and on a per-sq-ft
    one it depends on the area — so the field is not asked for and the chip is
    not shown, rather than reporting a 60 nobody set.
    """

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Home')

    def _service(self, pricing_type):
        return Service.objects.create(
            category=self.category, name=f'Svc {pricing_type}', price=100,
            pricing_type=pricing_type, duration_minutes=90,
        )

    def test_the_flat_types_keep_their_duration(self):
        for pricing_type in (PricingType.FIXED, PricingType.STARTING_FROM):
            with self.subTest(pricing_type=pricing_type):
                self.assertTrue(self._service(pricing_type).shows_duration)

    def test_the_measured_types_do_not(self):
        for pricing_type in (
            PricingType.PER_HOUR, PricingType.PER_DAY, PricingType.PER_SQ_FT,
            PricingType.PER_KG, PricingType.PER_ROOM,
        ):
            with self.subTest(pricing_type=pricing_type):
                self.assertFalse(self._service(pricing_type).shows_duration)

    def test_a_quote_has_no_duration_either(self):
        """Nothing has been scoped yet, so there is nothing to state."""
        self.assertFalse(self._service(PricingType.CUSTOM_QUOTE).shows_duration)

    def test_the_api_sends_a_duration_only_where_it_applies(self):
        from .serializers import ServiceSerializer

        flat = ServiceSerializer(self._service(PricingType.FIXED)).data
        hourly = ServiceSerializer(self._service(PricingType.PER_HOUR)).data

        self.assertEqual(flat['duration_minutes'], 90)
        # Null is what makes the app skip the chip, with no change to the app.
        self.assertIsNone(hourly['duration_minutes'])

    def test_the_stored_value_is_kept_when_the_type_changes(self):
        """Switching to per-hour and back must not lose the number."""
        service = self._service(PricingType.FIXED)

        service.pricing_type = PricingType.PER_HOUR
        service.save()
        service.refresh_from_db()
        self.assertEqual(service.duration_minutes, 90)
        self.assertFalse(service.shows_duration)

        service.pricing_type = PricingType.FIXED
        service.save()
        service.refresh_from_db()
        self.assertEqual(service.duration_minutes, 90)
        self.assertTrue(service.shows_duration)


class QuotePrefillTests(TestCase):
    """
    What a quote-only service hands the tender form.

    The type of work comes from the service's own category, so only the
    project type has to be stored — it is the one thing a service could not
    otherwise say about the job.
    """

    def setUp(self):
        admin = User.objects.create_user(
            username='quoteadmin', password='pw12345', role=User.Role.ADMIN,
        )
        sign_in(self.client, admin)
        self.category = ServiceCategory.objects.create(name='Painting')

    def _post(self, **overrides):
        payload = {
            'name': 'House Painting',
            'description': '',
            'price': '0',
            'pricing_type': 'CUSTOM_QUOTE',
            'tender_project_type': 'INTERIOR',
            'duration_minutes': '60',
            'is_active': 'on',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('service_add_cat', args=[self.category.id]), payload)

    def test_a_quote_service_records_its_project_type(self):
        self.assertEqual(self._post().status_code, 302)

        service = Service.objects.get(name='House Painting')
        self.assertEqual(service.tender_project_type, 'INTERIOR')

    def test_a_priced_service_never_keeps_one(self):
        """It only means something on a quote, so it must not linger."""
        self.assertEqual(
            self._post(pricing_type='FIXED', price='800').status_code, 302)

        service = Service.objects.get(name='House Painting')
        self.assertEqual(service.tender_project_type, '')

    def test_changing_a_quote_to_a_priced_type_clears_it(self):
        self._post()
        service = Service.objects.get(name='House Painting')
        self.assertEqual(service.tender_project_type, 'INTERIOR')

        self.client.post(
            reverse('service_edit', args=[service.id]),
            {
                'name': service.name,
                'description': '',
                'price': '800',
                'pricing_type': 'FIXED',
                'tender_project_type': 'INTERIOR',
                'duration_minutes': '60',
                'is_active': 'on',
            },
        )

        service.refresh_from_db()
        self.assertEqual(service.tender_project_type, '')

    def test_leaving_it_empty_lets_the_customer_pick(self):
        self.assertEqual(self._post(tender_project_type='').status_code, 302)

        service = Service.objects.get(name='House Painting')
        self.assertEqual(service.tender_project_type, '')

    def test_the_api_sends_it_to_the_app(self):
        from .serializers import ServiceSerializer

        service = Service.objects.create(
            category=self.category, name='House Painting', price=0,
            pricing_type=PricingType.CUSTOM_QUOTE,
            tender_project_type='INTERIOR',
        )
        data = ServiceSerializer(service).data

        self.assertTrue(data['is_quote_only'])
        self.assertEqual(data['tender_project_type'], 'INTERIOR')

    def test_the_stored_value_is_one_the_tender_form_offers(self):
        """The two lists must not drift; both come from ProjectType."""
        from tenders.project_types import ProjectType

        offered = {value for value, _label in ProjectType.choices}
        self.assertIn('INTERIOR', offered)
        self.assertEqual(
            offered,
            {
                'HOUSE', 'APARTMENT', 'VILLA', 'COMMERCIAL',
                'RENOVATION', 'INTERIOR', 'OTHER',
            },
        )


class ServiceCardStatsTests(TestCase):
    """
    A service row has to say enough to judge it by: what it costs, how it is
    rated, and what it is. The rating figures used to reach only the flat card
    payload, so a category's own service list showed none.
    """

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.service = Service.objects.create(
            category=self.category, name='Tap repair', price=500,
            description='Fixes a dripping or stuck tap.',
        )

    def _review(self, rating, service=None):
        from reviews.models import Review

        user = User.objects.create_user(
            username=f'r{rating}{Review.objects.count()}',
            password='pw12345', role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(user=user)
        return Review.objects.create(
            customer=customer, rating=rating,
            service=service, service_category=self.category,
        )

    def test_the_nested_payload_carries_the_rating(self):
        """What a category's service list is built from."""
        from .serializers import ServiceSerializer

        self._review(4, service=self.service)
        self._review(5, service=self.service)

        data = ServiceSerializer(self.service).data
        self.assertEqual(data['average_rating'], 4.5)
        self.assertEqual(data['total_reviews'], 2)
        self.assertEqual(data['description'], 'Fixes a dripping or stuck tap.')

    def test_an_unreviewed_service_borrows_its_category(self):
        """Otherwise a new service reads as worse than unknown."""
        from .serializers import ServiceSerializer

        self._review(5)

        data = ServiceSerializer(self.service).data
        self.assertEqual(data['average_rating'], 5)
        self.assertEqual(data['total_reviews'], 1)

    def test_no_reviews_anywhere_reads_as_zero(self):
        from .serializers import ServiceSerializer

        data = ServiceSerializer(self.service).data
        self.assertEqual(data['average_rating'], 0)
        self.assertEqual(data['total_reviews'], 0)

    def test_the_flat_card_still_agrees(self):
        """Both payloads describe the same service the same way."""
        from .serializers import ServiceCardSerializer, ServiceSerializer

        self._review(3, service=self.service)

        nested = ServiceSerializer(self.service).data
        flat = ServiceCardSerializer(self.service).data
        self.assertEqual(nested['average_rating'], flat['average_rating'])
        self.assertEqual(nested['total_reviews'], flat['total_reviews'])
