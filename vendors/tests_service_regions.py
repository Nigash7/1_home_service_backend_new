"""
Tests for where a vendor works.

The rules being protected: coverage is most-specific-wins (nothing named is
everywhere, a state named is all of it, districts named narrow it), place
names match however they were typed, and a customer whose own place nobody
covers is told so and offered the vendors who are elsewhere.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from services.models import Service, ServiceCategory

from .models import Vendor, set_vendor_service_regions
from .regions import canonical_state, normalize_region, state_key


def make_vendor(username, regions=None, **kwargs):
    user = User.objects.create_user(
        username=username, password='pw12345', role=User.Role.VENDOR,
        first_name=username.title(),
    )
    vendor = Vendor.objects.create(
        user=user,
        service_area=kwargs.pop('service_area', 'Zone 1'),
        verification_status=kwargs.pop(
            'verification_status', Vendor.VerificationStatus.VERIFIED),
        **kwargs
    )
    if regions is not None:
        set_vendor_service_regions(vendor, regions)
    return vendor


class StateNameTests(TestCase):
    """Two people spelling one state must still mean one state."""

    def test_matches_across_case_and_spacing(self):
        self.assertEqual(state_key('  KERALA '), state_key('Kerala'))
        self.assertEqual(state_key('tamilnadu'), state_key('Tamil Nadu'))

    def test_older_names_resolve_to_the_current_one(self):
        self.assertEqual(canonical_state('Orissa'), 'Odisha')
        self.assertEqual(canonical_state('NCT of Delhi'), 'Delhi')
        self.assertEqual(canonical_state('Jammu & Kashmir'), 'Jammu and Kashmir')

    def test_an_unknown_place_is_kept_not_dropped(self):
        self.assertEqual(canonical_state('  Some  Province '), 'Some Province')

    def test_nothing_in_nothing_out(self):
        self.assertEqual(state_key(''), '')
        self.assertEqual(state_key(None), '')
        self.assertEqual(canonical_state('   '), '')

    def test_districts_match_the_same_way(self):
        """There is no list of districts to canonicalise against, only this."""
        self.assertEqual(
            normalize_region('  ERNAKULAM '), normalize_region('ernakulam'),
        )
        self.assertEqual(normalize_region(''), '')


class ServiceStateWriteTests(TestCase):
    def test_states_are_stored_canonically(self):
        vendor = make_vendor('v1', regions=['kerala', 'TAMILNADU'])
        self.assertEqual(vendor.service_region_labels, ['Kerala', 'Tamil Nadu'])

    def test_two_spellings_of_one_state_store_once(self):
        vendor = make_vendor('v1', regions=['Odisha', 'orissa', ' ODISHA '])
        self.assertEqual(vendor.service_region_labels, ['Odisha'])

    def test_saving_again_replaces_the_whole_list(self):
        vendor = make_vendor('v1', regions=['Kerala', 'Goa'])
        set_vendor_service_regions(vendor, ['Goa', 'Punjab'])
        self.assertEqual(vendor.service_region_labels, ['Goa', 'Punjab'])

    def test_an_empty_list_clears_the_rows(self):
        vendor = make_vendor('v1', regions=['Kerala'])
        set_vendor_service_regions(vendor, [])
        self.assertEqual(vendor.service_region_labels, [])

    def test_blanks_are_ignored(self):
        vendor = make_vendor('v1', regions=['Kerala', '', '   '])
        self.assertEqual(vendor.service_region_labels, ['Kerala'])

    def test_districts_are_grouped_under_their_state(self):
        vendor = make_vendor('v1', regions=[
            ('Kerala', 'Ernakulam'), ('Kerala', 'Thrissur'), ('Goa', ''),
        ])
        self.assertEqual(
            sorted(vendor.service_region_labels),
            ['Goa', 'Kerala — Ernakulam, Thrissur'],
        )

    def test_the_whole_state_swallows_districts_named_beside_it(self):
        """Asking for all of Kerala and for Ernakulam means all of Kerala."""
        vendor = make_vendor('v1', regions=[('Kerala', 'Ernakulam'), 'Kerala'])

        self.assertEqual(vendor.service_region_labels, ['Kerala'])
        self.assertTrue(vendor.serves('Kerala', 'Thrissur'))

    def test_a_district_is_stored_as_typed_and_matched_loosely(self):
        vendor = make_vendor('v1', regions=[('kerala', '  ERNAKULAM ')])

        self.assertEqual(vendor.service_region_labels, ['Kerala — ERNAKULAM'])
        self.assertTrue(vendor.serves('Kerala', 'ernakulam'))


class CoverageTests(TestCase):
    def setUp(self):
        self.narrow = make_vendor('narrow', regions=['Kerala'])
        self.everywhere = make_vendor('everywhere', regions=[])
        self.elsewhere = make_vendor('elsewhere', regions=['Goa'])

    def test_a_vendor_with_no_states_covers_every_one(self):
        self.assertTrue(self.everywhere.serves('Kerala'))
        self.assertTrue(self.everywhere.serves('Goa'))

    def test_a_named_state_is_covered_however_it_is_typed(self):
        self.assertTrue(self.narrow.serves('  kerala '))

    def test_a_state_left_off_the_list_is_not_covered(self):
        self.assertFalse(self.narrow.serves('Goa'))

    def test_serving_area_finds_the_named_and_the_unrestricted(self):
        found = set(Vendor.objects.serving_area('Kerala'))
        self.assertEqual(found, {self.narrow, self.everywhere})

    def test_outside_area_is_only_vendors_who_named_others(self):
        found = set(Vendor.objects.outside_area('Kerala'))
        self.assertEqual(found, {self.elsewhere})

    def test_a_vendor_is_never_in_both_lists(self):
        serving = set(Vendor.objects.serving_area('Kerala'))
        outside = set(Vendor.objects.outside_area('Kerala'))
        self.assertEqual(serving & outside, set())

    def test_no_state_asked_about_matches_nobody(self):
        self.assertEqual(list(Vendor.objects.serving_area('')), [])
        self.assertEqual(list(Vendor.objects.outside_area(None)), [])


class DistrictCoverageTests(TestCase):
    """Districts narrow a state the vendor already covers."""

    def setUp(self):
        self.whole = make_vendor('whole', regions=['Kerala'])
        self.partial = make_vendor(
            'partial', regions=[('Kerala', 'Ernakulam')])

    def test_a_district_named_is_covered(self):
        self.assertTrue(self.partial.serves('Kerala', 'Ernakulam'))

    def test_a_district_left_out_is_not_covered(self):
        self.assertFalse(self.partial.serves('Kerala', 'Thrissur'))

    def test_the_whole_state_covers_every_district_in_it(self):
        self.assertTrue(self.whole.serves('Kerala', 'Thrissur'))

    def test_an_unknown_district_falls_back_to_the_state(self):
        """A profile with no district must not hide a vendor."""
        self.assertTrue(self.partial.serves('Kerala', ''))

    def test_the_queryset_agrees_with_the_model(self):
        in_ernakulam = set(Vendor.objects.serving_area('Kerala', 'Ernakulam'))
        in_thrissur = set(Vendor.objects.serving_area('Kerala', 'Thrissur'))

        self.assertEqual(in_ernakulam, {self.whole, self.partial})
        self.assertEqual(in_thrissur, {self.whole})

    def test_a_vendor_narrowed_elsewhere_in_the_state_counts_as_outside(self):
        outside = set(Vendor.objects.outside_area('Kerala', 'Thrissur'))
        self.assertEqual(outside, {self.partial})

    def test_no_vendor_is_ever_in_both_lists(self):
        serving = set(Vendor.objects.serving_area('Kerala', 'Thrissur'))
        outside = set(Vendor.objects.outside_area('Kerala', 'Thrissur'))
        self.assertEqual(serving & outside, set())


class BookableTests(TestCase):
    def test_only_vendors_who_could_take_the_job(self):
        ready = make_vendor('ready')
        make_vendor('unverified',
                    verification_status=Vendor.VerificationStatus.PENDING)
        make_vendor('off_duty', is_available=False)
        make_vendor('offline', status=Vendor.AvailabilityStatus.OFFLINE)

        self.assertEqual(list(Vendor.objects.bookable()), [ready])


class AvailabilityEndpointTests(TestCase):
    """GET /api/vendors/availability/ - what the service page asks on open."""

    def setUp(self):
        self.client = APIClient()
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.service = Service.objects.create(
            category=self.category, name='Tap repair', price=500,
        )
        self.url = reverse('service-availability')

    def _ask(self, **params):
        params.setdefault('service', self.service.id)
        return self.client.get(self.url, params)

    def _vendor(self, username, regions, **kwargs):
        vendor = make_vendor(username, regions=regions, **kwargs)
        vendor.categories.set([self.category])
        return vendor

    def test_covered_state_can_go_ahead(self):
        self._vendor('local', ['Kerala'])
        body = self._ask(state='kerala').json()

        self.assertTrue(body['available'])
        self.assertEqual(body['vendor_count'], 1)
        self.assertEqual(body['state'], 'Kerala')
        self.assertEqual(body['vendors_elsewhere'], [])

    def test_uncovered_state_offers_the_vendors_who_are_elsewhere(self):
        self._vendor('goan', ['Goa'], state='Goa', district='North Goa')
        body = self._ask(state='Kerala').json()

        self.assertFalse(body['available'])
        self.assertEqual(body['vendor_count'], 0)
        card = body['vendors_elsewhere'][0]
        self.assertEqual(card['state'], 'Goa')
        self.assertEqual(card['district'], 'North Goa')
        self.assertEqual(card['location_label'], 'North Goa, Goa')
        self.assertEqual(card['service_regions'], ['Goa'])

    def test_a_vendor_who_cannot_take_the_job_is_not_offered_anywhere(self):
        self._vendor('goan', ['Goa'], verification_status='PENDING')
        body = self._ask(state='Kerala').json()

        self.assertFalse(body['available'])
        self.assertEqual(body['vendors_elsewhere'], [])

    def test_a_vendor_for_another_service_is_not_counted(self):
        other_category = ServiceCategory.objects.create(name='Painting')
        painter = make_vendor('painter', regions=['Kerala'])
        painter.categories.set([other_category])

        body = self._ask(state='Kerala').json()
        self.assertFalse(body['available'])

    def test_no_state_given_never_blocks_the_booking(self):
        """A guest, or a customer who has not filled in a profile yet."""
        self._vendor('goan', ['Goa'])
        body = self._ask().json()

        self.assertTrue(body['available'])
        self.assertFalse(body['state_known'])

    def test_an_unknown_service_is_a_404_not_an_empty_yes(self):
        self.assertEqual(self._ask(service=999999).status_code, 404)

    def test_a_district_nobody_covers_is_refused_inside_a_covered_state(self):
        self._vendor('ernakulam_only', [('Kerala', 'Ernakulam')],
                     state='Kerala', district='Ernakulam')

        body = self._ask(state='Kerala', district='Thrissur').json()

        self.assertFalse(body['available'])
        self.assertEqual(body['district'], 'Thrissur')
        card = body['vendors_elsewhere'][0]
        self.assertEqual(card['location_label'], 'Ernakulam, Kerala')
        self.assertEqual(card['service_regions'], ['Kerala — Ernakulam'])

    def test_the_same_vendor_covers_their_own_district(self):
        self._vendor('ernakulam_only', [('Kerala', 'Ernakulam')])

        body = self._ask(state='Kerala', district='ernakulam').json()

        self.assertTrue(body['available'])
        self.assertEqual(body['vendor_count'], 1)

    def test_a_district_we_were_not_told_asks_about_the_state_alone(self):
        self._vendor('ernakulam_only', [('Kerala', 'Ernakulam')])

        body = self._ask(state='Kerala').json()

        self.assertTrue(body['available'])


class ProVendorStateFilterTests(TestCase):
    """The Book-with-a-Pro row only offers pros who work where you live."""

    def setUp(self):
        self.client = APIClient()
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.service = Service.objects.create(
            category=self.category, name='Tap repair', price=500,
        )
        for name, regions in (('local', ['Kerala']), ('remote', ['Goa'])):
            vendor = make_vendor(name, regions=regions, is_pro=True)
            vendor.categories.set([self.category])

    def test_filters_to_the_customers_state(self):
        res = self.client.get(
            reverse('pro-vendor-list'),
            {'service': self.service.id, 'state': 'Kerala'},
        )
        self.assertEqual([v['name'] for v in res.json()], ['Local'])

    def test_no_state_asked_for_leaves_the_list_alone(self):
        res = self.client.get(
            reverse('pro-vendor-list'), {'service': self.service.id},
        )
        self.assertEqual(len(res.json()), 2)


class RotationStateTests(TestCase):
    """
    Auto-assign must not put a vendor on a job in a state they said they do
    not work in — the same rule the customer app applies at booking time.
    """

    def setUp(self):
        from customers.models import Customer

        self.category = ServiceCategory.objects.create(name='Plumbing')
        customer_user = User.objects.create_user(
            username='cust', password='pw12345', role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(user=customer_user)

    def _booking(self, state='', district=''):
        from datetime import date, time

        from bookings.models import Booking

        return Booking.objects.create(
            customer=self.customer, category=self.category,
            preferred_date=date(2026, 1, 1), preferred_time=time(10, 0),
            address_state=state, address_district=district,
        )

    def _vendor(self, name, regions):
        vendor = make_vendor(name, regions=regions)
        vendor.categories.set([self.category])
        return vendor

    def test_a_vendor_outside_the_state_is_not_rotated_onto_the_job(self):
        from .round_robin import pick_next_vendor

        self._vendor('goan', ['Goa'])
        picked = pick_next_vendor(self.category, self._booking('Kerala'))

        self.assertIsNone(picked)

    def test_a_vendor_who_named_no_states_is_still_eligible(self):
        from .round_robin import pick_next_vendor

        anywhere = self._vendor('anywhere', [])
        picked = pick_next_vendor(self.category, self._booking('Kerala'))

        self.assertEqual(picked, anywhere)

    def test_a_vendor_outside_the_district_is_not_rotated_onto_the_job(self):
        from .round_robin import pick_next_vendor

        self._vendor('ernakulam', [('Kerala', 'Ernakulam')])
        picked = pick_next_vendor(
            self.category, self._booking('Kerala', 'Thrissur'))

        self.assertIsNone(picked)

    def test_a_vendor_covering_the_whole_state_takes_any_district(self):
        from .round_robin import pick_next_vendor

        statewide = self._vendor('statewide', ['Kerala'])
        picked = pick_next_vendor(
            self.category, self._booking('Kerala', 'Thrissur'))

        self.assertEqual(picked, statewide)

    def test_a_booking_with_no_state_recorded_rotates_as_before(self):
        from .round_robin import pick_next_vendor

        goan = self._vendor('goan', ['Goa'])
        picked = pick_next_vendor(self.category, self._booking())

        self.assertEqual(picked, goan)


class DistrictListTests(TestCase):
    """
    The lists the profile pickers offer.

    These exist so a customer picks their place instead of typing it -- the
    whole "is there a vendor in your zone" question compares what they chose
    against what a vendor covers, and two spellings of one place answer it
    wrong. The rule the tests protect is that a gap in *our* data never
    becomes a customer who cannot save their address.
    """

    def test_every_state_offers_districts(self):
        from .regions import INDIAN_STATES, districts_for

        empty = [name for name in INDIAN_STATES if not districts_for(name)]
        self.assertEqual(empty, [])

    def test_districts_are_found_however_the_state_is_typed(self):
        from .regions import districts_for

        self.assertEqual(districts_for('kerala'), districts_for('Kerala'))
        self.assertEqual(districts_for('Orissa'), districts_for('Odisha'))

    def test_a_district_is_recognised_however_it_is_typed(self):
        from .regions import is_known_district

        self.assertTrue(is_known_district('Kerala', 'ernakulam'))
        self.assertTrue(is_known_district('kerala', '  ERNAKULAM '))

    def test_a_district_that_is_not_in_the_state_is_not_recognised(self):
        from .regions import is_known_district

        self.assertFalse(is_known_district('Kerala', 'Bengaluru Urban'))

    def test_a_state_we_hold_no_list_for_accepts_anything(self):
        """A gap in our data must never block somebody's own address."""
        from .regions import districts_for, is_known_district

        self.assertEqual(districts_for('Atlantis'), [])
        self.assertTrue(is_known_district('Atlantis', 'Anywhere'))

    def test_unknown_input_is_handled(self):
        from .regions import districts_for

        self.assertEqual(districts_for(''), [])
        self.assertEqual(districts_for(None), [])


class RegionEndpointTests(TestCase):
    """GET /api/vendors/regions/ — what the profile form fetches on open."""

    def setUp(self):
        self.client = APIClient()

    def test_returns_every_state_with_its_districts(self):
        from .regions import INDIAN_STATES

        body = self.client.get(reverse('vendor-regions')).json()

        self.assertEqual(len(body['states']), len(INDIAN_STATES))
        by_name = {entry['name']: entry['districts'] for entry in body['states']}
        self.assertIn('Ernakulam', by_name['Kerala'])
        self.assertTrue(all(by_name.values()))

    def test_it_is_open_to_a_guest(self):
        """The profile form is filled before a first booking, not after."""
        res = self.client.get(reverse('vendor-regions'))
        self.assertEqual(res.status_code, 200)
