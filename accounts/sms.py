"""
Pluggable SMS sending. Controlled by SMS_BACKEND in settings/.env:

  SMS_BACKEND=console   -> FREE. Just prints/logs the OTP. Use this while developing.
  SMS_BACKEND=fast2sms  -> Real SMS via Fast2SMS (needs FAST2SMS_API_KEY in .env)
  SMS_BACKEND=msg91     -> Real SMS via MSG91 (needs MSG91_AUTH_KEY, MSG91_SENDER_ID in .env)
  SMS_BACKEND=twilio    -> Real SMS via Twilio (needs TWILIO_* keys in .env)

To go live later: sign up for one of the real providers, put the API key in
.env, change SMS_BACKEND in .env -- NO CODE CHANGES NEEDED anywhere else.
"""
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_otp_sms(phone_number: str, code: str) -> None:
    backend = getattr(settings, 'SMS_BACKEND', 'console')

    if backend == 'console':
        _send_console(phone_number, code)
    elif backend == 'fast2sms':
        _send_fast2sms(phone_number, code)
    elif backend == 'msg91':
        _send_msg91(phone_number, code)
    elif backend == 'twilio':
        _send_twilio(phone_number, code)
    else:
        raise ValueError(f"Unknown SMS_BACKEND: {backend}")


def _send_console(phone_number: str, code: str) -> None:
    # FREE mode for development: no real SMS sent. The OTP is just printed
    # to your terminal (and Django's log) so you can test the full flow.
    print(f"\n{'='*50}\n[DEV SMS] OTP for {phone_number} is: {code}\n{'='*50}\n")
    logger.info(f"[console SMS backend] OTP for {phone_number}: {code}")


def _send_fast2sms(phone_number: str, code: str) -> None:
    import requests
    api_key = settings.FAST2SMS_API_KEY
    resp = requests.get(
        "https://www.fast2sms.com/dev/bulkV2",
        params={
            "authorization": api_key,
            "route": "otp",
            "variables_values": code,
            "flash": 0,
            "numbers": phone_number,
        },
        timeout=10,
    )
    resp.raise_for_status()


def _send_msg91(phone_number: str, code: str) -> None:
    import requests
    auth_key = settings.MSG91_AUTH_KEY
    sender_id = settings.MSG91_SENDER_ID
    message = f"Your Home Service verification code is {code}. Do not share this with anyone."
    resp = requests.post(
        "https://api.msg91.com/api/v5/flow/",
        headers={"authkey": auth_key, "content-type": "application/json"},
        json={
            "sender": sender_id,
            "route": "4",
            "mobiles": phone_number,
            "message": message,
        },
        timeout=10,
    )
    resp.raise_for_status()


def _send_twilio(phone_number: str, code: str) -> None:
    from twilio.rest import Client
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    client.messages.create(
        body=f"Your Home Service verification code is {code}.",
        from_=settings.TWILIO_FROM_NUMBER,
        to=f"+91{phone_number}" if not phone_number.startswith('+') else phone_number,
    )
