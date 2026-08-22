from django.urls import path
from .views import SpotlightBannerListView, HeaderBannerListView, PromoCardListView

urlpatterns = [
    path('spotlights/', SpotlightBannerListView.as_view(), name='spotlight-list'),
    path('header-banners/', HeaderBannerListView.as_view(), name='header-banner-list'),
    path('promo-cards/', PromoCardListView.as_view(), name='promo-card-list'),
]
