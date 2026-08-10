from django.urls import path
from .views import (
    ReviewCreateView,
    MyReviewsListView,
    VendorReviewsView,
    ServiceReviewsView,
    BookingReviewView,
    IndividualServiceReviewsView,


)

urlpatterns = [
    path('create/', ReviewCreateView.as_view(), name='review-create'),
    path('my/', MyReviewsListView.as_view(), name='my-reviews'),
    path('vendor/<int:vendor_id>/', VendorReviewsView.as_view(), name='vendor-reviews'),
    path('service/<int:category_id>/', ServiceReviewsView.as_view(), name='service-reviews'),
    path('booking/<int:booking_id>/', BookingReviewView.as_view(), name='booking-review'),
    path('individual-service/<int:service_id>/', IndividualServiceReviewsView.as_view(), name='individual-service-reviews'),
]