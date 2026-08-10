from rest_framework import generics, permissions, status
from rest_framework.response import Response
from accounts.permissions import IsCustomer
from .models import ServiceForm, FormSubmission
from .serializers import ServiceFormSerializer, FormSubmissionCreateSerializer


class ServiceFormDetailView(generics.RetrieveAPIView):
    """
    GET /api/forms/<id>/
    Get a form with all its steps and options.
    """
    serializer_class = ServiceFormSerializer
    permission_classes = [permissions.AllowAny]
    queryset = ServiceForm.objects.filter(is_active=True).prefetch_related(
        'steps__options'
    )


class FormByServiceView(generics.ListAPIView):
    """
    GET /api/forms/by-service/?service_id=X
    GET /api/forms/by-service/?subcategory_id=X
    GET /api/forms/by-service/?category_id=X
    Check if a form exists for a service/subcategory/category.
    """
    serializer_class = ServiceFormSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = ServiceForm.objects.filter(is_active=True).prefetch_related('steps__options')
        service_id = self.request.query_params.get('service_id')
        subcategory_id = self.request.query_params.get('subcategory_id')
        category_id = self.request.query_params.get('category_id')

        if service_id:
            return qs.filter(service_id=service_id)
        if subcategory_id:
            return qs.filter(subcategory_id=subcategory_id)
        if category_id:
            return qs.filter(category_id=category_id)
        return qs.none()


class FormSubmissionCreateView(generics.CreateAPIView):
    """
    POST /api/forms/submit/
    Customer submits a filled form.
    """
    serializer_class = FormSubmissionCreateSerializer
    permission_classes = [IsCustomer]