from django.urls import path
from .views import (
    CustomerRegisterView,
    CustomerMeView,
    RecentlyViewedView,
    BookAgainView,
)

urlpatterns = [
    path('register/', CustomerRegisterView.as_view(), name='customer-register'),
    path('me/', CustomerMeView.as_view(), name='customer-me'),
    path('recently-viewed/', RecentlyViewedView.as_view(), name='customer-recently-viewed'),
    path('book-again/', BookAgainView.as_view(), name='customer-book-again'),
]
