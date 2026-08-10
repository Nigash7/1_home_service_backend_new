from django.urls import path
from .views import ApplicableDiscountsView, ValidateCouponView

urlpatterns = [
    path('applicable/', ApplicableDiscountsView.as_view(), name='applicable-discounts'),
    path('coupon/', ValidateCouponView.as_view(), name='validate-coupon'),
]