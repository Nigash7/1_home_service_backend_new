from django.urls import path

from .views import (
    MySubscriptionView,
    SubscriptionPlanListView,
    UpgradeRequestListCreateView,
    UpgradeRequestWithdrawView,
)

urlpatterns = [
    path('plans/', SubscriptionPlanListView.as_view(), name='subscription-plan-list'),
    path('me/', MySubscriptionView.as_view(), name='vendor-my-subscription'),
    path(
        'upgrade-requests/',
        UpgradeRequestListCreateView.as_view(),
        name='subscription-upgrade-requests',
    ),
    path(
        'upgrade-requests/<int:pk>/withdraw/',
        UpgradeRequestWithdrawView.as_view(),
        name='subscription-upgrade-request-withdraw',
    ),
]
