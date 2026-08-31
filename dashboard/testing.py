"""
Test helpers for signing in to the dashboard.

Dashboard access hangs off an `AdminProfile`, not off `is_staff` -- so a test
that only sets `session['admin_user_id']` is refused at the door. This is the
one place that knows how to arrange it, so tests do not each grow their own
copy of the setup.
"""

from .decorators import SESSION_USER_KEY
from .models import AdminProfile, AdminRole


def grant_dashboard_access(user, permissions=None, full_name=None):
    """
    Give `user` a dashboard login.

    With no `permissions` they become a super admin, which is what a test
    exercising some other feature wants: everything reachable, nothing about
    roles to arrange. Pass a list of codes to test a limited role instead.
    """
    role = None
    if permissions is not None:
        role = AdminRole.objects.create(
            name=f'Test role for {user.username}',
            permissions=list(permissions),
        )

    profile, _created = AdminProfile.objects.get_or_create(
        user=user,
        defaults={
            'full_name': full_name or user.get_full_name() or user.username,
            'role': role,
            'is_super_admin': permissions is None,
        },
    )
    return profile


def sign_in(client, user, permissions=None):
    """Put `client` into a signed-in dashboard session as `user`."""
    profile = grant_dashboard_access(user, permissions)

    session = client.session
    session[SESSION_USER_KEY] = user.id
    session.save()
    return profile
