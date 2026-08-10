from django.urls import path
from .views import HomeSectionListView,HomeSectionDetailView

urlpatterns = [
    path('sections/', HomeSectionListView.as_view(), name='home-section-list'),
    path('sections/<int:pk>/full/', HomeSectionDetailView.as_view(), name='home-section-detail'),
]