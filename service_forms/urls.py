from django.urls import path
from .views import ServiceFormDetailView, FormByServiceView, FormSubmissionCreateView

urlpatterns = [
    path('<int:pk>/', ServiceFormDetailView.as_view(), name='form-detail'),
    path('by-service/', FormByServiceView.as_view(), name='form-by-service'),
    path('submit/', FormSubmissionCreateView.as_view(), name='form-submit'),
]