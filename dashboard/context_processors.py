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
