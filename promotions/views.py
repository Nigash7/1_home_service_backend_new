from rest_framework import generics, permissions
from .models import SpotlightBanner
from .serializers import SpotlightBannerSerializer


class SpotlightBannerListView(generics.ListAPIView):
    """
    GET /api/promotions/spotlights/
    Public list of active spotlight banners for the home screen.
    """
    serializer_class = SpotlightBannerSerializer
    permission_classes = [permissions.AllowAny]
    queryset = SpotlightBanner.objects.filter(is_active=True)