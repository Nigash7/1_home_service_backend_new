from django.urls import path

from .views import (
    BookingPaymentStatusView, CreateOrderView, MyPaymentsListView,
    RazorpayWebhookView, VerifyPaymentView,
)

urlpatterns = [
    path('order/', CreateOrderView.as_view(), name='payment-create-order'),
    path('verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('my/', MyPaymentsListView.as_view(), name='payment-my-list'),
    path('booking/<int:pk>/', BookingPaymentStatusView.as_view(), name='payment-booking-status'),
    path('webhook/razorpay/', RazorpayWebhookView.as_view(), name='payment-webhook-razorpay'),
]
