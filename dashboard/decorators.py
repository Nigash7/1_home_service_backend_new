"""
The one gate every dashboard view passes through.

`admin_login_required` does two jobs: it proves who is asking, and it decides
whether they may. The second half is driven by `permissions.URL_PERMISSIONS`
rather than a decorator argument, so permissions cannot drift away from the
views they guard -- and an unmapped URL is refused rather than waved through,
which means forgetting to classify a new page fails closed.
"""

from functools import wraps

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .models import AdminProfile
from .permissions import permission_for


SESSION_USER_KEY = 'admin_user_id'


def _sign_out(request, message):
    request.session.flush()
    messages.error(request, message)
    return redirect('dashboard_login')


def _load_profile(user_id):
    """
    The signed-in user's dashboard profile, or None.

    A super-user created with `createsuperuser` has no profile until someone
    makes one, so one is filled in on the spot -- otherwise the very account
    meant to bootstrap the panel would be the one account locked out of it.
    """
    try:
        return (
            AdminProfile.objects
            .select_related('user', 'role')
            .get(user_id=user_id)
        )
    except AdminProfile.DoesNotExist:
        pass

    from django.contrib.auth import get_user_model

    try:
        user = get_user_model().objects.get(id=user_id, is_superuser=True)
    except get_user_model().DoesNotExist:
        return None

    profile = AdminProfile.objects.create(
        user=user,
        full_name=user.get_full_name() or user.username,
        is_super_admin=True,
    )
    profile.user = user
    return profile


def admin_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user_id = request.session.get(SESSION_USER_KEY)
        if not user_id:
            return _sign_out(request, 'Please sign in to continue.')

        profile = _load_profile(user_id)
        if profile is None:
            return _sign_out(request, 'Session expired. Please sign in again.')

        if not profile.can_sign_in:
            # Covers an account switched off, and a role switched off or
            # emptied, while the person was already signed in.
            return _sign_out(
                request,
                'Your dashboard access has been changed. Contact an administrator.',
            )

        request.admin_profile = profile
        request.admin_user = profile.user
        request.admin_perms = profile.permission_codes()

        denied = _permission_denied(request)
        if denied is not None:
            return denied

        return view_func(request, *args, **kwargs)

    return wrapper


def _permission_denied(request):
    """None when the request may proceed, otherwise the page to show instead."""
    match = request.resolver_match
    url_name = match.url_name if match else None

    try:
        required = permission_for(url_name, request.method)
    except KeyError:
        # An unclassified URL. Only a super admin gets the benefit of the
        # doubt; everyone else is refused until it is added to the map.
        required = None if request.admin_profile.is_super_admin else '__unmapped__'

    if required is None or required in request.admin_perms:
        return None

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Reorder and toggle endpoints are called from JavaScript, which needs
        # a status it can read rather than a login page in a JSON parser.
        return JsonResponse(
            {'success': False, 'error': 'You do not have permission to do that.'},
            status=403,
        )

    if request.method == 'POST':
        messages.error(request, 'You do not have permission to do that.')
        return redirect('dashboard')

    return render(request, 'dashboard/no_access.html', {
        'admin_user': request.admin_user,
        'admin_profile': request.admin_profile,
        'required_permission': None if required == '__unmapped__' else required,
    }, status=403)


def has_permission(request, *codes):
    """
    Whether the signed-in user holds every one of `codes`.

    For branches inside a view that need more than the URL as a whole does --
    hiding an action button, say, on a page the user may otherwise read.
    """
    held = getattr(request, 'admin_perms', set())
    return all(code in held for code in codes)
