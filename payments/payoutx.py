"""
RazorpayX — the API money is sent OUT through.

Separate from `gateway.py` on purpose. That one collects money into the
platform's account; this one moves it out again, which is the direction where
a mistake is expensive and hard to undo. The Python SDK covers only the
payment gateway, so these are plain REST calls.

Three entities, created in this order and then reused:

    Contact       the vendor, as a party we pay
    Fund account  their bank account, registered against that contact
    Payout        one transfer from our virtual account to a fund account
"""
import logging
import uuid

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = 'https://api.razorpay.com/v1'
TIMEOUT = 30


class PayoutError(Exception):
    """
    RazorpayX refused or could not be reached.

    `retriable` is False when RazorpayX gave a definite answer -- a bad
    account, insufficient balance -- and True when the outcome is genuinely
    unknown, such as a timeout. Retrying only the second kind is what keeps a
    retry from becoming a second payout.
    """

    def __init__(self, message, *, retriable=False, payload=None):
        super().__init__(message)
        self.retriable = retriable
        self.payload = payload or {}


def is_enabled():
    """Payouts are off until a virtual account number is configured."""
    return bool(
        settings.RAZORPAYX_ENABLED
        and settings.RAZORPAYX_KEY_ID
        and settings.RAZORPAYX_KEY_SECRET
        and settings.RAZORPAYX_ACCOUNT_NUMBER
    )


def new_idempotency_key():
    """
    One key per payout attempt, generated before the first call and reused on
    every retry of that same payout.

    This is the single most important thing in this module: without it, a
    timeout followed by a retry sends the money twice.
    """
    return f"payout_{uuid.uuid4().hex}"


def _auth():
    return (settings.RAZORPAYX_KEY_ID, settings.RAZORPAYX_KEY_SECRET)


def _request(method, path, *, json=None, headers=None, idempotency_key=None):
    if not is_enabled():
        raise PayoutError("Payouts are not configured.")

    request_headers = {'Content-Type': 'application/json'}
    if idempotency_key:
        request_headers['X-Payout-Idempotency'] = idempotency_key
    request_headers.update(headers or {})

    try:
        response = requests.request(
            method, f"{BASE_URL}{path}", json=json,
            headers=request_headers, auth=_auth(), timeout=TIMEOUT,
        )
    except requests.Timeout as exc:
        # The request may well have been received. Never treat this as a
        # failure that can be retried without the same idempotency key.
        raise PayoutError(
            "RazorpayX did not respond in time.", retriable=True
        ) from exc
    except requests.RequestException as exc:
        raise PayoutError(
            "Could not reach RazorpayX.", retriable=True
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = {}

    if response.status_code >= 400:
        error = (body.get('error') or {})
        message = error.get('description') or f"RazorpayX returned {response.status_code}."
        # 5xx is their side and safe to retry with the same key; 4xx is a
        # definite refusal that retrying will only repeat.
        raise PayoutError(
            message, retriable=response.status_code >= 500, payload=body,
        )

    return body


# ------------------------------------------------------------------ contacts

def create_contact(*, name, contact_type='vendor', reference_id='',
                   email='', phone=''):
    payload = {
        'name': name[:50],
        'type': contact_type,
        'reference_id': reference_id,
    }
    if email:
        payload['email'] = email
    if phone:
        payload['contact'] = phone
    return _request('POST', '/contacts', json=payload)


# ------------------------------------------------------------- fund accounts

def create_fund_account(*, contact_id, name, ifsc, account_number):
    """
    Register a bank account against a contact.

    RazorpayX stores these itself and returns an `fa_...` id. Every later
    payout and validation refers to that id rather than to the raw number,
    which keeps the account number out of subsequent calls.
    """
    return _request('POST', '/fund_accounts', json={
        'contact_id': contact_id,
        'account_type': 'bank_account',
        'bank_account': {
            'name': name[:120],
            'ifsc': ifsc,
            'account_number': account_number,
        },
    })


def validate_fund_account(*, fund_account_id, amount_paise=100, notes=None):
    """
    Penny drop: send a rupee and see whose name comes back.

    The reply carries `results.account_status` and, when the bank supports
    it, `results.registered_name` -- the name the bank has on the account.
    That name is the actual check; an account that merely exists is not
    evidence it belongs to this vendor.
    """
    return _request('POST', '/fund_accounts/validations', json={
        'account_number': settings.RAZORPAYX_ACCOUNT_NUMBER,
        'fund_account': {'id': fund_account_id},
        'amount': amount_paise,
        'currency': 'INR',
        'notes': notes or {},
    })


def fetch_validation(validation_id):
    return _request('GET', f'/fund_accounts/validations/{validation_id}')


# ------------------------------------------------------------------- payouts

def choose_mode(amount_rupees):
    """
    IMPS settles in minutes but banks cap it, so anything larger goes NEFT.

    Getting this wrong is not dangerous -- RazorpayX rejects an over-limit
    IMPS payout rather than sending it -- but it does mean a failed payout
    somebody has to chase.
    """
    if amount_rupees > settings.RAZORPAYX_IMPS_LIMIT:
        return 'NEFT'
    return settings.RAZORPAYX_PAYOUT_MODE


def create_payout(*, fund_account_id, amount_paise, idempotency_key,
                  mode='IMPS', purpose='vendor_payment', reference_id='',
                  narration='', notes=None):
    """
    Send money to a fund account.

    `queue_if_low_balance` is on: if the virtual account is short, RazorpayX
    holds the payout and releases it when funds arrive, rather than failing it
    outright and leaving a vendor unpaid with no record of why.
    """
    payload = {
        'account_number': settings.RAZORPAYX_ACCOUNT_NUMBER,
        'fund_account_id': fund_account_id,
        'amount': amount_paise,
        'currency': 'INR',
        'mode': mode,
        'purpose': purpose,
        'queue_if_low_balance': True,
        'notes': notes or {},
    }
    if reference_id:
        payload['reference_id'] = reference_id[:40]
    if narration:
        # What the vendor sees on their bank statement. Alphanumerics and
        # spaces only, 30 characters, or the bank rejects the transfer.
        payload['narration'] = narration[:30]

    return _request(
        'POST', '/payouts', json=payload, idempotency_key=idempotency_key,
    )


def fetch_payout(payout_id):
    return _request('GET', f'/payouts/{payout_id}')
