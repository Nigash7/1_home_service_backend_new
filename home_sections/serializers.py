from rest_framework import serializers
from services.serializers import ServiceCardSerializer
from vendors.serializers import ProVendorCardSerializer
from .models import HomeSection, HomeSectionItem, ProVendorSection


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


class ProVendorSectionItemSerializer(serializers.BaseSerializer):
    """Unwraps a section item to its vendor and reuses the shared pro card."""

    def to_representation(self, instance):
        return ProVendorCardSerializer(instance.vendor, context=self.context).data


class ProVendorSectionSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()
    total_items = serializers.SerializerMethodField()

    class Meta:
        model = ProVendorSection
        fields = ['id', 'title', 'subtitle', 'home_display_limit', 'items', 'total_items']

    def _listed(self, obj):
        """
        Members still fit to show. Filtered in Python rather than with a
        queryset so the view's prefetch is not thrown away, and so a vendor
        un-flagged after being curated simply drops out of the row.
        """
        return [
            item for item in obj.items.all()
            if item.vendor.is_pro and item.vendor.verification_status == 'VERIFIED'
        ]

    def get_items(self, obj):
        listed = self._listed(obj)[:obj.home_display_limit]
        return ProVendorSectionItemSerializer(listed, many=True, context=self.context).data

    def get_total_items(self, obj):
        return len(self._listed(obj))
