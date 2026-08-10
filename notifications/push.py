"""
FCM HTTP v1 delivery.

The legacy FCM server-key API is dead, so this uses the v1 endpoint with a
service-account OAuth token. Requires:

    pip install google-auth requests

settings.py:
    FCM_ENABLED = True
    FCM_PROJECT_ID = "your-firebase-project-id"
    FCM_CREDENTIALS_FILE = BASE_DIR / "secrets" / "fcm-service-account.json"

If FCM_ENABLED is False the whole module no-ops and notifications are still
created in-app — you can build and test the entire feature without Firebase.
"""
import json
import logging
import threading

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

_credentials = None
_lock = threading.Lock()


def _enabled() -> bool:
    return bool(
        getattr(settings, "FCM_ENABLED", False)
        and getattr(settings, "FCM_PROJECT_ID", None)
        and getattr(settings, "FCM_CREDENTIALS_FILE", None)
    )


def _access_token():
    global _credentials
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    with _lock:
        if _credentials is None:
            _credentials = service_account.Credentials.from_service_account_file(
                str(settings.FCM_CREDENTIALS_FILE), scopes=[FCM_SCOPE]
            )
        if not _credentials.valid:
            _credentials.refresh(Request())
        return _credentials.token


def _active_tokens(notification):
    from .models import DeviceToken

    field = {
        "CUSTOMER": "customer",
        "VENDOR": "vendor",
        "ADMIN": "admin_user",
    }[notification.recipient_type]
    recipient = notification.recipient
    if recipient is None:
        return DeviceToken.objects.none()
    return DeviceToken.objects.filter(
        recipient_type=notification.recipient_type,
        is_active=True,
        **{field: recipient},
    )


def _send_one(token_obj, title, body, data, image_url=""):
    """Returns (ok: bool, error: str)."""
    import requests

    payload = {
        "message": {
            "token": token_obj.token,
            "notification": {"title": title, "body": body},
            # All data values MUST be strings for FCM.
            "data": {str(k): str(v) for k, v in (data or {}).items()},
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": getattr(settings, "FCM_ANDROID_CHANNEL", "default"),
                    "sound": "default",
                },
            },
            "apns": {
                "payload": {"aps": {"sound": "default", "badge": 1}},
            },
        }
    }
    if image_url:
        payload["message"]["notification"]["image"] = image_url

    try:
        resp = requests.post(
            FCM_ENDPOINT.format(project=settings.FCM_PROJECT_ID),
            headers={
                "Authorization": f"Bearer {_access_token()}",
                "Content-Type": "application/json; UTF-8",
            },
            data=json.dumps(payload),
            timeout=10,
        )
    except Exception as exc:
        return False, f"transport: {exc}"

    if resp.status_code == 200:
        return True, ""

    detail = resp.text[:400]
    # Stale/invalid tokens: stop retrying them forever.
    if resp.status_code in (400, 403, 404) and (
        "UNREGISTERED" in detail or "INVALID_ARGUMENT" in detail
    ):
        token_obj.deactivate()
        return False, f"token deactivated ({resp.status_code})"
    return False, f"HTTP {resp.status_code}: {detail}"


def _deliver(notification_id):
    from .models import Notification, PushStatus

    try:
        note = Notification.objects.get(pk=notification_id)
    except Notification.DoesNotExist:
        return

    tokens = list(_active_tokens(note))
    if not tokens:
        note.push_status = PushStatus.SKIPPED
        note.push_error = "No active device tokens"
        note.save(update_fields=["push_status", "push_error"])
        return

    data = dict(note.data or {})
    data.update(
        {
            "notification_id": note.pk,
            "event": note.event,
            "route": note.route or "",
            "booking_id": note.booking_id or "",
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
        }
    )

    errors, sent = [], 0
    for token_obj in tokens:
        ok, err = _send_one(token_obj, note.title, note.body, data, note.image_url)
        if ok:
            sent += 1
        else:
            errors.append(err)

    if sent:
        note.push_status = PushStatus.SENT
        note.push_sent_at = timezone.now()
    else:
        note.push_status = PushStatus.FAILED
    note.push_error = " | ".join(errors)[:1000]
    note.save(update_fields=["push_status", "push_sent_at", "push_error"])


def dispatch(notification):
    """
    Fire-and-forget push. Runs on a background thread so a slow FCM call never
    blocks the HTTP request that created the notification.

    When you add Celery later, swap the thread for `deliver_push.delay(pk)`.
    """
    from .models import PushStatus

    if not _enabled():
        notification.push_status = PushStatus.SKIPPED
        notification.push_error = "FCM disabled"
        notification.save(update_fields=["push_status", "push_error"])
        return

    thread = threading.Thread(
        target=_deliver, args=(notification.pk,), daemon=True
    )
    thread.start()