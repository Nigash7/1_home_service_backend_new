from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from accounts.models import User
from services.models import ServiceCategory
from services.serializers import ServiceCategorySerializer
from subscriptions import services as subscription_services
from subscriptions.models import SubscriptionPlan
from .models import Vendor, VendorDocument, set_vendor_service_regions


class VendorProfileSerializer(serializers.ModelSerializer):
    """
    Read-only view of a vendor's own profile for the Vendor app's home/profile screen.
    Vendor CANNOT edit their own verification_status or categories -- only admin can.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    categories = ServiceCategorySerializer(many=True, read_only=True)
    service_regions = serializers.SerializerMethodField()
    # Enough for the profile screen's plan card without a second round trip.
    # The full picture -- history, what else is on offer -- lives at
    # /api/subscriptions/me/.
    subscription = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number', 'email',
            'categories', 'service_area', 'address', 'state', 'district',
            'service_regions', 'verification_status', 'is_available',
            # The app reads these back to show whether a work location is on
            # file; without them the location screen can never confirm a save.
            'latitude', 'longitude',
            'subscription',
        ]
        read_only_fields = [
            'verification_status', 'categories', 'latitude', 'longitude',
            # Coverage is an admin decision, like the categories above it.
            'state', 'district',
        ]

    def get_service_regions(self, vendor):
        """Where this vendor works. Empty means every state."""
        return vendor.service_region_labels

    def get_subscription(self, vendor):
        """The plan card, or None when the vendor is on nothing."""
        subscription = vendor.active_subscription
        if subscription is None:
            return None
        return {
            'plan_id': subscription.plan_id,
            'plan_name': subscription.plan.name,
            'price': str(subscription.plan.price),
            'is_free': subscription.plan.is_free,
            'billing_period': subscription.plan.get_billing_period_display(),
            'end_date': subscription.end_date,
            'days_remaining': subscription.days_remaining,
            'is_expiring_soon': subscription.is_expiring_soon,
        }


class VendorAvailabilitySerializer(serializers.ModelSerializer):
    """Lets a vendor toggle their own availability (busy/free) from the app."""
    class Meta:
        model = Vendor
        fields = ['is_available']


class VendorSignupSerializer(serializers.Serializer):
    """
    Self-registration from the Vendor app. Collects the same details an admin
    would fill in on the dashboard's "Add Vendor" form, minus the fields only
    an admin may decide: verification_status, is_available and status.

    Everyone who signs up here lands on PENDING and cannot log in until an
    admin verifies them from the dashboard.
    """

    # --- Login credentials ---
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    # --- Personal details ---
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=15)
    email = serializers.EmailField(required=False, allow_blank=True)

    # --- Work details ---
    categories = serializers.PrimaryKeyRelatedField(
        queryset=ServiceCategory.objects.filter(is_active=True), many=True
    )
    service_area = serializers.CharField(max_length=255)
    address = serializers.CharField(required=False, allow_blank=True)
    # Where the vendor is based...
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # ...and the states they will travel to for work. Left empty the vendor
    # covers every state, so this is how they narrow themselves, not how they
    # switch themselves on.
    service_states = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False, allow_empty=True, write_only=True,
    )
    # Districts are not asked for here. A vendor signing up on their phone
    # claims whole states; an admin narrows them to districts from the
    # dashboard, which is where the rest of their coverage is decided too.
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, required=False, allow_null=True
    )

    # --- Verification documents ---
    # An admin has nothing to review without at least a proof of identity,
    # so that one is mandatory; the rest are accepted when offered.
    id_proof = serializers.FileField(write_only=True)
    address_proof = serializers.FileField(write_only=True, required=False)
    trade_certificate = serializers.FileField(write_only=True, required=False)

    # --- Subscription ---
    # The tier they tapped on the signup screen. Optional: every vendor lands
    # on the free default regardless, and picking anything above it raises a
    # request for an admin rather than granting it. A misconfigured plan
    # catalogue must never be the reason somebody cannot register.
    plan = serializers.PrimaryKeyRelatedField(
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        required=False, allow_null=True, write_only=True,
    )

    def to_internal_value(self, data):
        # A multipart body cannot repeat a field key, so the app sends the
        # chosen categories as one comma-separated value. Expand it back into
        # the list that the many=True field expects.
        raw = data.get('categories')
        raw_states = data.get('service_states')
        if isinstance(raw, str) or isinstance(raw_states, str):
            # Shallow copy into a plain dict. QueryDict.copy() deep-copies its
            # values, and an upload big enough to be spooled to disk carries an
            # open file handle that cannot be copied.
            data = dict(data.items())
            if isinstance(raw, str):
                data['categories'] = [c for c in raw.split(',') if c.strip()]
            if isinstance(raw_states, str):
                data['service_states'] = [
                    s.strip() for s in raw_states.split(',') if s.strip()
                ]
        return super().to_internal_value(data)

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_phone_number(self, value):
        value = value.strip()
        if not value.isdigit() or len(value) < 10:
            raise serializers.ValidationError(
                "Enter a valid phone number (digits only, at least 10 digits)."
            )
        # Scoped to vendors: plenty of people book work in the customer app on
        # the same number they now want to take work on. Customer sign-in finds
        # its account by phone *and* role, so the two never reach for each
        # other -- only a second vendor account on one number is a real clash.
        if User.objects.filter(
            phone_number=value, role=User.Role.VENDOR,
        ).exists():
            raise serializers.ValidationError(
                "A vendor account already exists for this phone number."
            )
        return value

    def validate_categories(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one service category.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': "Passwords do not match."})
        try:
            validate_password(attrs['password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        documents = {
            VendorDocument.DocType.ID_PROOF: validated_data.pop('id_proof'),
            VendorDocument.DocType.ADDRESS_PROOF: validated_data.pop('address_proof', None),
            VendorDocument.DocType.TRADE_CERTIFICATE: validated_data.pop('trade_certificate', None),
        }
        categories = validated_data.pop('categories')
        service_states = validated_data.pop('service_states', [])
        chosen_plan = validated_data.pop('plan', None)
        validated_data.pop('password_confirm')

        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data.get('last_name', ''),
            email=validated_data.get('email', ''),
            phone_number=validated_data['phone_number'],
            role=User.Role.VENDOR,
        )

        vendor = Vendor.objects.create(
            user=user,
            service_area=validated_data['service_area'],
            address=validated_data.get('address', ''),
            latitude=validated_data.get('latitude'),
            longitude=validated_data.get('longitude'),
            state=validated_data.get('state', ''),
            district=validated_data.get('district', ''),
            # Set explicitly rather than trusting the model default: a
            # self-registered vendor must never start out verified.
            verification_status=Vendor.VerificationStatus.PENDING,
        )
        vendor.categories.set(categories)
        set_vendor_service_regions(vendor, service_states)

        VendorDocument.objects.bulk_create([
            VendorDocument(vendor=vendor, doc_type=doc_type, file=f)
            for doc_type, f in documents.items() if f
        ])

        self._start_subscription(vendor, chosen_plan)
        return vendor

    def _start_subscription(self, vendor, chosen_plan):
        """
        Every new vendor lands on the free default tier.

        Picking a higher tier on the signup screen does not grant it -- there
        is nothing to charge them with yet, so it is recorded as a request for
        an admin to answer. Registration must not fail over any of this, so a
        catalogue with no default plan simply leaves them unsubscribed.
        """
        subscription = subscription_services.ensure_default_subscription(vendor)

        if chosen_plan is None:
            return
        if subscription and subscription.plan_id == chosen_plan.id:
            return

        try:
            subscription_services.request_upgrade(
                vendor, chosen_plan, note='Chosen during signup',
            )
        except subscription_services.SubscriptionError:
            # Nothing here is worth losing a registration over.
            pass


def _absolute(serializer, image):
    """Absolute media URL for an image field, or None when it is empty."""
    if not image or not hasattr(image, 'url'):
        return None
    request = serializer.context.get('request')
    return request.build_absolute_uri(image.url) if request else image.url


class ProVendorCardSerializer(serializers.ModelSerializer):
    """
    The compact pro vendor used in the home sections, the banners' tap
    targets and the "Pro vendors for this service" row on a service page.
    """
    name = serializers.CharField(source='display_name', read_only=True)
    photo = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    average_rating = serializers.FloatField(read_only=True)
    total_reviews = serializers.IntegerField(read_only=True)
    # Where this vendor is based, and the states they take work in. The card
    # shows both whenever it is offering a vendor from outside the customer's
    # own state, so nobody has to open a profile to find out where they are.
    location_label = serializers.CharField(read_only=True)
    service_regions = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            'id', 'name', 'pro_title', 'pro_tagline', 'photo',
            'experience_years', 'average_rating', 'total_reviews',
            'categories', 'service_area', 'state', 'district',
            'location_label', 'service_regions',
            # The fallback list on a service page can carry vendors who were
            # never put on show, so the card has to be able to tell the two
            # apart -- only a pro wears the badge and has a profile to open.
            'is_pro',
        ]

    def get_photo(self, obj):
        return _absolute(self, obj.pro_photo)

    def get_categories(self, obj):
        return obj.coverage_labels

    def get_service_regions(self, obj):
        """Where this vendor works. Empty means they cover every state."""
        return obj.service_region_labels


class ProVendorServiceSerializer(serializers.ModelSerializer):
    """A service a pro can be booked for, with everything the app needs to
    open its detail screen without another round trip."""
    # Null on the types where it means nothing -- see ServiceSerializer.
    duration_minutes = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    subcategory_name = serializers.CharField(
        source='subcategory.name', read_only=True, default=None
    )
    image = serializers.SerializerMethodField()
    # How `price` becomes an amount, so every card and the cart agree.
    # `price_label` is the ready-made line ("₹15 / sq ft", "From ₹499",
    # "Price on request"); the rest let a screen build its own.
    price_label = serializers.CharField(read_only=True)
    unit_label = serializers.CharField(read_only=True)
    measure_label = serializers.CharField(read_only=True)
    needs_quantity = serializers.BooleanField(read_only=True)
    allows_decimal_quantity = serializers.BooleanField(read_only=True)
    is_quote_only = serializers.BooleanField(read_only=True)

    class Meta:
        from services.models import Service
        model = Service
        fields = [
            'id', 'name', 'description', 'image', 'price', 'duration_minutes',
            'category', 'category_name', 'subcategory', 'subcategory_name',
            'pricing_type', 'price_label', 'unit_label', 'measure_label',
            'needs_quantity', 'allows_decimal_quantity', 'is_quote_only',
            # What the tender form opens with when a quote service sends
            # the customer there.
            'tender_project_type',
        ]

    def get_image(self, obj):
        return _absolute(self, obj.image)

    def get_duration_minutes(self, obj):
        return obj.duration_minutes if obj.shows_duration else None


class ProVendorDetailSerializer(ProVendorCardSerializer):
    """Everything the customer app's pro vendor profile screen renders."""
    banner = serializers.SerializerMethodField()
    category_ids = serializers.SerializerMethodField()
    completed_jobs = serializers.IntegerField(
        source='completed_job_count', read_only=True
    )
    bookable_services = serializers.SerializerMethodField()

    class Meta(ProVendorCardSerializer.Meta):
        fields = ProVendorCardSerializer.Meta.fields + [
            'pro_bio', 'banner', 'category_ids', 'completed_jobs',
            'bookable_services',
        ]

    def get_bookable_services(self, obj):
        """
        Exactly what this pro can be booked for. Worked out here rather than
        in the app, so a vendor narrowed to part of a category is never
        offered the rest of it.
        """
        return ProVendorServiceSerializer(
            obj.covered_services(), many=True, context=self.context
        ).data

    def get_banner(self, obj):
        return _absolute(self, obj.pro_banner)

    def get_category_ids(self, obj):
        return [c.id for c in obj.categories.all()]
