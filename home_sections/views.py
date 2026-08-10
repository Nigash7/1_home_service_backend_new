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