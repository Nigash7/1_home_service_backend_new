"""
Brute-force protection for the dashboard sign-in.

The rule is: count the failed attempts that have piled up since the last
successful sign-in, and refuse to look at a password at all once there are too
many. Every extra batch of failures buys the attacker a longer wait, so
guessing a password at any useful rate stops being possible after a handful of
tries -- while a real admin who mistyped twice is never inconvenienced.

Two keys are tracked independently:

  username -- stops someone hammering one account.
  IP       -- stops someone spraying one password across many usernames, which
              never trips a single username's counter.

Failures are counted from `AdminLoginAttempt` rather than a counter column, so
the lockout and the audit log an admin reads can never disagree with each
other, and unlocking is just "stop counting these" rather than a delete.

Nothing here stores a password, a password length, or any part of one.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import AdminLoginAttempt


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: How far back failures are counted. Longer than the longest lockout, so a
#: patient attacker climbs the tiers instead of resetting to zero each time.
FAILURE_WINDOW = timedelta(hours=24)

#: (failures needed, how long the lock lasts), strictest first.
USERNAME_TIERS = [
    (20, timedelta(hours=24)),
    (10, timedelta(hours=1)),
    (5, timedelta(minutes=15)),
]

#: An office shares one IP, so this has to sit well above one person fumbling
#: a password. It is aimed at spraying, not at a single wrong login.
IP_TIERS = [
    (60, timedelta(hours=24)),
    (40, timedelta(hours=1)),
    (20, timedelta(minutes=15)),
]

USERNAME_THRESHOLD = USERNAME_TIERS[-1][0]
IP_THRESHOLD = IP_TIERS[-1][0]

#: Outcomes that count as a failed guess. A blocked attempt is deliberately
#: not one of them -- otherwise anyone could keep a real admin locked out
#: forever just by hammering the form.
FAILURE_OUTCOMES = (
    AdminLoginAttempt.Outcome.BAD_PASSWORD,
    AdminLoginAttempt.Outcome.UNKNOWN_USER,
    AdminLoginAttempt.Outcome.NO_ACCESS,
)

SCOPE_USERNAME = 'username'
SCOPE_IP = 'ip'


class LockStatus:
    """Whether a sign-in is currently refused, and until when."""

    def __init__(self, locked=False, until=None, scope=None, failures=0):
        self.locked = locked
        self.until = until
        self.scope = scope
        self.failures = failures

    def __bool__(self):
        return self.locked

    @property
    def seconds_left(self):
        if not self.until:
            return 0
        return max(0, int((self.until - timezone.now()).total_seconds()))

    @property
    def wait_text(self):
        """A rounded-up wait, so the message never says 'try again in 0'."""
        seconds = self.seconds_left
        if seconds >= 3600:
            hours = -(-seconds // 3600)
            return f'{hours} hour' + ('s' if hours != 1 else '')
        minutes = max(1, -(-seconds // 60))
        return f'{minutes} minute' + ('s' if minutes != 1 else '')


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def client_ip(request):
    """
    The caller's address, reading X-Forwarded-For when we sit behind a proxy.

    On a platform like Render every request arrives from the load balancer, so
    without this the IP counter would see one address for the whole world and
    lock everybody out at once. The header is client-supplied and therefore
    spoofable -- which only lets an attacker dodge the IP counter, never the
    username one, and the username counter is the one that actually guards a
    password.
    """
    if getattr(settings, 'ADMIN_LOGIN_TRUST_PROXY_HEADER', True):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            candidate = forwarded.split(',')[0].strip()
            if candidate:
                return candidate[:45]
    return request.META.get('REMOTE_ADDR') or None


def _user_agent(request):
    return request.META.get('HTTP_USER_AGENT', '')[:255]


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def _attempts_for(scope, key):
    field = 'username' if scope == SCOPE_USERNAME else 'ip_address'
    return AdminLoginAttempt.objects.filter(**{field: key})


def _failure_state(scope, key):
    """
    (failure count, time of the latest failure) for one key.

    Only failures newer than the last success count, so signing in
    successfully wipes the slate without touching the log.
    """
    if not key:
        return 0, None

    since = timezone.now() - FAILURE_WINDOW
    attempts = _attempts_for(scope, key).filter(created_at__gte=since)

    last_success = (
        attempts.filter(outcome=AdminLoginAttempt.Outcome.SUCCESS)
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    if last_success:
        attempts = attempts.filter(created_at__gt=last_success)

    failures = attempts.filter(outcome__in=FAILURE_OUTCOMES, cleared=False)
    latest = failures.order_by('-created_at').values_list('created_at', flat=True).first()
    return failures.count(), latest


def _lock_for(scope, key, tiers):
    count, latest = _failure_state(scope, key)
    if not latest:
        return LockStatus(failures=count)

    for threshold, duration in tiers:
        if count >= threshold:
            until = latest + duration
            if timezone.now() < until:
                return LockStatus(True, until, scope, count)
            # The tier is met but its wait is already served.
            return LockStatus(failures=count)
    return LockStatus(failures=count)


def lock_status(username, ip):
    """
    Is this sign-in refused right now?

    The username lock is reported first: it is the one a real admin will hit,
    and it is the one an admin can clear from the security page.
    """
    by_username = _lock_for(SCOPE_USERNAME, (username or '').strip(), USERNAME_TIERS)
    if by_username.locked:
        return by_username

    by_ip = _lock_for(SCOPE_IP, ip, IP_TIERS)
    if by_ip.locked:
        return by_ip

    return LockStatus(failures=by_username.failures)


def attempts_left(username):
    """How many more tries before this username locks. For the warning line."""
    count, _latest = _failure_state(SCOPE_USERNAME, (username or '').strip())
    return max(0, USERNAME_THRESHOLD - count)


# ---------------------------------------------------------------------------
# Recording and clearing
# ---------------------------------------------------------------------------

def record_attempt(request, username, outcome):
    return AdminLoginAttempt.objects.create(
        username=(username or '')[:150],
        ip_address=client_ip(request),
        user_agent=_user_agent(request),
        outcome=outcome,
    )


def clear_failures(scope, key):
    """
    Unlock a username or an IP.

    The attempts stay in the log, marked so they no longer count -- an admin
    investigating later still sees that the guessing happened.
    """
    return _attempts_for(scope, key).filter(
        outcome__in=FAILURE_OUTCOMES, cleared=False,
    ).update(cleared=True)


def locked_out():
    """
    Everything currently locked, for the security page.

    Only keys with recent uncleared failures are examined, so this stays a
    handful of rows however big the log gets.
    """
    since = timezone.now() - FAILURE_WINDOW
    recent = AdminLoginAttempt.objects.filter(
        created_at__gte=since, outcome__in=FAILURE_OUTCOMES, cleared=False,
    )

    locks = []
    for username in set(recent.values_list('username', flat=True)):
        status = _lock_for(SCOPE_USERNAME, username, USERNAME_TIERS)
        if status.locked:
            locks.append({'scope': SCOPE_USERNAME, 'key': username, 'status': status})

    for ip in set(recent.values_list('ip_address', flat=True)):
        if not ip:
            continue
        status = _lock_for(SCOPE_IP, ip, IP_TIERS)
        if status.locked:
            locks.append({'scope': SCOPE_IP, 'key': ip, 'status': status})

    locks.sort(key=lambda item: item['status'].until, reverse=True)
    return locks
