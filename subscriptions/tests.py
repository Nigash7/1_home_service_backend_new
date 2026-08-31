"""
Tests for vendor subscription plans and the terms vendors are put on.

The rules worth protecting: a vendor holds one live plan at a time, a term
that has run out stops counting as active, a plan somebody has been on cannot
be deleted out from under the record, and holding no plan is a normal state
that blocks nothing.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from services.models import ServiceCategory
from vendors.models import Vendor

from .models import SubscriptionPlan, SubscriptionUpgradeRequest, VendorSubscription
from . import services as subscription_services
from dashboard.testing import sign_in


def make_vendor(username):
    user = User.objects.create_user(
        username=username, password='pw12345', role=User.Role.VENDOR,
        first_name=username.title(),
    )
    return Vendor.objects.create(user=user, service_area='Zone 1')


class SubscriptionPlanModelTests(TestCase):

    def test_zero_price_reads_as_free(self):
        plan = SubscriptionPlan.objects.create(name='Free', price=0)
        self.assertTrue(plan.is_free)
        self.assertFalse(
            SubscriptionPlan.objects.create(name='Gold', price=Decimal('499')).is_free
        )

    def test_term_end_date_is_inclusive_of_the_last_day(self):
        plan = SubscriptionPlan.objects.create(
            name='Monthly', price=100,
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )
        start = timezone.localdate()
        # 30 days including the start day: the vendor gets all 30.
        self.assertEqual(plan.term_end_date(start), start + timedelta(days=29))

    def test_lifetime_plan_has_no_end_date(self):
        plan = SubscriptionPlan.objects.create(
            name='Lifetime', price=5000,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )
        self.assertIsNone(plan.duration_days)
        self.assertIsNone(plan.term_end_date(timezone.localdate()))

    def test_only_one_plan_holds_the_default_seat(self):
        first = SubscriptionPlan.objects.create(name='Free', price=0, is_default=True)
        second = SubscriptionPlan.objects.create(name='Gold', price=499, is_default=True)

        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_features_split_into_bullets(self):
        plan = SubscriptionPlan.objects.create(
            name='Gold', price=499,
            features='Unlimited bids\n\n  Priority assignment  \n',
        )
        self.assertEqual(
            plan.feature_list, ['Unlimited bids', 'Priority assignment']
        )


class VendorSubscriptionModelTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor('vend1')
        self.plan = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )

    def test_a_term_that_ran_out_is_not_active(self):
        today = timezone.localdate()
        lapsed = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=10),
        )
        # Still marked ACTIVE in the database, but the window has closed.
        self.assertEqual(lapsed.status, VendorSubscription.Status.ACTIVE)
        self.assertFalse(lapsed.is_active)
        self.assertNotIn(lapsed, VendorSubscription.objects.active())
        self.assertIsNone(VendorSubscription.objects.active_for(self.vendor))

    def test_a_term_that_has_not_started_is_not_active(self):
        future = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=timezone.localdate() + timedelta(days=3),
        )
        self.assertFalse(future.is_active)

    def test_expire_due_sweeps_lapsed_terms(self):
        today = timezone.localdate()
        lapsed = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=10),
        )
        live = VendorSubscription.objects.create(
            vendor=make_vendor('vend2'), plan=self.plan,
            start_date=today, end_date=today + timedelta(days=10),
        )

        self.assertEqual(VendorSubscription.objects.expire_due(), 1)

        lapsed.refresh_from_db()
        live.refresh_from_db()
        self.assertEqual(lapsed.status, VendorSubscription.Status.EXPIRED)
        self.assertEqual(live.status, VendorSubscription.Status.ACTIVE)

    def test_days_remaining_counts_today(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate(),
        )
        self.assertEqual(subscription.days_remaining, 1)

    def test_lifetime_term_never_expires(self):
        subscription = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan, end_date=None,
        )
        self.assertTrue(subscription.is_lifetime)
        self.assertIsNone(subscription.days_remaining)
        self.assertFalse(subscription.is_expiring_soon)
        self.assertTrue(subscription.is_active)

    def test_expiring_soon_only_inside_the_warning_window(self):
        today = timezone.localdate()
        soon = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=today, end_date=today + timedelta(days=2),
        )
        later = VendorSubscription.objects.create(
            vendor=make_vendor('vend3'), plan=self.plan,
            start_date=today, end_date=today + timedelta(days=60),
        )
        self.assertTrue(soon.is_expiring_soon)
        self.assertFalse(later.is_expiring_soon)


class AssignPlanTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor('vend1')
        self.monthly = SubscriptionPlan.objects.create(
            name='Silver', price=Decimal('199'),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )
        self.lifetime = SubscriptionPlan.objects.create(
            name='Lifetime', price=Decimal('4999'),
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )

    def test_end_date_comes_from_the_plan_when_none_is_given(self):
        subscription = subscription_services.assign_plan(self.vendor, self.monthly)
        self.assertEqual(
            subscription.end_date, timezone.localdate() + timedelta(days=29)
        )

    def test_a_lifetime_plan_gets_no_end_date(self):
        subscription = subscription_services.assign_plan(self.vendor, self.lifetime)
        self.assertIsNone(subscription.end_date)

    def test_assigning_a_new_plan_ends_the_old_one(self):
        first = subscription_services.assign_plan(self.vendor, self.monthly)
        second = subscription_services.assign_plan(self.vendor, self.lifetime)

        first.refresh_from_db()
        self.assertEqual(first.status, VendorSubscription.Status.CANCELLED)
        self.assertIn('Lifetime', first.cancel_reason)

        # One live plan, and it is the new one.
        self.assertEqual(
            VendorSubscription.objects.active().filter(vendor=self.vendor).count(), 1
        )
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).id, second.id
        )

    def test_history_survives_a_plan_change(self):
        subscription_services.assign_plan(self.vendor, self.monthly)
        subscription_services.assign_plan(self.vendor, self.lifetime)
        self.assertEqual(
            VendorSubscription.objects.filter(vendor=self.vendor).count(), 2
        )

    def test_amount_paid_defaults_to_the_plan_price(self):
        subscription = subscription_services.assign_plan(self.vendor, self.monthly)
        self.assertEqual(subscription.amount_paid, Decimal('199'))

    def test_amount_paid_can_be_overridden_including_to_nothing(self):
        subscription = subscription_services.assign_plan(
            self.vendor, self.monthly, amount_paid=Decimal('0')
        )
        self.assertEqual(subscription.amount_paid, Decimal('0'))

    def test_an_end_date_before_the_start_is_refused(self):
        today = timezone.localdate()
        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.assign_plan(
                self.vendor, self.monthly,
                start_date=today, end_date=today - timedelta(days=1),
            )

    def test_renewing_early_keeps_the_days_already_paid_for(self):
        first = subscription_services.assign_plan(self.vendor, self.monthly)
        renewed = subscription_services.renew(first)

        # Picks up the day after the current term ends, not today.
        self.assertEqual(renewed.start_date, first.end_date + timedelta(days=1))

        # And the running term is left alone -- renewing early must not drop
        # the vendor off the plan they are still paying for.
        first.refresh_from_db()
        self.assertEqual(first.status, VendorSubscription.Status.ACTIVE)
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).id, first.id
        )
        self.assertEqual(
            VendorSubscription.objects.queued_for(self.vendor).id, renewed.id
        )

    def test_a_queued_term_takes_over_when_the_running_one_lapses(self):
        today = timezone.localdate()
        running = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.monthly,
            start_date=today - timedelta(days=29), end_date=today - timedelta(days=1),
        )
        queued = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.monthly,
            start_date=today, end_date=today + timedelta(days=29),
        )

        VendorSubscription.objects.expire_due()

        running.refresh_from_db()
        self.assertEqual(running.status, VendorSubscription.Status.EXPIRED)
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).id, queued.id
        )

    def test_renewing_twice_over_is_refused(self):
        first = subscription_services.assign_plan(self.vendor, self.monthly)
        subscription_services.renew(first)

        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.renew(first)

    def test_a_lifetime_plan_has_nothing_to_renew(self):
        subscription = subscription_services.assign_plan(self.vendor, self.lifetime)
        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.renew(subscription)

    def test_renewing_an_old_term_while_on_another_plan_is_refused(self):
        old = subscription_services.assign_plan(self.vendor, self.monthly)
        subscription_services.assign_plan(self.vendor, self.lifetime)

        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.renew(old)

    def test_changing_plan_clears_a_queued_renewal(self):
        first = subscription_services.assign_plan(self.vendor, self.monthly)
        queued = subscription_services.renew(first)

        subscription_services.assign_plan(self.vendor, self.lifetime)

        queued.refresh_from_db()
        self.assertEqual(queued.status, VendorSubscription.Status.CANCELLED)
        self.assertIsNone(VendorSubscription.objects.queued_for(self.vendor))

    def test_renewing_a_lapsed_term_restarts_from_today(self):
        today = timezone.localdate()
        lapsed = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.monthly,
            status=VendorSubscription.Status.EXPIRED,
            start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=30),
        )
        renewed = subscription_services.renew(lapsed)
        self.assertEqual(renewed.start_date, today)

    def test_ensure_default_subscription_is_a_no_op_without_a_default_plan(self):
        self.assertIsNone(
            subscription_services.ensure_default_subscription(self.vendor)
        )

    def test_ensure_default_subscription_does_not_double_up(self):
        self.monthly.is_default = True
        self.monthly.save()

        first = subscription_services.ensure_default_subscription(self.vendor)
        self.assertIsNotNone(first)
        self.assertIsNone(
            subscription_services.ensure_default_subscription(self.vendor)
        )


class VendorSubscriptionApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.vendor = make_vendor('vend1')
        self.plan = SubscriptionPlan.objects.create(name='Gold', price=Decimal('499'))
        SubscriptionPlan.objects.create(name='Retired', price=0, is_active=False)

    def test_plans_are_public_and_hide_deactivated_tiers(self):
        res = self.client.get(reverse('subscription-plan-list'))
        self.assertEqual(res.status_code, 200)
        names = [p['name'] for p in res.json()]
        self.assertEqual(names, ['Gold'])

    def test_a_vendor_with_no_plan_gets_a_null_current(self):
        self.client.force_authenticate(self.vendor.user)
        res = self.client.get(reverse('vendor-my-subscription'))

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()['current'])
        self.assertEqual(res.json()['history'], [])

    def test_current_and_history_are_kept_apart(self):
        subscription_services.assign_plan(self.vendor, self.plan)
        subscription_services.assign_plan(self.vendor, self.plan)

        self.client.force_authenticate(self.vendor.user)
        body = self.client.get(reverse('vendor-my-subscription')).json()

        self.assertEqual(body['current']['plan']['name'], 'Gold')
        self.assertTrue(body['current']['is_active'])
        self.assertEqual(len(body['history']), 1)
        self.assertEqual(body['history'][0]['status'], 'CANCELLED')

    def test_a_customer_cannot_read_the_vendor_endpoint(self):
        customer = User.objects.create_user(
            username='cust1', password='pw12345', role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(customer)
        res = self.client.get(reverse('vendor-my-subscription'))
        self.assertEqual(res.status_code, 403)


class DashboardSubscriptionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', password='pw12345', is_staff=True,
        )
        self.vendor = make_vendor('vend1')
        self.plan = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )

    def login(self):
        sign_in(self.client, self.admin)

    # -------------------------------------------------------------- access

    def test_logged_out_visitors_are_sent_to_the_login_page(self):
        for name, args in [
            ('subscription_plans_list', []),
            ('subscribers_list', []),
            ('vendor_subscription', [self.vendor.id]),
        ]:
            res = self.client.get(reverse(name, args=args))
            self.assertEqual(res.status_code, 302, name)
            self.assertIn(reverse('dashboard_login'), res.url)

    def test_logged_out_visitors_cannot_assign_a_plan(self):
        res = self.client.post(reverse('subscription_assign'), {
            'vendor': self.vendor.id, 'plan': self.plan.id,
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(VendorSubscription.objects.exists())

    # -------------------------------------------------------------- pages

    def test_the_plans_page_shows_each_plan_and_its_subscriber_count(self):
        self.login()
        subscription_services.assign_plan(self.vendor, self.plan)

        res = self.client.get(reverse('subscription_plans_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Gold')
        self.assertContains(res, '499')
        self.assertContains(res, '1 subscribed')
        # The whole point of "free for now" -- say so on the page.
        self.assertContains(res, 'Nothing is charged yet')

    def test_the_plan_form_opens_prefilled_for_an_edit(self):
        self.login()
        res = self.client.get(reverse('subscription_plan_edit', args=[self.plan.id]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'value="Gold"')

    def test_the_subscribers_page_offers_the_assign_form(self):
        self.login()
        res = self.client.get(reverse('subscribers_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, reverse('subscription_assign'))
        self.assertContains(res, self.vendor.display_name)

    def test_filters_survive_paging(self):
        self.login()
        for i in range(25):
            subscription_services.assign_plan(make_vendor(f'bulk{i}'), self.plan)

        res = self.client.get(reverse('subscribers_list'), {'status': 'ACTIVE'})
        self.assertContains(res, 'status=ACTIVE&amp;page=2')

    # --------------------------------------------------------------- plans

    def test_creating_a_plan(self):
        self.login()
        res = self.client.post(reverse('subscription_plan_add'), {
            'name': 'Silver',
            'description': 'Mid tier',
            'price': '199.00',
            'billing_period': 'QUARTERLY',
            'features': 'Unlimited bids\nPriority assignment',
            'sort_order': '1',
            'is_active': 'on',
        })
        self.assertEqual(res.status_code, 302)

        plan = SubscriptionPlan.objects.get(name='Silver')
        self.assertEqual(plan.price, Decimal('199.00'))
        self.assertEqual(plan.billing_period, 'QUARTERLY')
        self.assertEqual(len(plan.feature_list), 2)
        self.assertFalse(plan.is_default)

    def test_a_free_plan_is_allowed(self):
        self.login()
        self.client.post(reverse('subscription_plan_add'), {
            'name': 'Free', 'price': '0', 'billing_period': 'MONTHLY',
            'sort_order': '0', 'is_active': 'on',
        })
        self.assertTrue(SubscriptionPlan.objects.get(name='Free').is_free)

    def test_duplicate_plan_names_are_refused(self):
        self.login()
        res = self.client.post(reverse('subscription_plan_add'), {
            'name': 'gold', 'price': '99', 'billing_period': 'MONTHLY',
            'sort_order': '0', 'is_active': 'on',
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(SubscriptionPlan.objects.filter(price=99).count(), 0)

    def test_editing_a_plan_writes_the_whole_form(self):
        self.login()
        res = self.client.post(reverse('subscription_plan_edit', args=[self.plan.id]), {
            'name': 'Gold',
            'description': 'Top tier',
            'price': '599',
            'billing_period': 'YEARLY',
            'features': 'Everything',
            'sort_order': '2',
            'is_active': 'on',
            'is_default': 'on',
        })
        self.assertEqual(res.status_code, 302)

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.price, Decimal('599'))
        self.assertEqual(self.plan.billing_period, 'YEARLY')
        self.assertTrue(self.plan.is_default)

    def test_toggling_a_plan_off(self):
        self.login()
        self.client.post(reverse('subscription_plan_toggle', args=[self.plan.id]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)

    def test_a_plan_with_subscribers_cannot_be_deleted(self):
        self.login()
        subscription_services.assign_plan(self.vendor, self.plan)

        res = self.client.post(
            reverse('subscription_plan_delete', args=[self.plan.id]), follow=True
        )
        self.assertTrue(SubscriptionPlan.objects.filter(id=self.plan.id).exists())
        self.assertContains(res, 'cannot be deleted')

    def test_an_unused_plan_can_be_deleted(self):
        self.login()
        self.client.post(reverse('subscription_plan_delete', args=[self.plan.id]))
        self.assertFalse(SubscriptionPlan.objects.filter(id=self.plan.id).exists())

    # --------------------------------------------------------- subscribers

    def test_assigning_a_plan_records_who_granted_it(self):
        self.login()
        res = self.client.post(reverse('subscription_assign'), {
            'vendor': self.vendor.id,
            'plan': self.plan.id,
            'amount_paid': '499',
            'payment_reference': 'UPI-123',
        })
        self.assertEqual(res.status_code, 302)

        subscription = VendorSubscription.objects.active_for(self.vendor)
        self.assertEqual(subscription.plan, self.plan)
        self.assertEqual(subscription.created_by, self.admin)
        self.assertEqual(subscription.payment_reference, 'UPI-123')

    def test_an_explicit_end_date_overrides_the_plan_term(self):
        self.login()
        today = timezone.localdate()
        self.client.post(reverse('subscription_assign'), {
            'vendor': self.vendor.id,
            'plan': self.plan.id,
            'start_date': today.isoformat(),
            'end_date': (today + timedelta(days=6)).isoformat(),
        })
        subscription = VendorSubscription.objects.active_for(self.vendor)
        self.assertEqual(subscription.end_date, today + timedelta(days=6))

    def test_a_deactivated_plan_cannot_be_assigned(self):
        self.login()
        self.plan.is_active = False
        self.plan.save()

        self.client.post(reverse('subscription_assign'), {
            'vendor': self.vendor.id, 'plan': self.plan.id,
        }, follow=True)
        self.assertFalse(VendorSubscription.objects.exists())

    def test_cancelling_a_subscription(self):
        self.login()
        subscription = subscription_services.assign_plan(self.vendor, self.plan)

        self.client.post(
            reverse('subscription_cancel', args=[subscription.id]),
            {'reason': 'Stopped paying'},
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, VendorSubscription.Status.CANCELLED)
        self.assertEqual(subscription.cancel_reason, 'Stopped paying')
        self.assertIsNone(VendorSubscription.objects.active_for(self.vendor))

    def test_cancelling_twice_is_refused(self):
        self.login()
        subscription = subscription_services.assign_plan(self.vendor, self.plan)
        subscription.cancel()

        res = self.client.post(
            reverse('subscription_cancel', args=[subscription.id]), follow=True
        )
        self.assertContains(res, 'already closed')

    def test_renewing_from_the_dashboard_queues_the_next_term(self):
        self.login()
        subscription = subscription_services.assign_plan(self.vendor, self.plan)

        self.client.post(reverse('subscription_renew', args=[subscription.id]))

        # The running term is still the live one; the renewal waits its turn.
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).id, subscription.id
        )
        queued = VendorSubscription.objects.queued_for(self.vendor)
        self.assertEqual(queued.start_date, subscription.end_date + timedelta(days=1))
        self.assertEqual(queued.created_by, self.admin)

    def test_a_refused_renewal_says_why(self):
        self.login()
        subscription = subscription_services.assign_plan(self.vendor, self.plan)
        subscription_services.renew(subscription)

        res = self.client.post(
            reverse('subscription_renew', args=[subscription.id]), follow=True
        )
        self.assertContains(res, 'already queued')
        self.assertEqual(
            VendorSubscription.objects.filter(vendor=self.vendor).count(), 2
        )

    def test_the_unsubscribed_tab_lists_vendors_with_no_plan(self):
        self.login()
        subscribed = make_vendor('subscribed')
        subscription_services.assign_plan(subscribed, self.plan)

        res = self.client.get(reverse('subscribers_list'), {'tab': 'unsubscribed'})
        listed = [v.id for v in res.context['page_obj']]

        self.assertIn(self.vendor.id, listed)
        self.assertNotIn(subscribed.id, listed)

    def test_the_subscribers_list_filters_by_plan(self):
        self.login()
        other_plan = SubscriptionPlan.objects.create(name='Silver', price=199)
        subscription_services.assign_plan(self.vendor, self.plan)
        subscription_services.assign_plan(make_vendor('vend2'), other_plan)

        res = self.client.get(reverse('subscribers_list'), {'plan': self.plan.id})
        plans = {s.plan_id for s in res.context['page_obj']}
        self.assertEqual(plans, {self.plan.id})

    def test_a_lapsed_term_is_swept_when_the_list_is_opened(self):
        self.login()
        today = timezone.localdate()
        lapsed = VendorSubscription.objects.create(
            vendor=self.vendor, plan=self.plan,
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=1),
        )

        self.client.get(reverse('subscribers_list'))

        lapsed.refresh_from_db()
        self.assertEqual(lapsed.status, VendorSubscription.Status.EXPIRED)

    def test_the_vendor_subscription_page_shows_the_current_plan(self):
        self.login()
        subscription_services.assign_plan(self.vendor, self.plan)

        res = self.client.get(reverse('vendor_subscription', args=[self.vendor.id]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['current'].plan, self.plan)

    def test_the_vendor_detail_page_still_loads_without_a_plan(self):
        self.login()
        res = self.client.get(reverse('vendor_detail', args=[self.vendor.id]))
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.context['subscription'])


class SignupSubscriptionTests(TestCase):
    """A new vendor lands on the free tier; anything above it is a request."""

    def setUp(self):
        self.client = APIClient()
        self.category = ServiceCategory.objects.create(name='Plumbing')
        self.free = SubscriptionPlan.objects.create(
            name='Free', price=0, is_default=True,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )
        self.gold = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )

    def signup(self, **extra):
        payload = {
            'username': 'newvend',
            'password': 'SomeStrongPw!234',
            'password_confirm': 'SomeStrongPw!234',
            'first_name': 'New',
            'last_name': 'Vendor',
            'phone_number': '9876500123',
            'categories': str(self.category.id),
            'service_area': 'Zone 4',
            'id_proof': SimpleUploadedFile('id.jpg', b'x', content_type='image/jpeg'),
        }
        payload.update(extra)
        return self.client.post(
            reverse('vendor-signup'), payload, format='multipart'
        )

    def test_a_new_vendor_lands_on_the_free_plan(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201)

        vendor = Vendor.objects.get(user__username='newvend')
        subscription = VendorSubscription.objects.active_for(vendor)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.plan, self.free)
        self.assertFalse(SubscriptionUpgradeRequest.objects.exists())

    def test_picking_a_paid_plan_asks_rather_than_grants(self):
        res = self.signup(plan=self.gold.id)
        self.assertEqual(res.status_code, 201)

        vendor = Vendor.objects.get(user__username='newvend')
        # Still on Free -- nothing charged them, so nothing granted them Gold.
        self.assertEqual(VendorSubscription.objects.active_for(vendor).plan, self.free)

        upgrade_request = SubscriptionUpgradeRequest.objects.pending_for(vendor)
        self.assertEqual(upgrade_request.plan, self.gold)
        self.assertEqual(upgrade_request.quoted_price, Decimal('499'))

    def test_picking_the_free_plan_raises_no_request(self):
        self.signup(plan=self.free.id)
        self.assertFalse(SubscriptionUpgradeRequest.objects.exists())

    def test_signup_survives_a_catalogue_with_no_default(self):
        self.free.is_default = False
        self.free.save()

        res = self.signup()
        self.assertEqual(res.status_code, 201)

        vendor = Vendor.objects.get(user__username='newvend')
        self.assertIsNone(VendorSubscription.objects.active_for(vendor))

    def test_a_deactivated_plan_cannot_be_picked_at_signup(self):
        self.gold.is_active = False
        self.gold.save()

        res = self.signup(plan=self.gold.id)
        self.assertEqual(res.status_code, 400)
        self.assertIn('plan', res.json())

    def test_the_profile_endpoint_carries_the_plan_card(self):
        self.signup()
        vendor = Vendor.objects.get(user__username='newvend')

        self.client.force_authenticate(vendor.user)
        body = self.client.get(reverse('vendor-me')).json()

        self.assertEqual(body['subscription']['plan_name'], 'Free')
        self.assertTrue(body['subscription']['is_free'])
        self.assertIsNone(body['subscription']['end_date'])


class UpgradeRequestTests(TestCase):
    def setUp(self):
        self.vendor = make_vendor('vend1')
        self.free = SubscriptionPlan.objects.create(
            name='Free', price=0, is_default=True,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )
        self.gold = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
        )
        subscription_services.assign_plan(self.vendor, self.free)

    def test_asking_does_not_change_what_the_vendor_holds(self):
        subscription_services.request_upgrade(self.vendor, self.gold)
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).plan, self.free
        )

    def test_asking_for_the_plan_you_are_on_is_refused(self):
        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.request_upgrade(self.vendor, self.free)

    def test_a_second_request_is_refused_while_one_is_open(self):
        subscription_services.request_upgrade(self.vendor, self.gold)
        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.request_upgrade(self.vendor, self.gold)

    def test_a_deactivated_plan_cannot_be_asked_for(self):
        self.gold.is_active = False
        self.gold.save()
        with self.assertRaises(subscription_services.SubscriptionError):
            subscription_services.request_upgrade(self.vendor, self.gold)

    def test_approving_starts_the_term_and_closes_the_request(self):
        upgrade_request = subscription_services.request_upgrade(self.vendor, self.gold)
        subscription = subscription_services.approve_request(upgrade_request)

        upgrade_request.refresh_from_db()
        self.assertEqual(
            upgrade_request.status, SubscriptionUpgradeRequest.Status.APPROVED
        )
        self.assertEqual(upgrade_request.granted_subscription, subscription)
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).plan, self.gold
        )
        # The free term they were on is closed, not left running alongside.
        self.assertEqual(
            VendorSubscription.objects.active().filter(vendor=self.vendor).count(), 1
        )

    def test_rejecting_leaves_the_vendor_where_they_were(self):
        upgrade_request = subscription_services.request_upgrade(self.vendor, self.gold)
        subscription_services.reject_request(upgrade_request, reason='Not yet')

        upgrade_request.refresh_from_db()
        self.assertEqual(
            upgrade_request.status, SubscriptionUpgradeRequest.Status.REJECTED
        )
        self.assertEqual(upgrade_request.review_note, 'Not yet')
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).plan, self.free
        )

    def test_a_request_can_only_be_answered_once(self):
        upgrade_request = subscription_services.request_upgrade(self.vendor, self.gold)
        subscription_services.approve_request(upgrade_request)

        for answer in (
            subscription_services.approve_request,
            subscription_services.reject_request,
            subscription_services.withdraw_request,
        ):
            with self.assertRaises(subscription_services.SubscriptionError):
                answer(upgrade_request)

    def test_withdrawing_clears_the_way_for_another_ask(self):
        first = subscription_services.request_upgrade(self.vendor, self.gold)
        subscription_services.withdraw_request(first)

        second = subscription_services.request_upgrade(self.vendor, self.gold)
        self.assertNotEqual(second.id, first.id)


class UpgradeRequestApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.vendor = make_vendor('vend1')
        self.free = SubscriptionPlan.objects.create(
            name='Free', price=0, is_default=True,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )
        self.gold = SubscriptionPlan.objects.create(name='Gold', price=Decimal('499'))
        subscription_services.assign_plan(self.vendor, self.free)
        self.client.force_authenticate(self.vendor.user)

    def test_a_vendor_can_ask_for_an_upgrade(self):
        res = self.client.post(
            reverse('subscription-upgrade-requests'),
            {'plan': self.gold.id, 'note': 'Ready to grow'},
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()['plan']['name'], 'Gold')
        self.assertEqual(res.json()['status'], 'PENDING')

    def test_a_refused_ask_explains_itself(self):
        self.client.post(
            reverse('subscription-upgrade-requests'), {'plan': self.gold.id}
        )
        res = self.client.post(
            reverse('subscription-upgrade-requests'), {'plan': self.gold.id}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('still being reviewed', res.json()['detail'])

    def test_the_subscription_screen_gets_everything_in_one_call(self):
        self.client.post(
            reverse('subscription-upgrade-requests'), {'plan': self.gold.id}
        )
        body = self.client.get(reverse('vendor-my-subscription')).json()

        self.assertEqual(body['current']['plan']['name'], 'Free')
        self.assertEqual(body['pending_request']['plan']['name'], 'Gold')
        self.assertEqual({p['name'] for p in body['plans']}, {'Free', 'Gold'})

    def test_a_vendor_can_withdraw_their_own_request(self):
        created = self.client.post(
            reverse('subscription-upgrade-requests'), {'plan': self.gold.id}
        ).json()

        res = self.client.post(
            reverse('subscription-upgrade-request-withdraw', args=[created['id']])
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'WITHDRAWN')

    def test_one_vendor_cannot_withdraw_another_vendors_request(self):
        other = make_vendor('vend2')
        theirs = subscription_services.request_upgrade(other, self.gold)

        res = self.client.post(
            reverse('subscription-upgrade-request-withdraw', args=[theirs.id])
        )
        self.assertEqual(res.status_code, 404)
        theirs.refresh_from_db()
        self.assertTrue(theirs.is_open)


class DashboardUpgradeRequestTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin1', password='pw12345', is_staff=True,
        )
        self.vendor = make_vendor('vend1')
        self.free = SubscriptionPlan.objects.create(
            name='Free', price=0, is_default=True,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
        )
        self.gold = SubscriptionPlan.objects.create(name='Gold', price=Decimal('499'))
        subscription_services.assign_plan(self.vendor, self.free)
        self.request = subscription_services.request_upgrade(self.vendor, self.gold)

    def login(self):
        sign_in(self.client, self.admin)

    def test_logged_out_visitors_cannot_approve(self):
        res = self.client.post(
            reverse('subscription_request_approve', args=[self.request.id])
        )
        self.assertEqual(res.status_code, 302)
        self.request.refresh_from_db()
        self.assertTrue(self.request.is_open)

    def test_the_queue_shows_what_the_vendor_is_moving_from(self):
        self.login()
        res = self.client.get(reverse('subscription_requests_list'))

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.vendor.display_name)
        self.assertContains(res, 'Gold')
        listed = list(res.context['page_obj'])
        self.assertEqual(listed[0].current_plan.plan, self.free)

    def test_approving_grants_the_plan_and_records_the_payment(self):
        self.login()
        res = self.client.post(
            reverse('subscription_request_approve', args=[self.request.id]),
            {'amount_paid': '499', 'payment_reference': 'UPI-9'},
        )
        self.assertEqual(res.status_code, 302)

        subscription = VendorSubscription.objects.active_for(self.vendor)
        self.assertEqual(subscription.plan, self.gold)
        self.assertEqual(subscription.amount_paid, Decimal('499'))
        self.assertEqual(subscription.payment_reference, 'UPI-9')

        self.request.refresh_from_db()
        self.assertEqual(self.request.reviewed_by, self.admin)

    def test_rejecting_from_the_queue(self):
        self.login()
        self.client.post(
            reverse('subscription_request_reject', args=[self.request.id]),
            {'reason': 'Talk to us first'},
        )
        self.request.refresh_from_db()
        self.assertEqual(
            self.request.status, SubscriptionUpgradeRequest.Status.REJECTED
        )
        self.assertEqual(
            VendorSubscription.objects.active_for(self.vendor).plan, self.free
        )

    def test_answering_from_the_vendor_page_returns_there(self):
        self.login()
        res = self.client.post(
            reverse('subscription_request_approve', args=[self.request.id]),
            {'next': 'vendor'},
        )
        self.assertRedirects(
            res, reverse('vendor_subscription', args=[self.vendor.id])
        )

    def test_a_crafted_next_is_ignored_not_followed(self):
        self.login()
        res = self.client.post(
            reverse('subscription_request_approve', args=[self.request.id]),
            {'next': 'https://example.com/'},
        )
        self.assertRedirects(res, reverse('subscription_requests_list'))

    def test_the_vendor_page_offers_the_pending_request(self):
        self.login()
        res = self.client.get(
            reverse('vendor_subscription', args=[self.vendor.id])
        )
        self.assertEqual(res.context['pending_request'], self.request)
        self.assertContains(res, 'Asked for Gold')


class BackfillCommandTests(TestCase):
    """Putting the vendors who registered before plans existed onto Free."""

    def run_backfill(self, **options):
        out = StringIO()
        call_command('backfill_free_subscriptions', stdout=out, **options)
        return out.getvalue()

    def test_it_creates_a_free_plan_and_subscribes_everyone(self):
        a, b = make_vendor('vend1'), make_vendor('vend2')

        output = self.run_backfill()

        plan = SubscriptionPlan.objects.get(name='Free')
        self.assertTrue(plan.is_free)
        self.assertTrue(plan.is_default)
        self.assertEqual(VendorSubscription.objects.active_for(a).plan, plan)
        self.assertEqual(VendorSubscription.objects.active_for(b).plan, plan)
        self.assertIn('Put 2 vendor(s)', output)

    def test_running_it_twice_changes_nothing(self):
        make_vendor('vend1')
        self.run_backfill()
        self.run_backfill()
        self.assertEqual(VendorSubscription.objects.count(), 1)

    def test_a_vendor_already_on_a_plan_is_left_alone(self):
        vendor = make_vendor('vend1')
        gold = SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'), is_default=False,
        )
        subscription_services.assign_plan(vendor, gold)

        self.run_backfill()

        self.assertEqual(VendorSubscription.objects.active_for(vendor).plan, gold)

    def test_a_vendor_whose_term_ran_out_is_picked_up(self):
        vendor = make_vendor('vend1')
        gold = SubscriptionPlan.objects.create(name='Gold', price=Decimal('499'))
        today = timezone.localdate()
        VendorSubscription.objects.create(
            vendor=vendor, plan=gold,
            start_date=today - timedelta(days=60), end_date=today - timedelta(days=1),
        )

        self.run_backfill()

        self.assertEqual(
            VendorSubscription.objects.active_for(vendor).plan.name, 'Free'
        )

    def test_dry_run_writes_nothing(self):
        make_vendor('vend1')
        output = self.run_backfill(dry_run=True)

        self.assertIn('Dry run', output)
        self.assertFalse(VendorSubscription.objects.exists())
        self.assertFalse(SubscriptionPlan.objects.exists())

    def test_it_refuses_to_put_everyone_on_a_paid_default(self):
        make_vendor('vend1')
        SubscriptionPlan.objects.create(
            name='Gold', price=Decimal('499'), is_default=True,
        )

        output = self.run_backfill()

        self.assertIn('Mark a free plan as the default', output)
        self.assertFalse(VendorSubscription.objects.exists())

    def test_an_existing_free_plan_is_adopted_rather_than_duplicated(self):
        make_vendor('vend1')
        existing = SubscriptionPlan.objects.create(name='Free', price=0)

        self.run_backfill()

        existing.refresh_from_db()
        self.assertTrue(existing.is_default)
        self.assertEqual(SubscriptionPlan.objects.filter(name='Free').count(), 1)
