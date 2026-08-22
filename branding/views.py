from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AppBranding
from .serializers import AppBrandingSerializer


class AppBrandingView(APIView):
    """
    GET /api/branding/<app>/   where <app> is 'customer' or 'vendor'

    Public on purpose — the splash and login screens need it before anyone
    has signed in. Returns 404 when the admin has not uploaded a logo yet,
    which the apps read as "keep using the bundled one".
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, app):
        branding = AppBranding.objects.filter(app=app.upper()).first()
        if branding is None:
            return Response(
                {'detail': 'No branding set for this app.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            AppBrandingSerializer(branding, context={'request': request}).data
        )
