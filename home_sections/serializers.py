from rest_framework import serializers
from services.serializers import ServiceCardSerializer
from .models import HomeSection, HomeSectionItem


class HomeSectionItemSerializer(serializers.BaseSerializer):
    """
    Unwraps the section item to its service and hands it to the shared card
    serializer, so a service card is built in exactly one place.
    """

    def to_representation(self, instance):
        return ServiceCardSerializer(instance.service, context=self.context).data



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
