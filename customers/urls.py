from django.urls import path
from .views import CustomerRegisterView, CustomerMeView

urlpatterns = [
    path('register/', CustomerRegisterView.as_view(), name='customer-register'),
    path('me/', CustomerMeView.as_view(), name='customer-me'),
]
