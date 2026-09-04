"""
Delivery of the email verification code.

Which mailbox it actually reaches is decided by EMAIL_BACKEND in
settings/.env, exactly like every other Django mail:

  console  -> FREE. Prints the whole message to the terminal. Dev default.
  smtp     -> Real mail (needs EMAIL_HOST_USER / EMAIL_HOST_PASSWORD in .env)

Nothing here needs changing to go live -- flip EMAIL_BACKEND in .env.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

SUBJECT = "Your Make My House verification code"

_TEXT_BODY = """Hi{name},

Your verification code is {code}

It expires in {minutes} minutes. Enter it in the app to confirm this email
address belongs to you.

If you did not ask to verify this address, you can ignore this email --
nothing has changed on your account.

-- Make My House
"""

_HTML_BODY = """\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:0 auto;color:#1A1A2E">
  <p style="font-size:15px">Hi{name},</p>
  <p style="font-size:15px">Use this code to confirm your email address:</p>
  <p style="font-size:34px;font-weight:bold;letter-spacing:10px;color:#7C4DFF;margin:24px 0">{code}</p>
  <p style="font-size:14px;color:#8A8A9E">
    The code expires in {minutes} minutes. If you did not ask to verify this
    address, you can ignore this email &mdash; nothing has changed on your account.
  </p>
  <p style="font-size:13px;color:#8A8A9E">&mdash; Make My House</p>
</div>
"""


def send_email_otp(email: str, code: str, first_name: str = '') -> None:
    """
    Sends the code and lets any delivery failure propagate. The caller turns
    that into a visible error rather than telling the customer to check an
    inbox nothing was ever sent to.
    """
    minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 5)
    name = f" {first_name}" if first_name else ""

    message = EmailMultiAlternatives(
        subject=SUBJECT,
        body=_TEXT_BODY.format(name=name, code=code, minutes=minutes),
        from_email=settings.DEFAULT_FROM_EMAIL or None,
        to=[email],
    )
    message.attach_alternative(
        _HTML_BODY.format(name=name, code=code, minutes=minutes), "text/html"
    )
    message.send(fail_silently=False)
    logger.info("Email OTP sent to %s", email)
