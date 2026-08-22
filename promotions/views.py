from django.db.models import Q
from rest_framework import generics, permissions
from .models import SpotlightBanner, HeaderBanner, PromoCard
from .serializers import (
    SpotlightBannerSerializer,
    HeaderBannerSerializer,
    PromoCardSerializer,
)


class PromoCardListView(generics.ListAPIView):
    """
    GET /api/promotions/promo-cards/
    Active promo cards for the home screen, each carrying the placement the
    app uses to slot it in around the home sections.
    """
    serializer_class = PromoCardSerializer
    permission_classes = [permissions.AllowAny]
    # A card pinned after a specific section is useless without that section,
    # so leave those out rather than have the app silently drop them.
    queryset = PromoCard.objects.filter(is_active=True).exclude(
        Q(placement=PromoCard.PLACEMENT_AFTER_SECTION) & Q(after_section__isnull=True)
    )


class HeaderBannerListView(generics.ListAPIView):
    """
    GET /api/promotions/header-banners/
    Public list of active carousel slides for the home screen hero header.
    """
    serializer_class = HeaderBannerSerializer
    permission_classes = [permissions.AllowAny]
    queryset = HeaderBanner.objects.filter(is_active=True)


class SpotlightBannerListView(generics.ListAPIView):
    """
    GET /api/promotions/spotlights/
    Public list of active spotlight banners for the home screen.
    """
    serializer_class = SpotlightBannerSerializer
    permission_classes = [permissions.AllowAny]
    queryset = SpotlightBanner.objects.filter(is_active=True)