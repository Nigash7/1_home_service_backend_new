from django.db.models import Avg, Count
from rest_framework import serializers
from .models import HomeSection, HomeSectionItem
from django.db import models


class HomeSectionItemSerializer(serializers.ModelSerializer):
    service_id = serializers.IntegerField(source='service.id')
    name = serializers.CharField(source='service.name')
    description = serializers.CharField(source='service.description')
    price = serializers.DecimalField(source='service.price', max_digits=10, decimal_places=2)
    duration_minutes = serializers.IntegerField(source='service.duration_minutes')
    image = serializers.SerializerMethodField()
    category_id = serializers.IntegerField(source='service.category_id')
    category_name = serializers.CharField(source='service.category.name')
    subcategory_id = serializers.SerializerMethodField()
    subcategory_name = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    total_reviews = serializers.SerializerMethodField()
    discount_info = serializers.SerializerMethodField()

    class Meta:
        model = HomeSectionItem
        fields = [
            'service_id', 'name', 'description', 'price', 'duration_minutes',
            'image', 'category_id', 'category_name', 'subcategory_id', 'subcategory_name',
            'average_rating', 'total_reviews', 'discount_info',
        ]

    def get_image(self, obj):
        if obj.service.image and hasattr(obj.service.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.service.image.url)
            return obj.service.image.url
        return None

    def get_subcategory_id(self, obj):
        return obj.service.subcategory_id

    def get_subcategory_name(self, obj):
        if obj.service.subcategory:
            return obj.service.subcategory.name
        return None

    def get_average_rating(self, obj):
        from reviews.models import Review
        # Check service-specific reviews first
        qs = Review.objects.filter(service=obj.service)
        if not qs.exists():
            # Fall back to category-level
            qs = Review.objects.filter(service_category=obj.service.category)
        avg = qs.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0

    def get_total_reviews(self, obj):
        from reviews.models import Review
        qs = Review.objects.filter(service=obj.service)
        if not qs.exists():
            qs = Review.objects.filter(service_category=obj.service.category)
        return qs.count()
    def get_discount_info(self, obj):
        from discounts.models import Discount
        from decimal import Decimal
        from django.utils import timezone

        service = obj.service
        now = timezone.now()

        # Find applicable discount for this service
        discounts = Discount.objects.filter(
            is_active=True,
            valid_from__lte=now,
        ).filter(
            models.Q(valid_until__gte=now) | models.Q(valid_until__isnull=True)
        )

        # Filter to those matching this service
        matching = []
        for d in discounts:
            if d.service_id == service.id:
                matching.append(d)
            elif d.subcategory_id and d.subcategory_id == service.subcategory_id:
                matching.append(d)
            elif d.category_id and d.category_id == service.category_id:
                matching.append(d)
            elif not d.service and not d.subcategory and not d.category:
                matching.append(d)

        if not matching:
            return None

        # Pick best discount
        best_amount = Decimal('0')
        best = None
        price = Decimal(str(service.price))

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


class HomeSectionSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = HomeSection
        fields = ['id', 'title', 'subtitle', 'home_display_limit', 'items', 'total_items']

    def get_items(self, obj):
        # Only return the limited number for home page
        active_items = obj.items.filter(service__is_active=True)[:obj.home_display_limit]
        return HomeSectionItemSerializer(active_items, many=True, context=self.context).data

    def get_total_items(self, obj):
        return obj.items.filter(service__is_active=True).count()