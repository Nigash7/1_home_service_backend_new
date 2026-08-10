from django.urls import path
from .views import CurationSectionListView,CustomerRegisterView, CustomerMeView, MyNotificationsView, MarkNotificationsReadView

urlpatterns = [
    path('sections/', CurationSectionListView.as_view(), name='curation-section-list'),
    path('register/', CustomerRegisterView.as_view(), name='customer-register'),
    path('me/', CustomerMeView.as_view(), name='customer-me'),
    path('me/notifications/', MyNotificationsView.as_view(), name='my-notifications'),
    path('me/notifications/read/', MarkNotificationsReadView.as_view(), name='mark-notifications-read'),
]