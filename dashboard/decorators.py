from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import get_user_model

User = get_user_model()


def admin_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        admin_user_id = request.session.get('admin_user_id')
        if not admin_user_id:
            messages.error(request, 'Please log in to continue.')
            return redirect('dashboard_login')

        try:
            admin_user = User.objects.get(id=admin_user_id, is_staff=True)
        except User.DoesNotExist:
            request.session.flush()
            messages.error(request, 'Session expired. Please log in again.')
            return redirect('dashboard_login')

        request.admin_user = admin_user
        return view_func(request, *args, **kwargs)
    return wrapper