from django.urls import path
from .otp_views import (
    SendOTPView,
    VerifyOTPView,
    SendEmailOTPView,
    VerifyEmailOTPView,
)

urlpatterns = [
    path('send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),

    # Email verification for a customer who is already signed in.
    path('email/send-otp/', SendEmailOTPView.as_view(), name='email-send-otp'),
    path('email/verify-otp/', VerifyEmailOTPView.as_view(), name='email-verify-otp'),
]
