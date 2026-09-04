from maps.models import MapSettings


def admin_user(request):
    """
    Puts the signed-in dashboard user and what they can reach into every
    template, so the sidebar can hide links the user would only be refused at.

    Both are set by `dashboard.decorators.admin_login_required`; on the sign-in
    page they are simply absent.
    """
    return {
        'admin_user': getattr(request, 'admin_user', None),
        'admin_profile': getattr(request, 'admin_profile', None),
        'admin_perms': getattr(request, 'admin_perms', set()),
    }


def map_settings(request):
    """
    Which map this dashboard draws, for the pages that draw one.

    A context processor rather than per-view context because two unrelated
    pages need it -- the assignment centre's Vendors Map and the vendor form's
    location picker -- and a third would otherwise be one more place to forget.

    Skipped for anyone not signed in: the login page draws no map, and there
    is no reason to touch the database, or hand out the Google key, before a
    session exists.
    """
    if getattr(request, 'admin_user', None) is None:
        return {}
    return {'map_settings': MapSettings.get_solo()}
