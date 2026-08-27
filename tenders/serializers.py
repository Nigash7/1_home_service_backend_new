from django.db import transaction
from django.db.models import Max, Min
from rest_framework import serializers

from .models import (
    Tender,
    TenderAttachment,
    TenderBid,
    TenderMilestone,
    TenderProgressPhoto,
    TenderProgressUpdate,
)


class TenderAttachmentSerializer(serializers.ModelSerializer):
    """A drawing or site photo on the tender."""

    class Meta:
        model = TenderAttachment
        fields = ['id', 'file', 'caption', 'is_image', 'filename', 'uploaded_at']
        read_only_fields = ['id', 'is_image', 'filename', 'uploaded_at']


class TenderMilestoneSerializer(serializers.ModelSerializer):
    """
    A stage of work with money against it. Vendors write these as part of a
    bid; after that only `status` moves, and only through the dedicated
    reach/pay endpoints.
    """

    class Meta:
        model = TenderMilestone
        fields = [
            'id', 'title', 'description', 'amount', 'sort_order',
            'status', 'reached_at', 'paid_at',
        ]
        read_only_fields = ['id', 'status', 'reached_at', 'paid_at']


class TenderWriteSerializer(serializers.ModelSerializer):
    """
    Customer app: create or edit a tender.

    Everything about the lifecycle is read-only here -- a tender is published
    through /publish/, approved by an admin, and awarded through the bid
    endpoints. Letting the app POST a status would let it skip the queue.
    """

    class Meta:
        model = Tender
        fields = [
            'id', 'title', 'project_type', 'category', 'subcategory',
            'description', 'requirements', 'area_sqft',
            'expected_budget',
            'preferred_start_date', 'duration_days', 'bid_deadline',
            'address_text', 'address_state', 'address_district',
            'address_pincode', 'contact_phone', 'location_lat', 'location_lng',
            'status', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

    def validate_expected_budget(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("Enter the budget you expect to spend.")
        return value

    def validate(self, attrs):
        # Fall back to the stored values so a PATCH that touches only one of
        # the pair is still checked against the other.
        category = attrs.get('category', getattr(self.instance, 'category', None))
        subcategory = attrs.get('subcategory', getattr(self.instance, 'subcategory', None))
        if subcategory and category and subcategory.category_id != category.id:
            raise serializers.ValidationError(
                {'subcategory': 'That subcategory is not part of the chosen category.'}
            )

        deadline = attrs.get('bid_deadline', getattr(self.instance, 'bid_deadline', None))
        start = attrs.get(
            'preferred_start_date', getattr(self.instance, 'preferred_start_date', None)
        )
        if deadline and start and deadline > start:
            # Name both dates: the app shows this straight to the customer,
            # and "one of your dates is wrong" is not something they can act on.
            raise serializers.ValidationError({
                'bid_deadline': (
                    f'Bidding closes {deadline:%d %b %Y} but work is meant to '
                    f'start {start:%d %b %Y}. Move the bid deadline earlier, '
                    f'or the start date later.'
                )
            })
        return attrs

    def create(self, validated_data):
        customer = self.context['request'].user.customer_profile
        return Tender.objects.create(customer=customer, **validated_data)


class TenderListSerializer(serializers.ModelSerializer):
    """
    Row/card shape, shared by the customer's "My Tenders" list and the vendor's
    browse feed. Readable names, not bare IDs, and the bid figures both sides
    lead with.
    """

    code = serializers.CharField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    subcategory_name = serializers.CharField(
        source='subcategory.name', read_only=True, default=None
    )
    project_type_display = serializers.CharField(
        source='get_project_type_display', read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    location_label = serializers.CharField(read_only=True)
    is_bidding_open = serializers.BooleanField(read_only=True)
    bid_count = serializers.SerializerMethodField()
    lowest_bid = serializers.SerializerMethodField()
    highest_bid = serializers.SerializerMethodField()
    awarded_vendor_name = serializers.SerializerMethodField()
    final_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    attachment_count = serializers.SerializerMethodField()

    class Meta:
        model = Tender
        fields = [
            'id', 'code', 'title', 'project_type', 'project_type_display',
            'category', 'category_name', 'subcategory', 'subcategory_name',
            'expected_budget', 'area_sqft',
            'preferred_start_date', 'duration_days', 'bid_deadline',
            'address_district', 'address_state', 'address_pincode',
            'location_label',
            'status', 'status_display', 'is_bidding_open',
            'bid_count', 'lowest_bid', 'highest_bid',
            'awarded_vendor_name', 'final_amount', 'payment_status',
            'attachment_count',
            'created_at', 'published_at', 'awarded_at', 'completed_at',
        ]

    # with_bid_stats() annotates these; the fallbacks keep the serializer
    # usable on a plain instance (a freshly created tender, say).
    def get_bid_count(self, obj):
        if hasattr(obj, 'bid_total'):
            return obj.bid_total
        return obj.bids.filter(status=TenderBid.Status.SUBMITTED).count()

    def get_lowest_bid(self, obj):
        if hasattr(obj, 'bid_low'):
            return obj.bid_low
        return obj.bids.filter(status=TenderBid.Status.SUBMITTED).aggregate(
            low=Min('amount')
        )['low']

    def get_highest_bid(self, obj):
        if hasattr(obj, 'bid_high'):
            return obj.bid_high
        return obj.bids.filter(status=TenderBid.Status.SUBMITTED).aggregate(
            high=Max('amount')
        )['high']

    def get_awarded_vendor_name(self, obj):
        vendor = obj.awarded_vendor
        return vendor.display_name if vendor else None

    def get_attachment_count(self, obj):
        return obj.attachments.count()


class TenderBidSerializer(serializers.ModelSerializer):
    """
    A bid as the customer compares it: price against their budget, plus the
    vendor's profile, rating, experience and reviews -- everything the
    "Compare Bids" screen puts side by side.
    """

    vendor_name = serializers.CharField(source='vendor.display_name', read_only=True)
    vendor_title = serializers.CharField(source='vendor.pro_title', read_only=True)
    vendor_photo = serializers.ImageField(source='vendor.pro_photo', read_only=True)
    vendor_phone = serializers.SerializerMethodField()
    vendor_rating = serializers.SerializerMethodField()
    vendor_review_count = serializers.SerializerMethodField()
    vendor_experience_years = serializers.IntegerField(
        source='vendor.experience_years', read_only=True
    )
    vendor_completed_jobs = serializers.SerializerMethodField()
    vendor_is_pro = serializers.BooleanField(source='vendor.is_pro', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    difference_from_expected = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    milestone_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    milestones = TenderMilestoneSerializer(many=True, read_only=True)

    class Meta:
        model = TenderBid
        fields = [
            'id', 'tender', 'vendor',
            'vendor_name', 'vendor_title', 'vendor_photo', 'vendor_phone',
            'vendor_rating', 'vendor_review_count', 'vendor_experience_years',
            'vendor_completed_jobs', 'vendor_is_pro',
            'amount', 'difference_from_expected',
            'work_plan', 'timeline_days', 'proposed_start_date', 'notes',
            'milestones', 'milestone_total',
            'status', 'status_display', 'created_at', 'updated_at', 'decided_at',
        ]

    def get_vendor_phone(self, obj):
        """
        Only handed over once the vendor has actually won. Before that the
        customer is comparing quotes, not calling round.
        """
        if obj.status != TenderBid.Status.ACCEPTED:
            return None
        return obj.vendor.user.phone_number or ''

    def get_vendor_rating(self, obj):
        return obj.vendor.average_rating

    def get_vendor_review_count(self, obj):
        return obj.vendor.total_reviews

    def get_vendor_completed_jobs(self, obj):
        return obj.vendor.completed_job_count


class TenderBidWriteSerializer(serializers.ModelSerializer):
    """
    Vendor app: submit or revise a bid, milestones and all.

    Milestones are written nested because they only make sense as a set -- a
    payment plan with one stage replaced halfway through is not a plan. Every
    save replaces them wholesale.
    """

    milestones = TenderMilestoneSerializer(many=True, required=False)

    class Meta:
        model = TenderBid
        fields = [
            'id', 'amount', 'work_plan', 'timeline_days',
            'proposed_start_date', 'notes', 'milestones',
            'status', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

    def validate_amount(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("Enter the budget you are quoting.")
        return value

    def _save_milestones(self, bid, milestones):
        """
        Replace the bid's milestones with the ones just submitted.

        Sort order is taken from the order they arrived unless the vendor set
        it explicitly, so the app can post a plain list and get the stages back
        in the order the customer typed them.
        """
        bid.milestones.all().delete()
        for index, milestone in enumerate(milestones):
            milestone.setdefault('sort_order', index)
            TenderMilestone.objects.create(bid=bid, **milestone)

    @transaction.atomic
    def create(self, validated_data):
        milestones = validated_data.pop('milestones', None)
        bid = TenderBid.objects.create(
            tender=self.context['tender'],
            vendor=self.context['request'].user.vendor_profile,
            **validated_data,
        )
        if milestones:
            self._save_milestones(bid, milestones)
        return bid

    @transaction.atomic
    def update(self, instance, validated_data):
        milestones = validated_data.pop('milestones', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        # `None` means the vendor left milestones out of this edit, so keep
        # what they had. An empty list means they cleared the plan on purpose.
        if milestones is not None:
            self._save_milestones(instance, milestones)
        return instance


class TenderProgressPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenderProgressPhoto
        fields = ['id', 'image', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']


class TenderProgressUpdateSerializer(serializers.ModelSerializer):
    """
    Vendor app: post how the job is going, with photos.

    Photos arrive as repeated `images` parts in a multipart request, which is
    how the Flutter side sends a multi-pick.
    """

    vendor_name = serializers.CharField(source='vendor.display_name', read_only=True)
    photos = TenderProgressPhotoSerializer(many=True, read_only=True)
    images = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False,
    )

    class Meta:
        model = TenderProgressUpdate
        fields = [
            'id', 'message', 'percent_complete',
            'vendor_name', 'photos', 'images', 'created_at',
        ]
        read_only_fields = ['id', 'vendor_name', 'photos', 'created_at']

    def validate_percent_complete(self, value):
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError("Progress has to be between 0 and 100.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        images = validated_data.pop('images', [])
        update = TenderProgressUpdate.objects.create(
            tender=self.context['tender'],
            vendor=self.context['request'].user.vendor_profile,
            **validated_data,
        )
        for image in images:
            TenderProgressPhoto.objects.create(update=update, image=image)
        return update


class TenderDetailSerializer(TenderListSerializer):
    """
    Everything about one tender: the brief, the drawings, the accepted bid and
    the whole execution history. Used by both apps and by the dashboard API.
    """

    attachments = TenderAttachmentSerializer(many=True, read_only=True)
    awarded_bid = TenderBidSerializer(read_only=True)
    milestones = TenderMilestoneSerializer(many=True, read_only=True)
    progress_updates = TenderProgressUpdateSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    my_bid = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()

    class Meta(TenderListSerializer.Meta):
        fields = TenderListSerializer.Meta.fields + [
            'description', 'requirements',
            'address_text', 'location_lat', 'location_lng',
            'customer_name', 'customer_phone',
            'attachments', 'awarded_bid', 'milestones', 'progress_updates',
            'my_bid', 'review',
            'rejection_reason', 'cancellation_reason',
            'submitted_at', 'started_at', 'updated_at',
        ]

    def get_customer_name(self, obj):
        return str(obj.customer)

    def get_customer_phone(self, obj):
        """
        Withheld until a vendor is on the job. An open tender is not a lead
        list -- only the vendor who won gets the number.
        """
        vendor = self._request_vendor()
        awarded = obj.awarded_vendor
        if vendor is not None and (awarded is None or awarded.id != vendor.id):
            return None
        return obj.contact_phone or obj.customer.user.phone_number or ''

    def get_my_bid(self, obj):
        """The reading vendor's own bid, so the app knows what to show."""
        vendor = self._request_vendor()
        if vendor is None:
            return None
        bid = obj.bids.filter(vendor=vendor).first()
        return TenderBidSerializer(bid, context=self.context).data if bid else None

    def get_review(self, obj):
        review = getattr(obj, 'review', None)
        if review is None:
            return None
        return {
            'id': review.id,
            'rating': review.rating,
            'comment': review.comment,
            'created_at': review.created_at,
        }

    def _request_vendor(self):
        """The vendor reading this, or None when it is a customer or admin."""
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        return getattr(user, 'vendor_profile', None)


class TenderReviewSerializer(serializers.Serializer):
    """
    Rating the customer leaves once the project is done. Writes into the
    shared reviews.Review table so it counts towards the vendor's rating
    everywhere it is already shown.
    """

    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default='')
