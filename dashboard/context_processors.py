def admin_user(request):
    return {
        'admin_user': getattr(request, 'admin_user', None)
    }