from rest_framework import serializers
from .models import SpotlightBanner


class SpotlightBannerSerializer(serializers.ModelSerializer):
    background_image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    subcategory_name = serializers.CharField(source='subcategory.name', read_only=True, default=None)

    class Meta:
        model = SpotlightBanner
        fields = [
            'id', 'title', 'subtitle', 'background_image', 'button_text',
            'category', 'subcategory', 'category_name', 'subcategory_name',
        ]

    def get_background_image(self, obj):
        if obj.background_image and hasattr(obj.background_image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.background_image.url)
            return obj.background_image.url
        return None