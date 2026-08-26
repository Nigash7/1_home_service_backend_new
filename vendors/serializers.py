from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from accounts.models import User
from services.models import ServiceCategory
from services.serializers import ServiceCategorySerializer
from .models import Vendor, VendorDocument


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

    class Meta:
        model = Vendor
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number', 'email',
            'categories', 'service_area', 'address', 'verification_status', 'is_available',
            # The app reads these back to show whether a work location is on
            # file; without them the location screen can never confirm a save.
            'latitude', 'longitude',
        ]
        read_only_fields = ['verification_status', 'categories', 'latitude', 'longitude']


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

    def to_internal_value(self, data):
        # A multipart body cannot repeat a field key, so the app sends the
        # chosen categories as one comma-separated value. Expand it back into
        # the list that the many=True field expects.
        raw = data.get('categories')
        if isinstance(raw, str):
            # Shallow copy into a plain dict. QueryDict.copy() deep-copies its
            # values, and an upload big enough to be spooled to disk carries an
            # open file handle that cannot be copied.
            data = dict(data.items())
            data['categories'] = [c for c in raw.split(',') if c.strip()]
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
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError(
                "An account already exists for this phone number."
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
            # Set explicitly rather than trusting the model default: a
            # self-registered vendor must never start out verified.
            verification_status=Vendor.VerificationStatus.PENDING,
        )
        vendor.categories.set(categories)

        VendorDocument.objects.bulk_create([
            VendorDocument(vendor=vendor, doc_type=doc_type, file=f)
            for doc_type, f in documents.items() if f
        ])

        return vendor


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

    class Meta:
        model = Vendor
        fields = [
            'id', 'name', 'pro_title', 'pro_tagline', 'photo',
            'experience_years', 'average_rating', 'total_reviews',
            'categories', 'service_area',
        ]

    def get_photo(self, obj):
        return _absolute(self, obj.pro_photo)

    def get_categories(self, obj):
        return obj.coverage_labels


class ProVendorServiceSerializer(serializers.ModelSerializer):
    """A service a pro can be booked for, with everything the app needs to
    open its detail screen without another round trip."""
    category_name = serializers.CharField(source='category.name', read_only=True)
    subcategory_name = serializers.CharField(
        source='subcategory.name', read_only=True, default=None
    )
    image = serializers.SerializerMethodField()

    class Meta:
        from services.models import Service
        model = Service
        fields = [
            'id', 'name', 'description', 'image', 'price', 'duration_minutes',
            'category', 'category_name', 'subcategory', 'subcategory_name',
        ]

    def get_image(self, obj):
        return _absolute(self, obj.image)


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
