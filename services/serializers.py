from rest_framework import serializers
from .models import ServiceCategory, SubCategory, Service


class ServiceReviewStatsMixin:
    """
    The rating figures a service card shows, for any serializer that shows one.

    A service with no reviews of its own falls back to its category's, because
    a brand new service reading as unrated next to the category it belongs to
    says less than the category's own record does.
    """

    def _review_queryset(self, obj):
        from reviews.models import Review
        qs = Review.objects.filter(service=obj)
        if not qs.exists():
            # Fall back to category-level reviews.
            qs = Review.objects.filter(service_category=obj.category)
        return qs

    def get_average_rating(self, obj):
        from django.db.models import Avg
        avg = self._review_queryset(obj).aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0

    def get_total_reviews(self, obj):
        return self._review_queryset(obj).count()


class ServiceCardSerializer(ServiceReviewStatsMixin, serializers.ModelSerializer):
    """
    The payload behind every horizontal service card in the app — home
    sections, recently viewed, book again. One serializer so a card looks and
    prices the same wherever it appears.
    """
    service_id = serializers.IntegerField(source='id')
    image = serializers.SerializerMethodField()
    category_id = serializers.IntegerField()
    category_name = serializers.CharField(source='category.name')
    subcategory_id = serializers.IntegerField(allow_null=True)
    subcategory_name = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    total_reviews = serializers.SerializerMethodField()
    # Null on the types where it means nothing -- a per-hour service is as
    # long as the customer books it for. The apps already skip a null
    # duration, so this is what hides the "60 mins" chip on those.
    duration_minutes = serializers.SerializerMethodField()
    discount_info = serializers.SerializerMethodField()
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
        model = Service
        fields = [
            'service_id', 'name', 'description', 'price', 'duration_minutes',
            'image', 'category_id', 'category_name', 'subcategory_id', 'subcategory_name',
            'average_rating', 'total_reviews', 'discount_info',
            'pricing_type', 'price_label', 'unit_label', 'measure_label',
            'needs_quantity', 'allows_decimal_quantity', 'is_quote_only',
            # What the tender form opens with when a quote service sends
            # the customer there.
            'tender_project_type',
        ]

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_subcategory_name(self, obj):
        return obj.subcategory.name if obj.subcategory else None

    def get_duration_minutes(self, obj):
        return obj.duration_minutes if obj.shows_duration else None

    def get_discount_info(self, obj):
        from decimal import Decimal
        from django.db import models as db_models
        from django.utils import timezone
        from discounts.models import Discount

        now = timezone.now()
        discounts = Discount.objects.filter(
            is_active=True,
            valid_from__lte=now,
        ).filter(
            db_models.Q(valid_until__gte=now) | db_models.Q(valid_until__isnull=True)
        )

        matching = []
        for d in discounts:
            if d.service_id == obj.id:
                matching.append(d)
            elif d.subcategory_id and d.subcategory_id == obj.subcategory_id:
                matching.append(d)
            elif d.category_id and d.category_id == obj.category_id:
                matching.append(d)
            elif not d.service and not d.subcategory and not d.category:
                matching.append(d)

        if not matching:
            return None

        best_amount = Decimal('0')
        best = None
        price = Decimal(str(obj.price))

        for d in matching:
            if d.discount_type == 'PERCENTAGE':
                amount = (price * Decimal(str(d.value))) / Decimal('100')
                if d.max_discount:
                    amount = min(amount, Decimal(str(d.max_discount)))
            else:
                amount = Decimal(str(d.value))

            amount = min(amount, price)
            if amount > best_amount:
                best_amount = amount
                best = d

        if not best:
            return None

        return {
            'discount_amount': str(best_amount),
            'original_price': str(price),
            'final_price': str(price - best_amount),
            'discount_type': best.discount_type,
            'value': str(best.value),
        }


class ServiceSerializer(ServiceReviewStatsMixin, serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    # The same rating figures the flat card shows. A service row that says
    # nothing about how it has been rated is a row a customer cannot judge.
    average_rating = serializers.SerializerMethodField()
    total_reviews = serializers.SerializerMethodField()
    # Null on the types where it means nothing -- a per-hour service is as
    # long as the customer books it for. The apps already skip a null
    # duration, so this is what hides the "60 mins" chip on those.
    duration_minutes = serializers.SerializerMethodField()
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
        model = Service
        fields = [
            'id', 'name', 'description', 'image', 'price', 'duration_minutes',
            'is_active', 'average_rating', 'total_reviews',
            'pricing_type', 'price_label', 'unit_label', 'measure_label',
            'needs_quantity', 'allows_decimal_quantity', 'is_quote_only',
            # What the tender form opens with when a quote service sends
            # the customer there.
            'tender_project_type',
        ]

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


    def get_duration_minutes(self, obj):
        return obj.duration_minutes if obj.shows_duration else None


class SubCategorySerializer(serializers.ModelSerializer):
    icon = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()

    class Meta:
        model = SubCategory
        fields = ['id', 'name', 'description', 'icon', 'base_price', 'is_active', 'services']

    def get_icon(self, obj):
        if obj.icon and hasattr(obj.icon, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None

    def get_services(self, obj):
        active = obj.services.filter(is_active=True)
        return ServiceSerializer(active, many=True, context=self.context).data


class ServiceCategorySerializer(serializers.ModelSerializer):
    icon = serializers.SerializerMethodField()
    subcategories = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'description', 'icon', 'base_price', 'is_active', 'subcategories', 'services']

    def get_icon(self, obj):
        if obj.icon and hasattr(obj.icon, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None

    def get_subcategories(self, obj):
        active_subs = obj.subcategories.filter(is_active=True)
        return SubCategorySerializer(active_subs, many=True, context=self.context).data

    def get_services(self, obj):
        # Only return services that have NO subcategory (direct category services)
        active = obj.services.filter(is_active=True, subcategory__isnull=True)
        return ServiceSerializer(active, many=True, context=self.context).data