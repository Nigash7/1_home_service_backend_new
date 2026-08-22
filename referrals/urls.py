from django.urls import path
from .views import MyReferralInfoView, MyReferralListView

urlpatterns = [
    path('me/', MyReferralInfoView.as_view(), name='my-referral-info'),
    path('my-referrals/', MyReferralListView.as_view(), name='my-referral-list'),
]
