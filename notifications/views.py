from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeviceToken, Notification, NotificationPreference
from .resolvers import resolve_recipient
from .serializers import (
    DeviceTokenSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
)
from .services import mark_all_read, queryset_for, unread_count


class _RecipientView(APIView):
    """Base view that resolves the customer/vendor behind the token."""

    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.recipient_type, self.recipient = resolve_recipient(request)

    @property
    def _no_profile(self):
        return Response(
            {"detail": "No customer or vendor profile linked to this account."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def _owner_field(self):
        return {"CUSTOMER": "customer", "VENDOR": "vendor", "ADMIN": "admin_user"}[
            self.recipient_type
        ]


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class NotificationListView(_RecipientView):
    """GET /api/notifications/?unread=true&category=BOOKING&page=1"""

    def get(self, request):
        if not self.recipient:
            return self._no_profile

        qs = queryset_for(self.recipient_type, self.recipient)
        if request.query_params.get("unread") in ("1", "true", "True"):
            qs = qs.filter(is_read=False)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category.upper())

        paginator = NotificationPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = NotificationSerializer(page, many=True).data
        response = paginator.get_paginated_response(data)
        response.data["unread_count"] = unread_count(
            self.recipient_type, self.recipient
        )
        return response


class UnreadCountView(_RecipientView):
    """GET /api/notifications/unread-count/ — cheap, poll this for the badge."""

    def get(self, request):
        if not self.recipient:
            return Response({"unread_count": 0})
        return Response(
            {"unread_count": unread_count(self.recipient_type, self.recipient)}
        )


class MarkReadView(_RecipientView):
    """POST /api/notifications/<pk>/read/"""

    def post(self, request, pk):
        if not self.recipient:
            return self._no_profile
        note = queryset_for(self.recipient_type, self.recipient).filter(pk=pk).first()
        if not note:
            return Response({"detail": "Not found."}, status=404)
        note.mark_read()
        return Response(NotificationSerializer(note).data)


class MarkAllReadView(_RecipientView):
    """POST /api/notifications/read-all/"""

    def post(self, request):
        if not self.recipient:
            return self._no_profile
        updated = mark_all_read(self.recipient_type, self.recipient)
        return Response({"success": True, "updated": updated, "unread_count": 0})


class DeleteNotificationView(_RecipientView):
    """DELETE /api/notifications/<pk>/"""

    def delete(self, request, pk):
        if not self.recipient:
            return self._no_profile
        deleted, _ = (
            queryset_for(self.recipient_type, self.recipient).filter(pk=pk).delete()
        )
        return Response({"success": bool(deleted)}, status=200 if deleted else 404)


class ClearAllView(_RecipientView):
    """DELETE /api/notifications/clear/"""

    def delete(self, request):
        if not self.recipient:
            return self._no_profile
        deleted, _ = queryset_for(self.recipient_type, self.recipient).delete()
        return Response({"success": True, "deleted": deleted})


class DeviceTokenView(_RecipientView):
    """
    POST   /api/notifications/devices/   register or refresh an FCM token
    DELETE /api/notifications/devices/   unregister on logout  {"token": "..."}
    """

    def post(self, request):
        if not self.recipient:
            return self._no_profile
        serializer = DeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        defaults = {
            "recipient_type": self.recipient_type,
            "platform": payload.get("platform", "ANDROID"),
            "device_id": payload.get("device_id", ""),
            "app_version": payload.get("app_version", ""),
            "is_active": True,
            "last_seen_at": timezone.now(),
            "customer": None,
            "vendor": None,
            "admin_user": None,
        }
        defaults[self._owner_field()] = self.recipient

        obj, created = DeviceToken.objects.update_or_create(
            token=payload["token"], defaults=defaults
        )
        return Response(
            {"success": True, "created": created},
            status=201 if created else 200,
        )

    def delete(self, request):
        token = request.data.get("token") or request.query_params.get("token")
        if not token:
            return Response({"detail": "token is required."}, status=400)
        DeviceToken.objects.filter(token=token).update(is_active=False)
        return Response({"success": True})


class PreferenceView(_RecipientView):
    """
    GET   /api/notifications/preferences/
    PATCH /api/notifications/preferences/
    """

    def _get_or_create(self):
        lookup = {"recipient_type": self.recipient_type,
                  self._owner_field(): self.recipient}
        obj = NotificationPreference.objects.filter(**lookup).first()
        if obj is None:
            obj = NotificationPreference.objects.create(**lookup)
        return obj

    def get(self, request):
        if not self.recipient:
            return self._no_profile
        return Response(NotificationPreferenceSerializer(self._get_or_create()).data)

    def patch(self, request):
        if not self.recipient:
            return self._no_profile
        serializer = NotificationPreferenceSerializer(
            self._get_or_create(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)