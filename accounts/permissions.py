from rest_framework.permissions import BasePermission
from .models import User


class IsCustomer(BasePermission):
    """Only allows users with role=CUSTOMER."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.CUSTOMER)


class IsVendor(BasePermission):
    """Only allows users with role=VENDOR."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == User.Role.VENDOR)
