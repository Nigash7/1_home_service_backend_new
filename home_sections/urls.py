from django.urls import path
from .views import (
    HomeSectionListView,
    HomeSectionDetailView,
    ProVendorSectionListView,
    ProVendorSectionDetailView,
)

urlpatterns = [
    path('sections/', HomeSectionListView.as_view(), name='home-section-list'),
    path('sections/<int:pk>/full/', HomeSectionDetailView.as_view(), name='home-section-detail'),

    # Pro Vendor sections
    path(
        'pro-vendor-sections/',
        ProVendorSectionListView.as_view(),
        name='pro-vendor-section-list',
    ),
    path(
        'pro-vendor-sections/<int:pk>/full/',
        ProVendorSectionDetailView.as_view(),
        name='pro-vendor-section-detail',
    ),
]
