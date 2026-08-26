from rest_framework import generics, permissions
from .models import HomeSection
from .serializers import HomeSectionSerializer
from rest_framework.response import Response


class HomeSectionListView(generics.ListAPIView):
    serializer_class = HomeSectionSerializer
    permission_classes = [permissions.AllowAny]
    queryset = HomeSection.objects.filter(is_active=True).prefetch_related(
        'items__service__category', 'items__service__subcategory'
    )

from rest_framework.generics import RetrieveAPIView


class HomeSectionDetailView(RetrieveAPIView):
    """
    GET /api/home/sections/<id>/full/
    Returns all items in a section (for the See All page).
    """
    permission_classes = [permissions.AllowAny]
    queryset = HomeSection.objects.filter(is_active=True)

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        active_items = obj.items.filter(service__is_active=True)

        from .serializers import HomeSectionItemSerializer
        items_data = HomeSectionItemSerializer(
            active_items, many=True, context={'request': request}
        ).data

        return Response({
            'id': obj.id,
            'title': obj.title,
            'subtitle': obj.subtitle,
            'items': items_data,
        })

# ---------------------------------------------------------------------------
# Pro Vendor sections — same shape as the service sections above, but the
# items are admin-curated Pro Vendors instead of services.
# ---------------------------------------------------------------------------

from django.db.models import Prefetch
from vendors.models import Vendor
from vendors.serializers import ProVendorCardSerializer
from .models import ProVendorSection, ProVendorSectionItem
from .serializers import ProVendorSectionSerializer


def _pro_vendor_sections():
    """
    Active sections with their members loaded in one go. The nested vendor is
    prefetched through its own annotated queryset so every card can show a
    rating without a query per vendor.
    """
    vendors = (
        Vendor.objects.select_related('user')
        .prefetch_related('categories')
        .with_review_stats()
    )
    return ProVendorSection.objects.filter(is_active=True).prefetch_related(
        Prefetch('items', queryset=ProVendorSectionItem.objects.order_by('sort_order')),
        Prefetch('items__vendor', queryset=vendors),
    )


class ProVendorSectionListView(generics.ListAPIView):
    """GET /api/home/pro-vendor-sections/"""
    serializer_class = ProVendorSectionSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return _pro_vendor_sections()


class ProVendorSectionDetailView(RetrieveAPIView):
    """
    GET /api/home/pro-vendor-sections/<id>/full/
    Every member of the section, for the See All page.
    """
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return _pro_vendor_sections()

    def retrieve(self, request, *args, **kwargs):
        section = self.get_object()
        listed = [
            item.vendor for item in section.items.all()
            if item.vendor.is_pro and item.vendor.verification_status == 'VERIFIED'
        ]

        return Response({
            'id': section.id,
            'title': section.title,
            'subtitle': section.subtitle,
            'items': ProVendorCardSerializer(
                listed, many=True, context={'request': request}
            ).data,
        })
