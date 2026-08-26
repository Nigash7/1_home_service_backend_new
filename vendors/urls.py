from django.urls import path
from .views import (
    VendorMeView,
    VendorAvailabilityUpdateView,
    UpdateVendorLocationView,
    VendorSignupView,
    ProVendorListView,
    ProVendorDetailView,
)

urlpatterns = [
    # Pro Vendors (public — read by the Customer app)
    path('pro/', ProVendorListView.as_view(), name='pro-vendor-list'),
    path('pro/<int:pk>/', ProVendorDetailView.as_view(), name='pro-vendor-detail'),

    path('signup/', VendorSignupView.as_view(), name='vendor-signup'),
    path('me/', VendorMeView.as_view(), name='vendor-me'),
    path('me/availability/', VendorAvailabilityUpdateView.as_view(), name='vendor-availability'),
     path('update-location/', UpdateVendorLocationView.as_view(), name='vendor-update-location'),
]
