from django.urls import path
from .views import VendorMeView, VendorAvailabilityUpdateView, UpdateVendorLocationView

urlpatterns = [
    path('me/', VendorMeView.as_view(), name='vendor-me'),
    path('me/availability/', VendorAvailabilityUpdateView.as_view(), name='vendor-availability'),
     path('update-location/', UpdateVendorLocationView.as_view(), name='vendor-update-location'),
]
