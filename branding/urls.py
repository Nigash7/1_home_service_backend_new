from django.urls import path
from .views import AppBrandingView

urlpatterns = [
    path('<str:app>/', AppBrandingView.as_view(), name='app-branding'),
]
