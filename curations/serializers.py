from rest_framework import serializers
from .models import CurationSection, CurationItem


class CurationItemSerializer(serializers.ModelSerializer):
    thumbnail = serializers.SerializerMethodField()
    video = serializers.SerializerMethodField()
    service_id = serializers.IntegerField(source='service.id', default=None)
    service_name = serializers.CharField(source='service.name', default=None)
    service_price = serializers.DecimalField(
        source='service.price', max_digits=10, decimal_places=2, default=None
    )
    service_description = serializers.CharField(source='service.description', default=None)
    service_image = serializers.SerializerMethodField()
    category_id = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    subcategory_id = serializers.SerializerMethodField()

    class Meta:
        model = CurationItem
        fields = [
            'id', 'title', 'thumbnail', 'video',
            'service_id', 'service_name', 'service_price',
            'service_description', 'service_image',
            'category_id', 'category_name', 'subcategory_id',
        ]

    def _build_url(self, file_field):
        if file_field and hasattr(file_field, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(file_field.url)
            return file_field.url
        return None

    def get_thumbnail(self, obj):
        return self._build_url(obj.thumbnail)

    def get_video(self, obj):
        return self._build_url(obj.video)

    def get_service_image(self, obj):
        if obj.service and obj.service.image:
            return self._build_url(obj.service.image)
        return None

    def get_category_id(self, obj):
        return obj.service.category_id if obj.service else None

    def get_category_name(self, obj):
        return obj.service.category.name if obj.service else None

    def get_subcategory_id(self, obj):
        return obj.service.subcategory_id if obj.service else None


class CurationSectionSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = CurationSection
        fields = ['id', 'title', 'subtitle', 'items']

    def get_items(self, obj):
        active = obj.items.filter(is_active=True).select_related(
            'service__category', 'service__subcategory'
        )
        return CurationItemSerializer(active, many=True, context=self.context).data