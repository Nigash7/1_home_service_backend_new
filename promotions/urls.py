from django.urls import path
from .views import SpotlightBannerListView

urlpatterns = [
    path('spotlights/', SpotlightBannerListView.as_view(), name='spotlight-list'),
]