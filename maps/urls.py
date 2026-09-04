from django.urls import path

from . import views

urlpatterns = [
    path('config/', views.map_config_view, name='map-config'),
    path('reverse-geocode/', views.reverse_geocode_view, name='map-reverse-geocode'),
]
