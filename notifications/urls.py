from django.urls import path

from . import views

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="notification-list"),
    path("unread-count/", views.UnreadCountView.as_view(), name="notification-unread-count"),
    path("read-all/", views.MarkAllReadView.as_view(), name="notification-read-all"),
    path("clear/", views.ClearAllView.as_view(), name="notification-clear"),
    path("devices/", views.DeviceTokenView.as_view(), name="notification-devices"),
    path("preferences/", views.PreferenceView.as_view(), name="notification-preferences"),
    path("<int:pk>/read/", views.MarkReadView.as_view(), name="notification-read"),
    path("<int:pk>/", views.DeleteNotificationView.as_view(), name="notification-delete"),
]