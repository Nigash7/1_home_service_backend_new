from django.contrib import admin
from .models import Review


class RealReviewProxy(Review):
    class Meta:
        proxy = True
        verbose_name = 'Customer Review'
        verbose_name_plural = 'Customer Reviews'


class FakeReviewProxy(Review):
    class Meta:
        proxy = True
        verbose_name = 'Admin Review'
        verbose_name_plural = 'Admin Reviews (Fake)'


@admin.register(RealReviewProxy)
class RealReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'display_name', 'service_category', 'service', 'vendor', 'rating', 'created_at')
    list_filter = ('rating', 'service_category', 'vendor')
    search_fields = ('customer__user__first_name', 'comment')
    readonly_fields = ('booking', 'customer', 'vendor', 'service_category', 'service', 'rating', 'comment', 'created_at')

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_admin_created=False)

    def display_name(self, obj):
        if obj.customer:
            u = obj.customer.user
            return u.get_full_name() or u.username
        return 'Customer'
    display_name.short_description = 'Customer'

    def has_add_permission(self, request):
        return False


@admin.register(FakeReviewProxy)
class FakeReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'reviewer_name', 'service_category', 'service', 'rating', 'created_at')
    list_filter = ('rating', 'service_category', 'service')
    search_fields = ('reviewer_name', 'comment')
    autocomplete_fields = ('service_category', 'service', 'vendor')

    fieldsets = (
        ('Review Content', {
            'fields': ('rating', 'comment', 'reviewer_name'),
        }),
        ('Link To', {
            'fields': ('service_category', 'service', 'vendor'),
            'description': 'Pick the service category and/or specific service this review is for.',
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_admin_created=True)

    def save_model(self, request, obj, form, change):
        obj.is_admin_created = True
        super().save_model(request, obj, form, change)

    def display_name(self, obj):
        return obj.reviewer_name or 'Anonymous'
    display_name.short_description = 'Reviewer'