from django.urls import path
from .views import (
    BookingCreateView, MyBookingsListView, AssignedBookingsListView,
    BookingStartPhotoUploadView, BookingCompleteView, BookingCancelView,
)

urlpatterns = [
    path('', BookingCreateView.as_view(), name='booking-create'),
    path('my/', MyBookingsListView.as_view(), name='booking-my-list'),
    path('assigned/', AssignedBookingsListView.as_view(), name='booking-assigned-list'),
    path('<int:pk>/start-photo/', BookingStartPhotoUploadView.as_view(), name='booking-start-photo'),
    path('<int:pk>/complete/', BookingCompleteView.as_view(), name='booking-complete'),
    path('<int:pk>/cancel/', BookingCancelView.as_view(), name='booking-cancel'),
]
