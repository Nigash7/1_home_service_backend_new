from rest_framework import serializers
from .models import AppBranding


class AppBrandingSerializer(serializers.ModelSerializer):
    logo = serializers.SerializerMethodField()

    class Meta:
        model = AppBranding
        fields = ['app', 'logo', 'app_name', 'tagline', 'updated_at']

    def get_logo(self, obj):
        if obj.logo and hasattr(obj.logo, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None
