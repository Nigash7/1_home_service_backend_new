from rest_framework import generics, permissions
from .models import ServiceCategory
from .serializers import ServiceCategorySerializer


class ServiceCategoryListView(generics.ListAPIView):
    """
    GET /api/services/categories/
    Public list of active service categories (Plumbing, Electrician, etc.)
    Used by the Customer app to populate the "choose a service" screen.
    """
    serializer_class = ServiceCategorySerializer
    permission_classes = [permissions.AllowAny]
    queryset = ServiceCategory.objects.filter(is_active=True)
