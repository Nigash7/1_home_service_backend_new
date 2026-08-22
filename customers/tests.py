from datetime import date, time

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from bookings.models import Booking
from home_sections.models import HomeSection, HomeSectionItem
from home_sections.serializers import HomeSectionItemSerializer
from services.models import Service, ServiceCategory

from .models import Customer, ServiceView

# The exact keys the Flutter service card reads.
CARD_FIELDS = {
    'service_id', 'name', 'description', 'price', 'duration_minutes',
    'image', 'category_id', 'category_name', 'subcategory_id', 'subcategory_name',
    'average_rating', 'total_reviews', 'discount_info',
}


class PersonalisedRowsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='9000000001', phone_number='9000000001',
            first_name='Asha', role=User.Role.CUSTOMER,
        )
        self.customer = Customer.objects.create(user=self.user)
        self.category = ServiceCategory.objects.create(name='Cleaning')
        self.deep = self._service('Deep clean', 500)
        self.sofa = self._service('Sofa clean', 300)
        self.tank = self._service('Tank clean', 900)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _service(self, name, price):
        return Service.objects.create(
            category=self.category, name=name, price=price,
        )

    def _booking(self, services, status=Booking.Status.COMPLETED):
        return Booking.objects.create(
            customer=self.customer,
            category=self.category,
            preferred_date=date(2026, 1, 1),
            preferred_time=time(10, 0),
            amount=100,
            status=status,
            services_json=services,
        )

    # ---------- Recently viewed ----------

    def test_recording_a_view_then_listing_it(self):
        res = self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})
        self.assertEqual(res.status_code, 204)

        res = self.client.get('/api/customers/recently-viewed/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['service_id'], self.deep.id)
        self.assertEqual(set(res.data[0].keys()), CARD_FIELDS)

    def test_viewing_the_same_service_twice_does_not_duplicate_it(self):
        for _ in range(3):
            self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})

        self.assertEqual(ServiceView.objects.filter(customer=self.customer).count(), 1)
        res = self.client.get('/api/customers/recently-viewed/')
        self.assertEqual(len(res.data), 1)

    def test_most_recent_view_comes_first(self):
        self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})
        self.client.post('/api/customers/recently-viewed/', {'service_id': self.sofa.id})
        # Revisiting the older one should push it back to the top.
        self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})

        res = self.client.get('/api/customers/recently-viewed/')
        self.assertEqual(
            [c['service_id'] for c in res.data], [self.deep.id, self.sofa.id]
        )

    def test_inactive_services_are_left_out(self):
        self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})
        self.deep.is_active = False
        self.deep.save()

        res = self.client.get('/api/customers/recently-viewed/')
        self.assertEqual(res.data, [])

    def test_unknown_service_is_rejected(self):
        res = self.client.post('/api/customers/recently-viewed/', {'service_id': 999999})
        self.assertEqual(res.status_code, 404)

    def test_missing_service_id_is_rejected(self):
        res = self.client.post('/api/customers/recently-viewed/', {})
        self.assertEqual(res.status_code, 400)

    def test_another_customer_sees_their_own_history(self):
        self.client.post('/api/customers/recently-viewed/', {'service_id': self.deep.id})

        other_user = User.objects.create_user(
            username='9000000002', phone_number='9000000002', role=User.Role.CUSTOMER,
        )
        Customer.objects.create(user=other_user)
        other = APIClient()
        other.force_authenticate(user=other_user)

        self.assertEqual(other.get('/api/customers/recently-viewed/').data, [])

    # ---------- Book again ----------

    def test_book_again_ranks_by_times_booked(self):
        self._booking([{'id': self.deep.id, 'qty': 1}])
        self._booking([{'id': self.deep.id, 'qty': 1}, {'id': self.sofa.id, 'qty': 1}])
        self._booking([{'id': self.deep.id, 'qty': 1}])

        res = self.client.get('/api/customers/book-again/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            [c['service_id'] for c in res.data], [self.deep.id, self.sofa.id]
        )
        self.assertEqual(res.data[0]['times_booked'], 3)
        self.assertEqual(res.data[1]['times_booked'], 1)

    def test_quantities_count_towards_the_total(self):
        self._booking([{'id': self.sofa.id, 'qty': 4}])
        res = self.client.get('/api/customers/book-again/')
        self.assertEqual(res.data[0]['times_booked'], 4)

    def test_cancelled_bookings_are_ignored(self):
        self._booking([{'id': self.deep.id, 'qty': 1}], status=Booking.Status.CANCELLED)
        self.assertEqual(self.client.get('/api/customers/book-again/').data, [])

    def test_deleted_and_inactive_services_are_skipped(self):
        self._booking([{'id': self.tank.id, 'qty': 1}, {'id': 999999, 'qty': 1}])
        self.tank.is_active = False
        self.tank.save()

        self.assertEqual(self.client.get('/api/customers/book-again/').data, [])

    def test_malformed_services_json_does_not_break_the_row(self):
        self._booking(['nonsense', {'no_id': 1}, {'id': None}, {'id': self.deep.id}])
        res = self.client.get('/api/customers/book-again/')
        self.assertEqual([c['service_id'] for c in res.data], [self.deep.id])

    def test_no_bookings_returns_empty(self):
        self.assertEqual(self.client.get('/api/customers/book-again/').data, [])

    # ---------- The shared card shape ----------

    def test_home_section_items_still_use_the_same_card_shape(self):
        section = HomeSection.objects.create(title='Most booked')
        HomeSectionItem.objects.create(section=section, service=self.deep)

        data = HomeSectionItemSerializer(section.items.all(), many=True).data
        self.assertEqual(set(data[0].keys()), CARD_FIELDS)
        self.assertEqual(data[0]['service_id'], self.deep.id)
        self.assertEqual(data[0]['category_name'], 'Cleaning')
