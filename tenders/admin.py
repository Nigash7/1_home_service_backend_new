from django.contrib import admin

from .models import (
    Tender,
    TenderAttachment,
    TenderBid,
    TenderConfirmationFee,
    TenderMilestone,
    TenderProgressPhoto,
    TenderProgressUpdate,
    TenderSettings,
)


class TenderAttachmentInline(admin.TabularInline):
    model = TenderAttachment
    extra = 0


class TenderBidInline(admin.TabularInline):
    model = TenderBid
    extra = 0
    readonly_fields = ('vendor', 'amount', 'timeline_days', 'status', 'created_at')
    can_delete = False


class TenderMilestoneInline(admin.TabularInline):
    model = TenderMilestone
    extra = 0


class TenderProgressPhotoInline(admin.TabularInline):
    model = TenderProgressPhoto
    extra = 0


@admin.register(Tender)
class TenderAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'customer', 'category', 'expected_budget',
                    'status', 'bid_count', 'created_at')
    list_filter = ('status', 'project_type', 'payment_status', 'category')
    search_fields = ('title', 'description', 'address_pincode',
                     'customer__user__username', 'customer__user__first_name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_at', 'published_at',
                       'awarded_at', 'started_at', 'completed_at')
    inlines = [TenderAttachmentInline, TenderBidInline]

    @admin.display(description='Bids')
    def bid_count(self, obj):
        return obj.bids.count()


@admin.register(TenderBid)
class TenderBidAdmin(admin.ModelAdmin):
    list_display = ('id', 'tender', 'vendor', 'amount', 'timeline_days',
                    'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('tender__title', 'vendor__user__username')
    inlines = [TenderMilestoneInline]


@admin.register(TenderConfirmationFee)
class TenderConfirmationFeeAdmin(admin.ModelAdmin):
    list_display = ('id', 'tender', 'bid', 'percent', 'amount', 'status',
                    'created_at', 'paid_at')
    list_filter = ('status', 'is_live')
    search_fields = ('tender__title', 'razorpay_order_id', 'razorpay_payment_id')
    # Money the gateway told us about. Editing it here would mean the books
    # said one thing and Razorpay another.
    readonly_fields = ('tender', 'bid', 'percent', 'bid_amount', 'amount',
                       'razorpay_order_id', 'razorpay_payment_id',
                       'razorpay_signature', 'created_at', 'updated_at', 'paid_at')


@admin.register(TenderSettings)
class TenderSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_confirmation_fee_active', 'updated_at')


@admin.register(TenderProgressUpdate)
class TenderProgressUpdateAdmin(admin.ModelAdmin):
    list_display = ('id', 'tender', 'vendor', 'percent_complete', 'created_at')
    search_fields = ('tender__title', 'message')
    inlines = [TenderProgressPhotoInline]
