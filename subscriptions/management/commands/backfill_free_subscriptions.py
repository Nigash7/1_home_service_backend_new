"""
Puts every vendor who is on nothing onto the free default plan.

For the vendors who registered before plans existed. New signups land on the
default on their own, so this is a one-off catch-up -- but it is safe to run
again whenever, because a vendor already holding a live plan is skipped.

    python manage.py backfill_free_subscriptions            # do it
    python manage.py backfill_free_subscriptions --dry-run  # just count
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from subscriptions import services as subscription_services
from subscriptions.models import SubscriptionPlan, VendorSubscription
from vendors.models import Vendor

FREE_PLAN_NAME = 'Free'
FREE_PLAN_DESCRIPTION = 'Everything you need to start taking work.'
FREE_PLAN_FEATURES = '\n'.join([
    'Take jobs assigned by the admin',
    'Bid on open tenders',
    'Receive payouts to your bank account',
])


class Command(BaseCommand):
    help = "Put every vendor with no live plan onto the free default plan."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            '--quiet', action='store_true',
            help="Only print the summary line.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        quiet = options['quiet']

        plan = self._get_or_create_default_plan(dry_run)
        if plan is None:
            return

        # Lapsed terms first: a vendor whose plan ran out months ago belongs
        # in this pass, and until it is swept they still look subscribed.
        if not dry_run:
            swept = VendorSubscription.objects.expire_due()
            if swept and not quiet:
                self.stdout.write(f'Closed {swept} lapsed term(s) first.')

        subscribed_ids = set(
            VendorSubscription.objects.active().values_list('vendor_id', flat=True)
        )
        pending = Vendor.objects.exclude(id__in=subscribed_ids).select_related('user')
        total = pending.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS('Every vendor is already on a plan.'))
            return

        if dry_run:
            for vendor in pending[:20]:
                self.stdout.write(f'  would subscribe: {vendor.display_name}')
            if total > 20:
                self.stdout.write(f'  ... and {total - 20} more')
            self.stdout.write(
                self.style.WARNING(
                    f'Dry run: {total} vendor(s) would be put on "{plan.name}".'
                )
            )
            return

        done = 0
        for vendor in pending:
            with transaction.atomic():
                if subscription_services.assign_plan(vendor, plan):
                    done += 1
            if not quiet:
                self.stdout.write(f'  {vendor.display_name} -> {plan.name}')

        self.stdout.write(
            self.style.SUCCESS(f'Put {done} vendor(s) on "{plan.name}".')
        )

    def _get_or_create_default_plan(self, dry_run):
        """
        The plan to put everyone on: whichever tier is marked default, or a
        free one created here on a catalogue that has none yet.
        """
        plan = subscription_services.default_plan()
        if plan:
            if not plan.is_free:
                self.stdout.write(self.style.WARNING(
                    f'The default plan "{plan.name}" costs {plan.price}. '
                    f'Backfilling would put every vendor on a paid tier for '
                    f'nothing. Mark a free plan as the default first.'
                ))
                return None
            return plan

        existing = SubscriptionPlan.objects.filter(name__iexact=FREE_PLAN_NAME).first()
        if existing:
            if dry_run:
                self.stdout.write(
                    f'Would mark the existing "{existing.name}" plan as default.'
                )
                return existing
            existing.is_default = True
            existing.is_active = True
            existing.save()
            self.stdout.write(f'Marked "{existing.name}" as the default plan.')
            return existing

        if dry_run:
            self.stdout.write(f'Would create a free "{FREE_PLAN_NAME}" default plan.')
            # Nothing to hand back that the caller can count against, but the
            # vendor tally below is still worth printing.
            return SubscriptionPlan(name=FREE_PLAN_NAME, price=0)

        plan = SubscriptionPlan.objects.create(
            name=FREE_PLAN_NAME,
            description=FREE_PLAN_DESCRIPTION,
            price=0,
            billing_period=SubscriptionPlan.BillingPeriod.LIFETIME,
            features=FREE_PLAN_FEATURES,
            is_active=True,
            is_default=True,
            sort_order=0,
        )
        self.stdout.write(self.style.SUCCESS(f'Created the "{plan.name}" plan.'))
        return plan
