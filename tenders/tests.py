"""
End-to-end tests for the tender / bidding flow, driven through the real API.

They walk the same path the diagram does -- customer posts, admin approves,
vendors bid, customer picks one, work runs, customer reviews -- and check the
guards at each step, because most of the risk here is a vendor seeing or doing
something that belongs to someone else.
"""
import base64
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from customers.models import Customer
from reviews.models import Review
from services.models import ServiceCategory, SubCategory
from vendors.models import Vendor

from .models import Tender, TenderBid, TenderMilestone

# Smallest valid PNG, so ImageField validation has something real to read.
PNG_BYTES = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM'
    b'IQAAAABJRU5ErkJggg=='
)


def png(name='shot.png'):
    return SimpleUploadedFile(name, PNG_BYTES, content_type='image/png')


class MediaSandboxMixin:
    """
    Sends uploads to a throwaway directory. Without it every run leaves real
    files behind in the project's media folder, which is shared with the
    running app.
    """

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='tender-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)


class TenderFlowTests(MediaSandboxMixin, TestCase):
    """The happy path, start to finish, plus the rules along the way."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Construction')
        self.sub_civil = SubCategory.objects.create(category=self.category, name='Civil')
        self.sub_paint = SubCategory.objects.create(category=self.category, name='Painting')
        self.other_category = ServiceCategory.objects.create(name='Cleaning')

        self.customer = self._make_customer('buyer')
        self.other_customer = self._make_customer('stranger')

        # Covers the whole category -- sees everything in it.
        self.vendor_a = self._make_vendor('alpha')
        self.vendor_a.categories.add(self.category)

        # Narrowed to Civil -- sees civil tenders and category-only ones.
        self.vendor_b = self._make_vendor('bravo')
        self.vendor_b.categories.add(self.category)
        self.vendor_b.subcategories.add(self.sub_civil)

        # Narrowed to Painting -- must not see a Civil tender.
        self.vendor_c = self._make_vendor('charlie')
        self.vendor_c.categories.add(self.category)
        self.vendor_c.subcategories.add(self.sub_paint)

        # Different line of work entirely.
        self.vendor_d = self._make_vendor('delta')
        self.vendor_d.categories.add(self.other_category)

    # ------------------------------------------------------------- helpers
    def _make_customer(self, tag):
        user = User.objects.create_user(
            username=tag, password='pw', role=User.Role.CUSTOMER,
            first_name=tag.title(), phone_number='9000000001',
        )
        return Customer.objects.create(user=user)

    def _make_vendor(self, tag, verified=True):
        user = User.objects.create_user(
            username=tag, password='pw', role=User.Role.VENDOR,
            first_name=tag.title(), phone_number='9000000002',
        )
        return Vendor.objects.create(
            user=user, service_area='Zone 1', experience_years=7,
            verification_status='VERIFIED' if verified else 'PENDING',
        )

    def client_for(self, profile):
        client = APIClient()
        client.force_authenticate(user=profile.user)
        return client

    def make_tender(self, customer=None, **overrides):
        # Defaults live in the dict so `make_tender(subcategory=None)` really
        # does mean "category-only" rather than "argument omitted".
        fields = {
            'customer': customer or self.customer,
            'title': 'Build a 3BHK',
            'category': self.category,
            'subcategory': self.sub_civil,
            'description': 'Ground floor construction',
            'expected_budget': Decimal('1500000'),
            'address_district': 'Kollam',
            'address_state': 'Kerala',
            'address_pincode': '691001',
            'contact_phone': '9000000001',
        }
        fields.update(overrides)
        return Tender.objects.create(**fields)

    def open_tender(self, **overrides):
        tender = self.make_tender(**overrides)
        tender.status = Tender.Status.OPEN
        tender.save()
        return tender

    # ------------------------------------------------- 1-3. post + publish
    def test_customer_creates_tender_as_draft(self):
        response = self.client_for(self.customer).post(reverse('tender-create'), {
            'title': 'New villa',
            'project_type': 'VILLA',
            'category': self.category.id,
            'subcategory': self.sub_civil.id,
            'description': 'Two floors',
            'expected_budget': '2000000',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        tender = Tender.objects.get(id=response.data['id'])
        self.assertEqual(tender.status, Tender.Status.DRAFT)
        self.assertEqual(tender.customer, self.customer)

    def test_budget_must_be_positive(self):
        response = self.client_for(self.customer).post(reverse('tender-create'), {
            'title': 'x', 'category': self.category.id,
            'description': 'x', 'expected_budget': '0',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('expected_budget', response.data)

    def test_subcategory_must_belong_to_category(self):
        stray = SubCategory.objects.create(category=self.other_category, name='Sofa')
        response = self.client_for(self.customer).post(reverse('tender-create'), {
            'title': 'x', 'category': self.category.id, 'subcategory': stray.id,
            'description': 'x', 'expected_budget': '1000',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('subcategory', response.data)

    def test_bidding_must_close_before_work_starts(self):
        """
        A deadline after the start date means bidding would still be open once
        work was meant to have begun. The message has to name both dates --
        the app shows it verbatim, and "one of your dates is wrong" is not
        something a customer can act on.
        """
        from datetime import date

        response = self.client_for(self.customer).post(reverse('tender-create'), {
            'title': 'Villa', 'category': self.category.id,
            'description': 'x', 'expected_budget': '100000',
            'preferred_start_date': date(2027, 1, 10).isoformat(),
            'bid_deadline': date(2027, 5, 29).isoformat(),
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('bid_deadline', response.data)
        message = str(response.data['bid_deadline'][0])
        self.assertIn('29 May 2027', message)
        self.assertIn('10 Jan 2027', message)

    def test_deadline_on_the_start_date_is_allowed(self):
        """Closing bids the same day work starts is tight, not contradictory."""
        from datetime import date

        response = self.client_for(self.customer).post(reverse('tender-create'), {
            'title': 'Villa', 'category': self.category.id,
            'description': 'x', 'expected_budget': '100000',
            'preferred_start_date': date(2027, 1, 10).isoformat(),
            'bid_deadline': date(2027, 1, 10).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_publish_queues_for_approval_not_straight_to_vendors(self):
        tender = self.make_tender()
        response = self.client_for(self.customer).post(
            reverse('tender-publish', args=[tender.id])
        )

        self.assertEqual(response.status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, Tender.Status.PENDING_APPROVAL)
        self.assertIsNotNone(tender.submitted_at)
        self.assertFalse(tender.is_bidding_open)

    def test_attachments_locked_once_submitted(self):
        tender = self.make_tender()
        url = reverse('tender-attachment-upload', args=[tender.id])
        client = self.client_for(self.customer)

        first = client.post(url, {'file': png('plan.png'), 'caption': 'Floor plan'},
                            format='multipart')
        self.assertEqual(first.status_code, 201)
        # The apps load this straight into an image widget, so a bare media
        # path here would render as a broken image.
        self.assertTrue(
            first.data['file'].startswith('http'),
            f"expected an absolute URL, got {first.data['file']!r}",
        )

        tender.status = Tender.Status.PENDING_APPROVAL
        tender.save()

        second = client.post(url, {'file': png('late.png')}, format='multipart')
        self.assertEqual(second.status_code, 400)

    def test_customer_cannot_edit_after_submitting(self):
        tender = self.make_tender()
        tender.status = Tender.Status.PENDING_APPROVAL
        tender.save()

        response = self.client_for(self.customer).patch(
            reverse('tender-detail', args=[tender.id]),
            {'title': 'Sneaky edit'}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_customer_cannot_touch_another_customers_tender(self):
        tender = self.make_tender(customer=self.other_customer)
        client = self.client_for(self.customer)

        self.assertEqual(
            client.get(reverse('tender-detail', args=[tender.id])).status_code, 403
        )
        self.assertEqual(
            client.post(reverse('tender-publish', args=[tender.id])).status_code, 404
        )

    # -------------------------------------------------- 4. vendors browse
    def test_pending_tender_is_invisible_to_vendors(self):
        tender = self.make_tender()
        tender.status = Tender.Status.PENDING_APPROVAL
        tender.save()

        response = self.client_for(self.vendor_a).get(reverse('tender-open-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)

    def test_open_tender_reaches_only_matching_vendors(self):
        tender = self.open_tender()

        for vendor, expected in [
            (self.vendor_a, True),   # whole category
            (self.vendor_b, True),   # narrowed to Civil
            (self.vendor_c, False),  # narrowed to Painting
            (self.vendor_d, False),  # another category
        ]:
            ids = [
                t['id'] for t in
                self.client_for(vendor).get(reverse('tender-open-list')).data
            ]
            self.assertEqual(
                tender.id in ids, expected,
                f'{vendor.display_name} visibility was wrong',
            )

    def test_matching_vendors_agrees_with_the_vendor_feed(self):
        """The fan-out and the browse list must never disagree."""
        tender = self.open_tender()
        notified = set(tender.matching_vendors().values_list('id', flat=True))

        for vendor in (self.vendor_a, self.vendor_b, self.vendor_c, self.vendor_d):
            sees = tender.id in [
                t['id'] for t in
                self.client_for(vendor).get(reverse('tender-open-list')).data
            ]
            self.assertEqual(
                vendor.id in notified, sees,
                f'{vendor.display_name} is notified but cannot see it, or vice versa',
            )

    def test_category_only_tender_reaches_every_vendor_in_the_category(self):
        tender = self.open_tender(subcategory=None)
        ids = [
            t['id'] for t in
            self.client_for(self.vendor_c).get(reverse('tender-open-list')).data
        ]
        self.assertIn(tender.id, ids)

    def test_unverified_vendor_is_never_notified(self):
        unverified = self._make_vendor('echo', verified=False)
        unverified.categories.add(self.category)
        tender = self.open_tender()
        self.assertNotIn(
            unverified.id, tender.matching_vendors().values_list('id', flat=True)
        )

    def test_expired_tender_stops_appearing(self):
        from datetime import timedelta
        from django.utils import timezone

        tender = self.open_tender()
        tender.bid_deadline = timezone.localdate() - timedelta(days=1)
        tender.save()

        response = self.client_for(self.vendor_a).get(reverse('tender-open-list'))
        self.assertNotIn(tender.id, [t['id'] for t in response.data])
        self.assertFalse(tender.is_bidding_open)

    # ------------------------------------------------------ vendors bid
    def test_vendor_submits_bid_with_milestones(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]),
            {
                'amount': '1400000',
                'work_plan': 'Three phases',
                'timeline_days': 180,
                'milestones': [
                    {'title': 'Foundation', 'amount': '400000'},
                    {'title': 'Structure', 'amount': '600000'},
                    {'title': 'Finishing', 'amount': '400000'},
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        bid = TenderBid.objects.get(tender=tender, vendor=self.vendor_a)
        self.assertEqual(bid.milestones.count(), 3)
        self.assertEqual(bid.milestone_total, Decimal('1400000'))
        # Order is taken from the order they arrived.
        self.assertEqual(
            list(bid.milestones.values_list('title', flat=True)),
            ['Foundation', 'Structure', 'Finishing'],
        )

    def test_vendor_cannot_bid_on_a_tender_outside_their_coverage(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_c).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '1'}, format='json'
        )
        self.assertEqual(response.status_code, 403)

    def test_vendor_cannot_bid_twice(self):
        tender = self.open_tender()
        client = self.client_for(self.vendor_a)
        url = reverse('tender-my-bid', args=[tender.id])

        self.assertEqual(client.post(url, {'amount': '100'}, format='json').status_code, 201)
        self.assertEqual(client.post(url, {'amount': '90'}, format='json').status_code, 400)
        self.assertEqual(TenderBid.objects.filter(tender=tender).count(), 1)

    def test_vendor_revises_bid_and_replaces_milestones(self):
        tender = self.open_tender()
        client = self.client_for(self.vendor_a)
        url = reverse('tender-my-bid', args=[tender.id])

        client.post(url, {
            'amount': '1400000',
            'milestones': [{'title': 'Old', 'amount': '1400000'}],
        }, format='json')

        response = client.patch(url, {
            'amount': '1350000',
            'milestones': [
                {'title': 'New A', 'amount': '700000'},
                {'title': 'New B', 'amount': '650000'},
            ],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        bid = TenderBid.objects.get(tender=tender, vendor=self.vendor_a)
        self.assertEqual(bid.amount, Decimal('1350000'))
        self.assertEqual(
            list(bid.milestones.values_list('title', flat=True)), ['New A', 'New B']
        )

    def test_revising_without_milestones_keeps_the_existing_plan(self):
        tender = self.open_tender()
        client = self.client_for(self.vendor_a)
        url = reverse('tender-my-bid', args=[tender.id])

        client.post(url, {
            'amount': '1400000',
            'milestones': [{'title': 'Keep me', 'amount': '1400000'}],
        }, format='json')
        client.patch(url, {'amount': '1390000'}, format='json')

        bid = TenderBid.objects.get(tender=tender, vendor=self.vendor_a)
        self.assertEqual(
            list(bid.milestones.values_list('title', flat=True)), ['Keep me']
        )

    def test_vendor_withdraws_bid(self):
        tender = self.open_tender()
        client = self.client_for(self.vendor_a)
        url = reverse('tender-my-bid', args=[tender.id])
        client.post(url, {'amount': '100'}, format='json')

        response = client.delete(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TenderBid.objects.get(tender=tender).status, TenderBid.Status.WITHDRAWN
        )
        # A withdrawn bid drops out of the comparison.
        bids = self.client_for(self.customer).get(
            reverse('tender-bids-list', args=[tender.id])
        ).data
        self.assertEqual(len(bids), 0)

    def test_bidding_closes_when_the_tender_is_no_longer_open(self):
        tender = self.make_tender()
        tender.status = Tender.Status.PENDING_APPROVAL
        tender.save()

        response = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '1'}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    # ----------------------------------------------- 5-6. compare + award
    def test_customer_compares_bids_cheapest_first(self):
        tender = self.open_tender()
        self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '1700000', 'timeline_days': 150}, format='json')
        self.client_for(self.vendor_b).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '1400000', 'timeline_days': 200}, format='json')

        response = self.client_for(self.customer).get(
            reverse('tender-bids-list', args=[tender.id])
        )
        self.assertEqual(response.status_code, 200)
        amounts = [Decimal(b['amount']) for b in response.data]
        self.assertEqual(amounts, sorted(amounts))
        # The comparison carries the vendor detail the screen leads with.
        self.assertIn('vendor_rating', response.data[0])
        self.assertIn('vendor_experience_years', response.data[0])
        self.assertEqual(
            Decimal(response.data[0]['difference_from_expected']), Decimal('-100000')
        )

    def test_bids_sort_by_timeline_with_blanks_last(self):
        tender = self.open_tender()
        self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '100', 'timeline_days': 90}, format='json')
        self.client_for(self.vendor_b).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '200'}, format='json')  # no timeline given

        response = self.client_for(self.customer).get(
            reverse('tender-bids-list', args=[tender.id]), {'sort': 'timeline'}
        )
        self.assertEqual(response.data[0]['timeline_days'], 90)
        self.assertIsNone(response.data[1]['timeline_days'])

    def test_vendor_phone_is_hidden_until_they_win(self):
        tender = self.open_tender()
        self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '100'}, format='json')

        before = self.client_for(self.customer).get(
            reverse('tender-bids-list', args=[tender.id])).data
        self.assertIsNone(before[0]['vendor_phone'])

        self.client_for(self.customer).post(
            reverse('tender-bid-accept', args=[before[0]['id']]))

        after = self.client_for(self.customer).get(
            reverse('tender-bids-list', args=[tender.id])).data
        self.assertEqual(after[0]['vendor_phone'], '9000000002')

    def test_customer_phone_is_withheld_from_vendors_who_have_not_won(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_a).get(
            reverse('tender-detail', args=[tender.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['customer_phone'])

    def test_accepting_a_bid_awards_the_tender_and_closes_the_rest(self):
        tender = self.open_tender()
        self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '1700000'},
            format='json')
        winner = self.client_for(self.vendor_b).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '1400000',
             'milestones': [{'title': 'Phase 1', 'amount': '1400000'}]},
            format='json').data

        response = self.client_for(self.customer).post(
            reverse('tender-bid-accept', args=[winner['id']]))
        self.assertEqual(response.status_code, 200)

        tender.refresh_from_db()
        self.assertEqual(tender.status, Tender.Status.AWARDED)
        self.assertEqual(tender.awarded_vendor, self.vendor_b)
        self.assertEqual(tender.final_amount, Decimal('1400000'))
        self.assertEqual(tender.milestones.count(), 1)
        self.assertEqual(
            TenderBid.objects.get(vendor=self.vendor_a).status,
            TenderBid.Status.REJECTED,
        )
        self.assertFalse(tender.is_bidding_open)

    def test_a_tender_cannot_be_awarded_twice(self):
        tender = self.open_tender()
        bid = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '100'},
            format='json').data

        client = self.client_for(self.customer)
        self.assertEqual(
            client.post(reverse('tender-bid-accept', args=[bid['id']])).status_code, 200)
        self.assertEqual(
            client.post(reverse('tender-bid-accept', args=[bid['id']])).status_code, 400)

    def test_only_the_owner_can_award(self):
        tender = self.open_tender()
        bid = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '100'},
            format='json').data

        response = self.client_for(self.other_customer).post(
            reverse('tender-bid-accept', args=[bid['id']]))
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------- execution
    def award(self):
        """Shortcut to a tender awarded to vendor_a with two milestones."""
        tender = self.open_tender()
        bid = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]),
            {'amount': '1400000',
             'milestones': [
                 {'title': 'Foundation', 'amount': '700000'},
                 {'title': 'Finishing', 'amount': '700000'},
             ]},
            format='json').data
        self.client_for(self.customer).post(
            reverse('tender-bid-accept', args=[bid['id']]))
        tender.refresh_from_db()
        return tender

    def test_awarded_vendor_runs_the_project_to_completion(self):
        tender = self.award()
        vendor_client = self.client_for(self.vendor_a)

        self.assertEqual(
            vendor_client.post(reverse('tender-start', args=[tender.id])).status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, Tender.Status.IN_PROGRESS)

        progress = vendor_client.post(
            reverse('tender-progress-add', args=[tender.id]),
            {'message': 'Footings poured', 'percent_complete': 30,
             'images': [png('a.png'), png('b.png')]},
            format='multipart',
        )
        self.assertEqual(progress.status_code, 201)
        self.assertEqual(len(progress.data['photos']), 2)

        self.assertEqual(
            vendor_client.post(reverse('tender-complete', args=[tender.id])).status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, Tender.Status.COMPLETED)

    def test_a_losing_vendor_cannot_drive_the_project(self):
        tender = self.award()
        intruder = self.client_for(self.vendor_b)

        self.assertEqual(
            intruder.post(reverse('tender-start', args=[tender.id])).status_code, 403)
        self.assertEqual(
            intruder.post(reverse('tender-complete', args=[tender.id])).status_code, 403)

    def test_work_cannot_start_before_the_tender_is_awarded(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_a).post(
            reverse('tender-start', args=[tender.id]))
        self.assertEqual(response.status_code, 403)

    def test_milestone_is_reached_by_the_vendor_then_paid_by_the_customer(self):
        tender = self.award()
        self.client_for(self.vendor_a).post(reverse('tender-start', args=[tender.id]))
        milestone = tender.milestones.first()

        # The customer cannot pay for work the vendor has not claimed done.
        early = self.client_for(self.customer).post(
            reverse('tender-milestone-pay', args=[milestone.id]))
        self.assertEqual(early.status_code, 400)

        reached = self.client_for(self.vendor_a).post(
            reverse('tender-milestone-reach', args=[milestone.id]))
        self.assertEqual(reached.status_code, 200)

        paid = self.client_for(self.customer).post(
            reverse('tender-milestone-pay', args=[milestone.id]))
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.data['payment_status'], Tender.PaymentStatus.PARTIAL)

        # Settle the second and the tender reads as fully paid.
        second = tender.milestones.last()
        self.client_for(self.vendor_a).post(
            reverse('tender-milestone-reach', args=[second.id]))
        final = self.client_for(self.customer).post(
            reverse('tender-milestone-pay', args=[second.id]))
        self.assertEqual(final.data['payment_status'], Tender.PaymentStatus.PAID)

    def test_a_vendor_cannot_mark_someone_elses_milestone(self):
        tender = self.award()
        self.client_for(self.vendor_a).post(reverse('tender-start', args=[tender.id]))
        milestone = tender.milestones.first()

        response = self.client_for(self.vendor_b).post(
            reverse('tender-milestone-reach', args=[milestone.id]))
        self.assertEqual(response.status_code, 403)

    def test_a_customer_cannot_pay_a_milestone_on_another_tender(self):
        tender = self.award()
        self.client_for(self.vendor_a).post(reverse('tender-start', args=[tender.id]))
        milestone = tender.milestones.first()
        self.client_for(self.vendor_a).post(
            reverse('tender-milestone-reach', args=[milestone.id]))

        response = self.client_for(self.other_customer).post(
            reverse('tender-milestone-pay', args=[milestone.id]))
        self.assertEqual(response.status_code, 404)

    # ---------------------------------------------------------- review
    def complete(self):
        tender = self.award()
        self.client_for(self.vendor_a).post(reverse('tender-start', args=[tender.id]))
        self.client_for(self.vendor_a).post(reverse('tender-complete', args=[tender.id]))
        tender.refresh_from_db()
        return tender

    def test_review_counts_towards_the_vendors_overall_rating(self):
        tender = self.complete()
        response = self.client_for(self.customer).post(
            reverse('tender-review', args=[tender.id]),
            {'rating': 5, 'comment': 'Excellent work'}, format='json',
        )

        self.assertEqual(response.status_code, 201)
        review = Review.objects.get(tender=tender)
        self.assertEqual(review.vendor, self.vendor_a)

        self.vendor_a.refresh_from_db()
        self.assertEqual(self.vendor_a.average_rating, 5.0)
        self.assertEqual(self.vendor_a.total_reviews, 1)

    def test_a_project_can_only_be_reviewed_once(self):
        tender = self.complete()
        client = self.client_for(self.customer)
        url = reverse('tender-review', args=[tender.id])

        self.assertEqual(client.post(url, {'rating': 5}, format='json').status_code, 201)
        self.assertEqual(client.post(url, {'rating': 1}, format='json').status_code, 400)

    def test_an_unfinished_project_cannot_be_reviewed(self):
        tender = self.award()
        response = self.client_for(self.customer).post(
            reverse('tender-review', args=[tender.id]), {'rating': 5}, format='json')
        self.assertEqual(response.status_code, 400)

    # --------------------------------------------------------- cancelling
    def test_customer_cancels_an_open_tender(self):
        tender = self.open_tender()
        self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '100'}, format='json')

        response = self.client_for(self.customer).post(
            reverse('tender-cancel', args=[tender.id]), {'reason': 'Postponed'},
            format='json')

        self.assertEqual(response.status_code, 200)
        tender.refresh_from_db()
        self.assertEqual(tender.status, Tender.Status.CANCELLED)
        self.assertEqual(tender.cancellation_reason, 'Postponed')

    def test_running_work_cannot_simply_be_cancelled(self):
        tender = self.award()
        self.client_for(self.vendor_a).post(reverse('tender-start', args=[tender.id]))

        response = self.client_for(self.customer).post(
            reverse('tender-cancel', args=[tender.id]), format='json')
        self.assertEqual(response.status_code, 400)

    # ----------------------------------------------------- vendor listings
    def test_vendor_sees_their_own_bids_and_won_projects(self):
        tender = self.award()
        client = self.client_for(self.vendor_a)

        my_bids = client.get(reverse('tender-my-bids'))
        self.assertEqual(len(my_bids.data), 1)
        self.assertEqual(my_bids.data[0]['status'], TenderBid.Status.ACCEPTED)

        won = client.get(reverse('tender-awarded-list'))
        self.assertEqual([t['id'] for t in won.data], [tender.id])

        # The vendor who lost has a bid but no project.
        loser = self.client_for(self.vendor_b)
        self.assertEqual(len(loser.get(reverse('tender-awarded-list')).data), 0)

    def test_a_vendor_who_bid_keeps_access_after_losing(self):
        tender = self.open_tender()
        self.client_for(self.vendor_b).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '9999'},
            format='json')
        winning = self.client_for(self.vendor_a).post(
            reverse('tender-my-bid', args=[tender.id]), {'amount': '100'},
            format='json').data
        self.client_for(self.customer).post(
            reverse('tender-bid-accept', args=[winning['id']]))

        response = self.client_for(self.vendor_b).get(
            reverse('tender-detail', args=[tender.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['my_bid']['status'], TenderBid.Status.REJECTED)

    def test_a_vendor_outside_the_category_cannot_open_the_tender(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_d).get(
            reverse('tender-detail', args=[tender.id]))
        self.assertEqual(response.status_code, 403)

    def test_vendors_cannot_edit_a_tender(self):
        tender = self.open_tender()
        response = self.client_for(self.vendor_a).patch(
            reverse('tender-detail', args=[tender.id]),
            {'title': 'Rewritten'}, format='json')
        self.assertEqual(response.status_code, 403)


class TenderDashboardTests(MediaSandboxMixin, TestCase):
    """The admin approval gate, driven through the dashboard views."""

    def setUp(self):
        self.category = ServiceCategory.objects.create(name='Construction')
        customer_user = User.objects.create_user(
            username='buyer', password='pw', role=User.Role.CUSTOMER)
        self.customer = Customer.objects.create(user=customer_user)

        vendor_user = User.objects.create_user(
            username='alpha', password='pw', role=User.Role.VENDOR)
        self.vendor = Vendor.objects.create(
            user=vendor_user, service_area='Zone 1', verification_status='VERIFIED')
        self.vendor.categories.add(self.category)

        # The dashboard authenticates through a staff User held in the session.
        self.staff = User.objects.create_user(
            username='admin1', password='pw', role=User.Role.ADMIN, is_staff=True)
        session = self.client.session
        session['admin_user_id'] = self.staff.id
        session.save()

        self.tender = Tender.objects.create(
            customer=self.customer, title='Build a 3BHK', category=self.category,
            description='x', expected_budget=Decimal('1500000'),
            status=Tender.Status.PENDING_APPROVAL,
        )

    def test_approving_publishes_the_tender_to_vendors(self):
        response = self.client.post(
            reverse('tender_approve', args=[self.tender.id]), follow=True)
        self.assertEqual(response.status_code, 200)

        self.tender.refresh_from_db()
        self.assertEqual(self.tender.status, Tender.Status.OPEN)
        self.assertIsNotNone(self.tender.published_at)
        self.assertTrue(self.tender.is_bidding_open)

    def test_rejecting_requires_a_reason_the_customer_can_act_on(self):
        blank = self.client.post(
            reverse('tender_reject', args=[self.tender.id]), {'reason': '  '}, follow=True)
        self.assertEqual(blank.status_code, 200)
        self.tender.refresh_from_db()
        self.assertEqual(self.tender.status, Tender.Status.PENDING_APPROVAL)

        self.client.post(
            reverse('tender_reject', args=[self.tender.id]),
            {'reason': 'Budget looks like a typo'}, follow=True)
        self.tender.refresh_from_db()
        self.assertEqual(self.tender.status, Tender.Status.REJECTED)
        self.assertEqual(self.tender.rejection_reason, 'Budget looks like a typo')

    def test_a_rejected_tender_can_be_fixed_and_resubmitted(self):
        self.tender.status = Tender.Status.REJECTED
        self.tender.rejection_reason = 'Budget looks like a typo'
        self.tender.save()

        api = APIClient()
        api.force_authenticate(user=self.customer.user)
        api.patch(reverse('tender-detail', args=[self.tender.id]),
                  {'expected_budget': '1600000'}, format='json')
        api.post(reverse('tender-publish', args=[self.tender.id]))

        self.tender.refresh_from_db()
        self.assertEqual(self.tender.status, Tender.Status.PENDING_APPROVAL)
        self.assertEqual(self.tender.expected_budget, Decimal('1600000'))
        self.assertEqual(self.tender.rejection_reason, '')

    def test_only_a_pending_tender_can_be_approved(self):
        self.tender.status = Tender.Status.OPEN
        self.tender.save()

        self.client.post(reverse('tender_approve', args=[self.tender.id]), follow=True)
        self.tender.refresh_from_db()
        self.assertIsNone(self.tender.published_at)

    def test_admin_can_award_on_the_customers_behalf(self):
        self.tender.status = Tender.Status.OPEN
        self.tender.save()
        bid = TenderBid.objects.create(
            tender=self.tender, vendor=self.vendor, amount=Decimal('1400000'))
        TenderMilestone.objects.create(bid=bid, title='Phase 1', amount=Decimal('1400000'))

        self.client.post(reverse('tender_award', args=[self.tender.id]),
                         {'bid_id': bid.id}, follow=True)

        self.tender.refresh_from_db()
        self.assertEqual(self.tender.status, Tender.Status.AWARDED)
        self.assertEqual(self.tender.awarded_vendor, self.vendor)

    def test_list_and_detail_pages_render(self):
        self.assertEqual(self.client.get(reverse('tenders_list')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('tender_detail', args=[self.tender.id])).status_code,
            200,
        )

    def test_detail_page_renders_with_every_section_filled(self):
        """
        A finished project exercises the branches an approval-queue tender
        never reaches: attachments, bids, milestones, progress, the map link
        and the review.
        """
        from django.utils import timezone

        from .models import TenderAttachment, TenderProgressPhoto, TenderProgressUpdate

        tender = self.tender
        tender.address_text = '12 Beach Road'
        tender.address_district = 'Kollam'
        tender.location_lat = 8.88
        tender.location_lng = 76.59
        tender.area_sqft = 1800
        tender.requirements = 'M-sand only'
        tender.save()

        TenderAttachment.objects.create(
            tender=tender, file=png('plan.png'), caption='Floor plan')
        TenderAttachment.objects.create(
            tender=tender, file=SimpleUploadedFile('spec.pdf', b'%PDF-1.4'),
            caption='Spec sheet')

        winner = TenderBid.objects.create(
            tender=tender, vendor=self.vendor, amount=Decimal('1400000'),
            work_plan='Three phases', timeline_days=180, notes='Includes labour',
        )
        TenderMilestone.objects.create(
            bid=winner, title='Foundation', amount=Decimal('700000'),
            status=TenderMilestone.Status.PAID, sort_order=0)
        TenderMilestone.objects.create(
            bid=winner, title='Finishing', amount=Decimal('700000'), sort_order=1)

        # A losing bid whose milestones do not add up, so the mismatch warning
        # renders too.
        loser_user = User.objects.create_user(
            username='bravo', password='pw', role=User.Role.VENDOR)
        loser = Vendor.objects.create(
            user=loser_user, service_area='Zone 2', verification_status='VERIFIED')
        losing_bid = TenderBid.objects.create(
            tender=tender, vendor=loser, amount=Decimal('1600000'),
            status=TenderBid.Status.REJECTED)
        TenderMilestone.objects.create(
            bid=losing_bid, title='All of it', amount=Decimal('999'))

        tender.awarded_bid = winner
        tender.status = Tender.Status.COMPLETED
        tender.awarded_at = timezone.now()
        tender.started_at = timezone.now()
        tender.completed_at = timezone.now()
        tender.payment_status = Tender.PaymentStatus.PARTIAL
        tender.save()

        update = TenderProgressUpdate.objects.create(
            tender=tender, vendor=self.vendor,
            message='Footings poured', percent_complete=40)
        TenderProgressPhoto.objects.create(update=update, image=png('site.png'))

        Review.objects.create(
            tender=tender, customer=self.customer, vendor=self.vendor,
            service_category=self.category, rating=4, comment='Solid work')

        response = self.client.get(reverse('tender_detail', args=[tender.id]))
        self.assertEqual(response.status_code, 200)

        body = response.content.decode()
        self.assertIn('Floor plan', body)
        self.assertIn('Footings poured', body)
        self.assertIn('Foundation', body)
        self.assertIn('Solid work', body)
        self.assertIn('does not match the bid', body)  # milestone mismatch warning
        self.assertIn('google.com/maps', body)

    def test_dashboard_requires_a_logged_in_admin(self):
        self.client.logout()
        anonymous = self.client_class()
        response = anonymous.get(reverse('tenders_list'))
        self.assertEqual(response.status_code, 302)
