from django.urls import path
from .views import (
    VendorMeView,
    VendorAvailabilityUpdateView,
    UpdateVendorLocationView,
    VendorSignupView,
    ProVendorListView,
    ProVendorDetailView,
    RegionListView,
    ServiceAvailabilityView,
    StateListView,
)
from .bank_views import (
    VendorBankAccountView, VendorBankAccountHistoryView,
)

urlpatterns = [
    # Pro Vendors (public — read by the Customer app)
    path('pro/', ProVendorListView.as_view(), name='pro-vendor-list'),
    path('pro/<int:pk>/', ProVendorDetailView.as_view(), name='pro-vendor-detail'),

    # Where work can be had, and the state names every form spells the same
    # way. Both open — a guest asks the first one before signing in.
    path('availability/', ServiceAvailabilityView.as_view(), name='service-availability'),
    path('states/', StateListView.as_view(), name='vendor-states'),
    path('regions/', RegionListView.as_view(), name='vendor-regions'),

    path('signup/', VendorSignupView.as_view(), name='vendor-signup'),
    path('me/', VendorMeView.as_view(), name='vendor-me'),
    path('me/availability/', VendorAvailabilityUpdateView.as_view(), name='vendor-availability'),

    # Payout details -- always the caller's own, never addressed by id.
    path('me/bank-account/', VendorBankAccountView.as_view(), name='vendor-bank-account'),
    path('me/bank-account/history/', VendorBankAccountHistoryView.as_view(), name='vendor-bank-account-history'),
     path('update-location/', UpdateVendorLocationView.as_view(), name='vendor-update-location'),
]
