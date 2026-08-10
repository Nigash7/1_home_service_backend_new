from django.contrib import admin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'user__first_name', 'user__last_name', 'address', 'created_at', 'state', 'district', 'pincode', 'latitude', 'longitude')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'address', 'state', 'district', 'pincode')
