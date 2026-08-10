from django import forms
from django.contrib import admin
from django.utils import timezone
from django.db.models import Sum
from vendors.models import Vendor
from .models import Booking, JobStartPhoto


class BookingAdminForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance and instance.category_id:
            self.fields['vendor'].queryset = Vendor.objects.filter(
                verification_status=Vendor.VerificationStatus.VERIFIED,
                is_available=True,
                categories=instance.category,
            )
        else:
            self.fields['vendor'].queryset = Vendor.objects.filter(
                verification_status=Vendor.VerificationStatus.VERIFIED,
                is_available=True,
            )


class JobStartPhotoInline(admin.StackedInline):
    model = JobStartPhoto
    extra = 0
    readonly_fields = ('image', 'latitude', 'longitude', 'captured_at')
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    form = BookingAdminForm
    list_display = (
        'id', 'customer', 'category', 'vendor', 'preferred_date', 'preferred_time',
        'status', 'amount', 'payment_status', 'has_location',
    )
    list_filter = ('status', 'payment_status', 'category', 'preferred_date')
    search_fields = ('customer__user__username', 'vendor__user__username', 'address_text')
    inlines = [JobStartPhotoInline]
    readonly_fields = ('created_at', 'assigned_at', 'completed_at')

    def has_location(self, obj):
        return bool(obj.location_lat and obj.location_lng)
    has_location.boolean = True
    has_location.short_description = "Pinned Location"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        return form

    def save_model(self, request, obj, form, change):
        if obj.vendor_id and obj.status == Booking.Status.PENDING:
            obj.status = Booking.Status.ASSIGNED
            obj.assigned_at = timezone.now()
        super().save_model(request, obj, form, change)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        qs = Booking.objects.filter(payment_status=Booking.PaymentStatus.PAID)
        total_revenue = qs.aggregate(total=Sum('amount'))['total'] or 0

        per_vendor = (
            qs.filter(vendor__isnull=False)
            .values('vendor__user__username')
            .annotate(total=Sum('amount'))
            .order_by('-total')
        )
        extra_context['total_revenue'] = total_revenue
        extra_context['per_vendor_revenue'] = per_vendor
        return super().changelist_view(request, extra_context=extra_context)