from rest_framework import serializers
from .models import ServiceCategory, SubCategory, Service


class ServiceSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'image', 'price', 'duration_minutes', 'is_active']

    def get_image(self, obj):
        if obj.image and hasattr(obj.image, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


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