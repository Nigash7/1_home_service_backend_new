from django.db import models
from django.conf import settings

from config.storages import private_storage
from .regions import (
    canonical_state, district_label, normalize_region, state_key,
)


class VendorQuerySet(models.QuerySet):
    """Reusable filters shared by the customer API and the dashboard."""

    def pro(self):
        """
        Pro vendors a customer is allowed to see: flagged by an admin *and*
        verified. An unverified vendor never reaches the customer app, even
        when someone ticks "Pro" before the paperwork is reviewed.
        """
        return self.filter(is_pro=True, verification_status='VERIFIED')

    def for_category(self, category_id):
        """Anyone who does *something* in this category, however narrowly."""
        return self.filter(
            models.Q(categories__id=category_id)
            | models.Q(subcategories__category_id=category_id)
            | models.Q(services__category_id=category_id)
        ).distinct()

    def for_service(self, service):
        """
        Vendors who actually do this one service.

        Coverage is most-specific-wins. A vendor listed against the service
        itself, or against its subcategory, always counts. A vendor listed
        only against the category counts as well -- unless they have narrowed
        themselves somewhere inside that category, in which case only their
        narrower picks apply and the rest of the category is not theirs.
        """
        explicit = models.Q(services=service)
        if service.subcategory_id:
            explicit |= models.Q(subcategories=service.subcategory_id)

        # Vendors who have said something more specific inside this category.
        narrowed = self.model.objects.filter(
            models.Q(services__category=service.category_id)
            | models.Q(subcategories__category=service.category_id)
        ).values('pk')

        category_wide = models.Q(categories=service.category_id) & ~models.Q(
            pk__in=narrowed
        )
        return self.filter(explicit | category_wide).distinct()

    def bookable(self):
        """
        Vendors who could actually take a job right now -- verified, on duty
        and not marked offline. What a customer is really asking about when
        they ask whether a service can be had where they live.
        """
        return self.filter(
            verification_status='VERIFIED', is_available=True
        ).exclude(status='OFFLINE')

    def serving_area(self, state, district=''):
        """
        Vendors who work in this place.

        Coverage is most-specific-wins, the same shape as the category
        narrowing above it:

          no rows at all          every state
          a row with no district  the whole of that state
          rows with districts     only those districts of that state

        So naming a state is how a vendor narrows themselves to it, and naming
        districts is how they narrow themselves inside it. Nothing named is
        never "nowhere" -- it keeps every vendor recorded before coverage
        existed reachable.

        A customer whose district we do not know is matched on their state
        alone: missing data must not be the thing that hides a vendor.
        """
        key = state_key(state)
        if not key:
            return self.none()

        here = models.Q(service_regions__state_key=key)
        district_key = normalize_region(district)
        if district_key:
            # The whole-state row, or one naming this district. Both sit in
            # the same filter() call, so they must hold of the *same* row.
            here &= models.Q(
                service_regions__district_key__in=['', district_key]
            )

        return self.filter(
            here | models.Q(service_regions__isnull=True)
        ).distinct()

    def outside_area(self, state, district=''):
        """
        Vendors who said where they work and left this place out -- the ones
        the customer app offers when nobody covers the customer's own.

        The mirror of serving_area, so a vendor is never in both lists.
        """
        if not state_key(state):
            return self.none()

        serving = self.model._default_manager.serving_area(
            state, district
        ).values('pk')
        return self.exclude(service_regions__isnull=True).exclude(
            pk__in=serving
        ).distinct()

    def with_review_stats(self):
        """Annotates the rating figures every pro vendor card shows."""
        return self.annotate(
            avg_rating=models.Avg('reviews_received__rating'),
            review_count=models.Count('reviews_received', distinct=True),
        )


class Vendor(models.Model):
    """
    Extra profile info for a User with role=VENDOR.
    Created by ADMIN after verifying documents (not self-registered).
    """

    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        VERIFIED = 'VERIFIED', 'Verified'
        REJECTED = 'REJECTED', 'Rejected'

    class AvailabilityStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        BUSY = 'BUSY', 'Busy'
        OFFLINE = 'OFFLINE', 'Offline'

    # Booking statuses that mean "this vendor is actively on a job right now"
    ACTIVE_JOB_STATUSES = ['ASSIGNED', 'IN_PROGRESS']

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vendor_profile'
    )

    # Categories this vendor can do work for (a vendor could be both Plumber + Electrician)
    categories = models.ManyToManyField(
        'services.ServiceCategory', related_name='vendors', blank=True
    )

    # Not every vendor does everything in a category -- a small outfit might
    # only take 3D design work out of the whole Architect category. These two
    # narrow the categories above; leaving them empty keeps the vendor on the
    # whole category, which is how every existing vendor is set up.
    subcategories = models.ManyToManyField(
        'services.SubCategory', related_name='vendors', blank=True,
        help_text="Limit to these subcategories. Empty = the whole category.",
    )
    services = models.ManyToManyField(
        'services.Service', related_name='vendors', blank=True,
        help_text="Limit to these individual services. Empty = the whole subcategory.",
    )

    # Service area — used for "nearest vendor" matching (address-based, per your decision)
    service_area = models.CharField(
        max_length=255, help_text="e.g. area/zone/pincode this vendor covers"
    )
    address = models.TextField(blank=True)

    # Where the vendor themselves is based. Shown on their card so a customer
    # offered a vendor from outside their own state can see where that vendor
    # actually is. Where they *work* is a separate list --
    # VendorServiceRegion -- because the two are not the same thing: a vendor
    # based in Ernakulam may cover three districts, or none but their own.
    state = models.CharField(
        max_length=100, blank=True, help_text="State the vendor is based in"
    )
    district = models.CharField(
        max_length=100, blank=True, help_text="District the vendor is based in"
    )

    verification_status = models.CharField(
        max_length=10,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )

    last_assigned_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When this vendor was last given a job (for round-robin)"
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    is_available = models.BooleanField(
        default=True, help_text="Toggle off when vendor is busy/on leave"
    )

    status = models.CharField(
        max_length=10,
        choices=AvailabilityStatus.choices,
        default=AvailabilityStatus.AVAILABLE,
        help_text="Available = free, Busy = on a job, Offline = not working",
    )

    # ---------- Pro Vendor showcase (admin-managed) ----------
    # A "Pro" is a vendor the admin has chosen to put in front of customers:
    # they get a profile page in the customer app, can be curated into home
    # screen sections and pointed at from the banners. None of it is
    # vendor-editable -- the vendor app never writes these fields.
    is_pro = models.BooleanField(
        default=False, help_text="Show this vendor to customers as a Pro Vendor"
    )
    pro_title = models.CharField(
        max_length=100, blank=True,
        help_text="Headline under the name, e.g. Master Electrician",
    )
    pro_tagline = models.CharField(
        max_length=160, blank=True,
        help_text="One-line pitch shown on the pro vendor card",
    )
    pro_bio = models.TextField(
        blank=True, help_text="Longer intro shown on the vendor's profile page"
    )
    pro_photo = models.ImageField(
        upload_to='pro_vendor_photos/', blank=True, null=True,
        help_text="Square headshot used on the cards and the profile page",
    )
    pro_banner = models.ImageField(
        upload_to='pro_vendor_banners/', blank=True, null=True,
        help_text="Wide image across the top of the profile page",
    )
    experience_years = models.PositiveIntegerField(
        default=0, help_text="Years of experience, shown on the profile"
    )
    pro_sort_order = models.PositiveIntegerField(
        default=0, help_text="Lower number = shown first among pro vendors"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = VendorQuerySet.as_manager()

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.service_area}"

    def covers(self, service):
        """
        Whether this vendor does `service`. Mirrors
        VendorQuerySet.for_service, for code that already holds the vendor
        (assignment) rather than building a queryset.
        """
        if any(s.id == service.id for s in self.services.all()):
            return True
        if service.subcategory_id and any(
            sub.id == service.subcategory_id for sub in self.subcategories.all()
        ):
            return True

        if not any(c.id == service.category_id for c in self.categories.all()):
            return False

        # On the category, but did they narrow themselves inside it?
        narrowed = any(
            s.category_id == service.category_id for s in self.services.all()
        ) or any(
            sub.category_id == service.category_id for sub in self.subcategories.all()
        )
        return not narrowed

    def covered_services(self):
        """
        Every active service this vendor actually does -- the queryset form of
        `covers()`, so the app never has to work coverage out for itself.
        """
        from services.models import Service

        service_ids = [s.id for s in self.services.all()]
        subcategory_ids = [sub.id for sub in self.subcategories.all()]

        # Categories the vendor narrowed themselves inside; the rest of those
        # categories is not theirs.
        narrowed_category_ids = {
            s.category_id for s in self.services.all()
        } | {sub.category_id for sub in self.subcategories.all()}

        whole_category_ids = [
            c.id for c in self.categories.all()
            if c.id not in narrowed_category_ids
        ]

        match = models.Q(id__in=service_ids)
        if subcategory_ids:
            match |= models.Q(subcategory_id__in=subcategory_ids)
        if whole_category_ids:
            match |= models.Q(category_id__in=whole_category_ids)

        return Service.objects.filter(match, is_active=True).select_related(
            'category', 'subcategory'
        ).order_by('category__name', 'subcategory__name', 'name')

    @property
    def coverage_labels(self):
        """
        What this vendor works on, named as narrowly as it truly is.

        A vendor limited to 3D design should not read as covering the whole
        Architect category, so wherever they have narrowed themselves the
        narrower names are used. Shared by the customer API and the dashboard
        so both tell the same story.
        """
        labels = []
        narrowed_category_ids = set()

        for service in self.services.all():
            labels.append(service.name)
            narrowed_category_ids.add(service.category_id)

        for sub in self.subcategories.all():
            # A subcategory the vendor has already been pinned to by service
            # would just repeat what those services say.
            if not any(s.subcategory_id == sub.id for s in self.services.all()):
                labels.append(sub.name)
            narrowed_category_ids.add(sub.category_id)

        for category in self.categories.all():
            if category.id not in narrowed_category_ids:
                labels.append(category.name)

        # Keep the first occurrence of each label, order intact.
        return list(dict.fromkeys(labels))

    def serves(self, state, district=''):
        """
        Whether this vendor works in this place. Mirrors
        VendorQuerySet.serving_area for code that already holds the vendor.

        Nothing named means everywhere; a state named with no district means
        the whole of it; districts named mean only those. A district we were
        not told is matched on the state alone.
        """
        rows = list(self.service_regions.all())
        if not rows:
            return True

        key = state_key(state)
        if not key:
            return False

        here = [row for row in rows if row.state_key == key]
        if not here:
            return False
        if any(not row.district_key for row in here):
            return True

        district_key = normalize_region(district)
        if not district_key:
            # They cover part of this state and we cannot tell which part.
            # Offering them beats hiding them over an address we never asked
            # the customer to fill in.
            return True

        return any(row.district_key == district_key for row in here)

    @property
    def service_region_labels(self):
        """
        Where this vendor works, one label per state:
        "Kerala — Ernakulam, Thrissur", or just "Kerala" for the whole of it.

        Empty means every state.
        """
        by_state = {}
        for row in self.service_regions.all():
            by_state.setdefault(row.state, [])
            if row.district:
                by_state[row.state].append(row.district)

        labels = []
        for state, districts in by_state.items():
            labels.append(
                f"{state} — {', '.join(districts)}" if districts else state
            )
        return labels

    @property
    def location_label(self):
        """
        Where the vendor is based, as one line: "Ernakulam, Kerala". Empty
        when neither has been recorded, so callers can skip the row entirely.
        """
        return ', '.join(part for part in (self.district, self.state) if part)

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def average_rating(self):
        """Mean rating out of 5. Prefers the annotation to avoid an N+1."""
        if hasattr(self, 'avg_rating'):
            return round(self.avg_rating or 0, 1)
        return round(
            self.reviews_received.aggregate(avg=models.Avg('rating'))['avg'] or 0, 1
        )

    @property
    def total_reviews(self):
        if hasattr(self, 'review_count'):
            return self.review_count
        return self.reviews_received.count()

    @property
    def completed_job_count(self):
        """Jobs finished — the "X jobs done" figure on the profile page."""
        if hasattr(self, 'completed_jobs'):
            return self.completed_jobs

        from bookings.models import Booking
        return Booking.objects.filter(vendor=self, status='COMPLETED').count()

    @property
    def active_job_count(self):
        """Number of jobs this vendor is currently working on."""
        # Annotated value wins if the queryset already computed it (avoids N+1)
        if hasattr(self, '_active_jobs'):
            return self._active_jobs

        from bookings.models import Booking
        return Booking.objects.filter(
            vendor=self, status__in=self.ACTIVE_JOB_STATUSES
        ).count()

    @property
    def active_subscription(self):
        """
        The vendor's live subscription, or None when they hold nothing.

        Nothing is gated on this -- a vendor with no plan works exactly like a
        vendor with one -- it is here so the dashboard and the vendor API
        agree on what "subscribed" means.
        """
        from subscriptions.models import VendorSubscription
        return VendorSubscription.objects.active_for(self)

    @property
    def subscription_plan_name(self):
        subscription = self.active_subscription
        return subscription.plan.name if subscription else ''

    @property
    def computed_status(self):
        """
        Live availability:
          OFFLINE   - manually set (leave, not working)
          BUSY      - has at least one active job
          AVAILABLE - free to take work
        """
        if self.status == self.AvailabilityStatus.OFFLINE or not self.is_available:
            return self.AvailabilityStatus.OFFLINE

        if self.active_job_count > 0:
            return self.AvailabilityStatus.BUSY

        return self.AvailabilityStatus.AVAILABLE


class VendorServiceRegion(models.Model):
    """
    One place a vendor has said they can take work in: a state, and
    optionally a single district inside it.

    A vendor with no rows covers every state. A row with no district covers
    the whole of that state. Rows naming districts cover only those, so
    naming districts is how a vendor narrows themselves inside a state they
    already cover -- the same most-specific-wins shape the category,
    subcategory and service coverage above it uses.

    Both names are stored as they were typed and matched on their keys.
    Customers type their own state and district by hand, so nobody should be
    told their zone is uncovered over a capital letter.
    """

    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name='service_regions'
    )
    state = models.CharField(max_length=100)
    state_key = models.CharField(
        max_length=100, db_index=True, editable=False,
        help_text="Normalized form of `state`; set on save, never by hand.",
    )
    district = models.CharField(
        max_length=100, blank=True,
        help_text="Leave empty to cover the whole state.",
    )
    district_key = models.CharField(
        max_length=100, blank=True, db_index=True, editable=False,
        help_text="Normalized form of `district`; set on save, never by hand.",
    )

    class Meta:
        ordering = ['state', 'district']
        unique_together = ('vendor', 'state_key', 'district_key')

    def __str__(self):
        where = f"{self.state} — {self.district}" if self.district else self.state
        return f"{self.vendor.display_name} — {where}"

    def save(self, *args, **kwargs):
        self.state = canonical_state(self.state)
        self.state_key = state_key(self.state)
        self.district = district_label(self.district)
        self.district_key = normalize_region(self.district)
        super().save(*args, **kwargs)


def set_vendor_service_regions(vendor, entries):
    """
    Replaces where a vendor works with `entries`, the way `categories.set()`
    replaces their categories.

    `entries` may be plain state names, or (state, district) pairs -- a pair
    with an empty district means the whole state. Every form that writes these
    posts the whole list, so this is a full replace: a place left off is a
    place the vendor no longer covers. Blanks and repeats are dropped, and an
    empty list clears the rows, which puts the vendor back on every state.

    A state named both on its own and with districts keeps only the
    whole-state row -- the two say different things, and the wider one is
    what the vendor asked for.
    """
    wanted = {}
    for entry in entries or []:
        state, district = entry if isinstance(entry, (tuple, list)) else (entry, '')
        key = state_key(state)
        if not key:
            continue
        wanted[(key, normalize_region(district))] = (
            canonical_state(state), district_label(district),
        )

    # "The whole state" swallows any districts named alongside it.
    whole_states = {key for key, district_key in wanted if not district_key}
    wanted = {
        (key, district_key): names
        for (key, district_key), names in wanted.items()
        if not district_key or key not in whole_states
    }

    for row in vendor.service_regions.all():
        if (row.state_key, row.district_key) not in wanted:
            row.delete()

    existing = {
        (row.state_key, row.district_key)
        for row in vendor.service_regions.all()
    }
    for pair, (state, district) in wanted.items():
        if pair not in existing:
            VendorServiceRegion.objects.create(
                vendor=vendor, state=state, district=district,
            )


class VendorDocument(models.Model):
    """
    Documents uploaded for verification (ID proof, address proof, trade certificate, etc.)
    Admin reviews these before setting Vendor.verification_status = VERIFIED.
    """

    class DocType(models.TextChoices):
        ID_PROOF = 'ID_PROOF', 'ID Proof'
        ADDRESS_PROOF = 'ADDRESS_PROOF', 'Address Proof'
        TRADE_CERTIFICATE = 'TRADE_CERT', 'Trade Certificate'
        OTHER = 'OTHER', 'Other'

    IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic')

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='documents')
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    # Local disk only -- never Cloudinary. These are ID and address proofs, and
    # a Cloudinary delivery URL authorizes nobody: anyone holding the link can
    # read the file. See private_storage in config/storages.py.
    file = models.FileField(upload_to='vendor_documents/', storage=private_storage)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor} - {self.get_doc_type_display()}"

    @property
    def is_image(self):
        """Whether the admin page can preview this inline instead of linking to it."""
        return self.file.name.lower().endswith(self.IMAGE_EXTENSIONS)

    @property
    def filename(self):
        return self.file.name.rsplit('/', 1)[-1]


# Payout details live in their own module -- different rules, same app.
# Imported here so `vendors.models.VendorBankAccount` resolves and Django
# picks the models up without a second app registration.
from .bank_models import (  # noqa: E402,F401
    VendorBankAccount, VendorBankAccountChange, mask_account_number,
    IFSC_RE, ACCOUNT_NUMBER_RE, UPI_RE,
)
