from django.db import models
from django.utils import timezone


class TenderQuerySet(models.QuerySet):
    """Reusable filters shared by the vendor API and the dashboard."""

    def open_for_bids(self):
        """
        Tenders vendors may still bid on: approved, and either open-ended or
        still inside their bidding window. A tender past its deadline stays
        OPEN in the database -- the customer still has bids to compare -- it
        just stops accepting new ones.
        """
        return self.filter(status=Tender.Status.OPEN).filter(
            models.Q(bid_deadline__isnull=True)
            | models.Q(bid_deadline__gte=timezone.localdate())
        )

    def for_vendor(self, vendor):
        """
        Tenders this vendor should be shown.

        Coverage is most-specific-wins, the same rule the booking side uses
        (see VendorQuerySet.for_service). A vendor sees a tender when:

          * its subcategory is one they cover -- listed against it directly,
            or reached through one of their individual services; or
          * they are signed up for the whole category and have *not* narrowed
            themselves anywhere inside it; or
          * the tender names only a category and they do something -- however
            narrow -- inside that category. A category-wide requirement is
            broad enough that everyone working in it deserves a look.

        Mirrors Tender.matching_vendors, which walks the same rule from the
        other end. Change one and you must change the other.
        """
        category_ids = {c.id for c in vendor.categories.all()}
        services = list(vendor.services.all())
        subcategories = list(vendor.subcategories.all())

        covered_subcategory_ids = {sub.id for sub in subcategories}
        covered_subcategory_ids |= {
            s.subcategory_id for s in services if s.subcategory_id
        }

        # Categories the vendor has narrowed themselves inside; the rest of
        # those categories is not theirs.
        narrowed_category_ids = {sub.category_id for sub in subcategories}
        narrowed_category_ids |= {s.category_id for s in services}

        whole_category_ids = category_ids - narrowed_category_ids

        match = models.Q(pk__in=[])
        if covered_subcategory_ids:
            match |= models.Q(subcategory_id__in=covered_subcategory_ids)
        if whole_category_ids:
            match |= models.Q(category_id__in=whole_category_ids)
        # Category-only tenders inside a category they work in at all, even
        # where they have narrowed themselves further down.
        if narrowed_category_ids:
            match |= models.Q(
                category_id__in=narrowed_category_ids, subcategory__isnull=True
            )

        return self.filter(match).distinct()

    def with_bid_stats(self):
        """Annotates the figures every tender card and row shows."""
        live = models.Q(bids__status=TenderBid.Status.SUBMITTED)
        return self.annotate(
            bid_total=models.Count('bids', filter=live, distinct=True),
            bid_low=models.Min('bids__amount', filter=live),
            bid_high=models.Max('bids__amount', filter=live),
        )


class Tender(models.Model):
    """
    A construction requirement the customer posts for vendors to bid on.

    Unlike a Booking -- where the admin picks the vendor -- here the vendors
    come to the customer. The customer posts what they want and what they
    expect to pay, an admin approves it so nothing junk reaches vendors,
    matching vendors quote against it, and the customer picks the quote they
    like.

    Flow:
        DRAFT -> PENDING_APPROVAL -> OPEN -> AWARDED -> IN_PROGRESS -> COMPLETED
    with REJECTED (an admin said no) and CANCELLED (the customer pulled it) as
    the ways out.
    """

    class ProjectType(models.TextChoices):
        HOUSE = 'HOUSE', 'Independent House'
        APARTMENT = 'APARTMENT', 'Apartment / Flat'
        VILLA = 'VILLA', 'Villa'
        COMMERCIAL = 'COMMERCIAL', 'Commercial Space'
        RENOVATION = 'RENOVATION', 'Renovation / Remodel'
        INTERIOR = 'INTERIOR', 'Interior Work'
        OTHER = 'OTHER', 'Other'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'Pending Approval'
        REJECTED = 'REJECTED', 'Rejected'
        OPEN = 'OPEN', 'Open for Bids'
        AWARDED = 'AWARDED', 'Awarded'
        IN_PROGRESS = 'IN_PROGRESS', 'Work In Progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PARTIAL = 'PARTIAL', 'Partially Paid'
        PAID = 'PAID', 'Paid'

    # Statuses where the customer may still edit the tender before it goes out.
    EDITABLE_STATUSES = [Status.DRAFT, Status.REJECTED]
    # Statuses that mean a vendor has been chosen and work is under way.
    LIVE_STATUSES = [Status.AWARDED, Status.IN_PROGRESS]

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='tenders'
    )

    # ---------- 1. What the customer wants ----------
    title = models.CharField(
        max_length=200, help_text="Short headline, e.g. 3BHK ground-floor construction"
    )
    project_type = models.CharField(
        max_length=20, choices=ProjectType.choices, default=ProjectType.HOUSE
    )
    category = models.ForeignKey(
        'services.ServiceCategory', on_delete=models.PROTECT, related_name='tenders',
        help_text="Decides which vendors this tender is shown to",
    )
    subcategory = models.ForeignKey(
        'services.SubCategory', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tenders',
        help_text="Narrows the vendors further. Empty = the whole category.",
    )
    description = models.TextField(help_text="What the project involves")
    requirements = models.TextField(
        blank=True, help_text="Specific requirements, materials, finishes"
    )
    area_sqft = models.PositiveIntegerField(
        null=True, blank=True, help_text="Built-up area, if the customer knows it"
    )

    # ---------- 2. Expected budget (the "first price") ----------
    expected_budget = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="What the customer expects to spend. Vendors quote against this.",
    )

    # ---------- Timeline ----------
    preferred_start_date = models.DateField(
        null=True, blank=True, help_text="When the customer wants work to begin"
    )
    duration_days = models.PositiveIntegerField(
        null=True, blank=True, help_text="How long the customer expects it to take"
    )
    bid_deadline = models.DateField(
        null=True, blank=True,
        help_text="Last day vendors may bid. Empty = open until awarded.",
    )

    # ---------- Location ----------
    # Same shape as Booking's address block, and for the same reason: the site
    # is often not the address saved on the customer's profile.
    address_text = models.CharField(max_length=500, blank=True)
    address_state = models.CharField(max_length=100, blank=True)
    address_district = models.CharField(max_length=100, blank=True)
    address_pincode = models.CharField(max_length=10, blank=True)
    contact_phone = models.CharField(max_length=15, blank=True)
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # ---------- Lifecycle ----------
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    awarded_bid = models.OneToOneField(
        'TenderBid', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='awarded_for',
        help_text="The bid the customer accepted. The agreed price, work plan "
                  "and milestones all hang off it.",
    )
    rejection_reason = models.TextField(
        blank=True, help_text="Why an admin rejected it -- shown to the customer"
    )
    cancellation_reason = models.TextField(blank=True)
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    awarded_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TenderQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', '-created_at'])]

    def __str__(self):
        return f"{self.code} - {self.title} ({self.status})"

    @property
    def code(self):
        """Human-facing reference, used in notifications and on both apps."""
        return f"TND-{self.pk:05d}" if self.pk else "TND-new"

    @property
    def awarded_vendor(self):
        """
        The vendor doing the work, or None. Read through the accepted bid so
        there is only ever one answer -- a separate FK would drift the moment
        a different bid was accepted.
        """
        return self.awarded_bid.vendor if self.awarded_bid_id else None

    @property
    def final_amount(self):
        """The agreed price -- the accepted bid's amount."""
        return self.awarded_bid.amount if self.awarded_bid_id else None

    @property
    def milestones(self):
        """
        The live milestones: the ones the winning vendor proposed. Losing bids
        keep their own, they just stop mattering once someone else wins.
        """
        if not self.awarded_bid_id:
            return TenderMilestone.objects.none()
        return self.awarded_bid.milestones.all()

    @property
    def is_bidding_open(self):
        """Whether a vendor may still submit or revise a bid."""
        if self.status != self.Status.OPEN:
            return False
        return self.bid_deadline is None or self.bid_deadline >= timezone.localdate()

    @property
    def active_bids(self):
        """Bids still in the running -- a withdrawn one is not comparable."""
        return self.bids.exclude(status=TenderBid.Status.WITHDRAWN)

    @property
    def location_label(self):
        """One-line location for cards and tables."""
        parts = [self.address_district, self.address_state, self.address_pincode]
        return ', '.join(p for p in parts if p) or self.address_text

    def matching_vendors(self):
        """
        Verified vendors this tender should be offered to.

        Mirrors TenderQuerySet.for_vendor from the other end -- that decides
        what one vendor sees, this decides who hears about one tender. Change
        one and you must change the other.
        """
        from vendors.models import Vendor

        verified = Vendor.objects.filter(
            verification_status=Vendor.VerificationStatus.VERIFIED
        )

        if not self.subcategory_id:
            # Category-only: anyone who does something in this category.
            return verified.for_category(self.category_id)

        # Vendors who have said something more specific inside this category.
        narrowed = Vendor.objects.filter(
            models.Q(services__category=self.category_id)
            | models.Q(subcategories__category=self.category_id)
        ).values('pk')

        return verified.filter(
            models.Q(subcategories=self.subcategory_id)
            | models.Q(services__subcategory=self.subcategory_id)
            | (models.Q(categories=self.category_id) & ~models.Q(pk__in=narrowed))
        ).distinct()

    def refresh_payment_status(self):
        """
        Recompute payment_status from the milestones, saving only if it moved.

        With no milestones there is nothing to go on, so the field is left
        alone for an admin to set by hand.
        """
        milestones = list(self.milestones)
        if not milestones:
            return self.payment_status

        paid = sum(1 for m in milestones if m.status == TenderMilestone.Status.PAID)
        if paid == 0:
            new_status = self.PaymentStatus.UNPAID
        elif paid == len(milestones):
            new_status = self.PaymentStatus.PAID
        else:
            new_status = self.PaymentStatus.PARTIAL

        if new_status != self.payment_status:
            self.payment_status = new_status
            self.save(update_fields=['payment_status', 'updated_at'])
        return new_status


class TenderAttachment(models.Model):
    """
    A drawing, plan or site photo the customer attached, so vendors quote
    against something real rather than a paragraph of text.
    """

    IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic')

    tender = models.ForeignKey(
        Tender, on_delete=models.CASCADE, related_name='attachments'
    )
    file = models.FileField(upload_to='tender_attachments/')
    caption = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Attachment for {self.tender.code}"

    @property
    def is_image(self):
        """Whether the dashboard can preview this inline instead of linking."""
        return self.file.name.lower().endswith(self.IMAGE_EXTENSIONS)

    @property
    def filename(self):
        return self.file.name.rsplit('/', 1)[-1]


class TenderBid(models.Model):
    """
    One vendor's quote against a tender: their price, how they plan to do the
    work and how long they need. A vendor has at most one bid per tender --
    they revise it rather than stacking new ones.
    """

    class Status(models.TextChoices):
        SUBMITTED = 'SUBMITTED', 'Submitted'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        REJECTED = 'REJECTED', 'Not Selected'
        WITHDRAWN = 'WITHDRAWN', 'Withdrawn'

    tender = models.ForeignKey(Tender, on_delete=models.CASCADE, related_name='bids')
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='tender_bids'
    )

    amount = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="The vendor's proposed budget"
    )
    work_plan = models.TextField(
        blank=True, help_text="How the vendor intends to run the project"
    )
    timeline_days = models.PositiveIntegerField(
        null=True, blank=True, help_text="Days the vendor needs to finish"
    )
    proposed_start_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Anything else for the customer")

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_at = models.DateTimeField(
        null=True, blank=True, help_text="When it was accepted or turned down"
    )

    class Meta:
        ordering = ['amount', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tender', 'vendor'], name='one_bid_per_vendor_per_tender'
            )
        ]

    def __str__(self):
        return f"Bid {self.amount} by {self.vendor} on {self.tender.code}"

    @property
    def is_editable(self):
        """A vendor may revise a bid only while the tender still takes bids."""
        return self.status == self.Status.SUBMITTED and self.tender.is_bidding_open

    @property
    def difference_from_expected(self):
        """
        How far the quote sits from what the customer budgeted. Positive means
        over budget -- the figure the comparison screen leads with.
        """
        return self.amount - self.tender.expected_budget

    @property
    def milestone_total(self):
        """
        What the proposed milestones add up to. Worth showing beside the bid
        amount: the two should agree, and when they do not the customer wants
        to know before choosing.
        """
        return sum((m.amount for m in self.milestones.all()), start=0)


class TenderMilestone(models.Model):
    """
    A stage of work with money attached, proposed by the vendor as part of
    their bid. The winning bid's milestones become the project's payment plan;
    the rest are simply never looked at again.

    Nothing here moves money -- it records what was agreed and what the
    customer says they have settled, the same way Booking.payment_status does.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        REACHED = 'REACHED', 'Reached'
        PAID = 'PAID', 'Paid'

    bid = models.ForeignKey(
        TenderBid, on_delete=models.CASCADE, related_name='milestones'
    )
    title = models.CharField(max_length=200, help_text="e.g. Foundation complete")
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sort_order = models.PositiveIntegerField(default=0, help_text="Lower number = earlier")

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    reached_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f"{self.title} ({self.amount})"

    @property
    def tender(self):
        return self.bid.tender


class TenderProgressUpdate(models.Model):
    """
    A note from the vendor while work is running, so the customer can see
    where the project has got to without visiting the site.
    """

    tender = models.ForeignKey(
        Tender, on_delete=models.CASCADE, related_name='progress_updates'
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.CASCADE, related_name='tender_progress_updates'
    )
    message = models.TextField()
    percent_complete = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="0-100, if the vendor gave a figure"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Update on {self.tender.code} at {self.created_at:%Y-%m-%d}"


class TenderProgressPhoto(models.Model):
    """A photo attached to a progress update. An update can carry several."""

    update = models.ForeignKey(
        TenderProgressUpdate, on_delete=models.CASCADE, related_name='photos'
    )
    image = models.ImageField(upload_to='tender_progress_photos/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Photo for update #{self.update_id}"
