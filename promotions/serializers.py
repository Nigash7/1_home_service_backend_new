from rest_framework import serializers
from .models import SpotlightBanner, HeaderBanner, PromoCard


class PromoCardSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)
    pro_vendor_name = serializers.CharField(
        source='pro_vendor.display_name', read_only=True, default=None
    )

    class Meta:
        model = PromoCard
        fields = [
            'id', 'image', 'badge_text', 'badge_color', 'title', 'subtitle', 'button_text',
            'category', 'subcategory', 'category_name', 'subcategory_name',
            'pro_vendor', 'pro_vendor_name',
            'placement', 'after_section',
        ]

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class HeaderBannerSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)
    pro_vendor_name = serializers.CharField(
        source='pro_vendor.display_name', read_only=True, default=None
    )

    class Meta:
        model = HeaderBanner
        fields = [
            'id', 'image', 'title', 'subtitle',
            'category', 'subcategory', 'category_name', 'subcategory_name',
            'pro_vendor', 'pro_vendor_name',
        ]

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class SpotlightBannerSerializer(serializers.ModelSerializer):
    background_image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)
    pro_vendor_name = serializers.CharField(
        source='pro_vendor.display_name', read_only=True, default=None
    )

    class Meta:
        model = SpotlightBanner
        fields = [
            'id', 'title', 'subtitle', 'background_image', 'button_text',
            'category', 'subcategory', 'category_name', 'subcategory_name',
            'pro_vendor', 'pro_vendor_name',
        ]

    def get_background_image(self, obj):
        if obj.background_image and hasattr(obj.background_image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.background_image.url)
            return obj.background_image.url
        return None