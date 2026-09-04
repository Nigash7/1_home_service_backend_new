from django.contrib import admin

from .models import Payment, Payout, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'razorpay_order_id', 'booking', 'amount', 'status',
        'payout_status', 'is_live', 'created_at',
    )
    list_filter = ('status', 'payout_status', 'is_live', 'currency')
    search_fields = ('razorpay_order_id', 'razorpay_payment_id', 'booking__id')
    readonly_fields = (
        'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature',
        'amount', 'currency', 'created_at', 'updated_at', 'captured_at',
        'released_at', 'is_live',
    )
    # Payments are a record of what a gateway did. Editing one by hand makes
    # our books disagree with Razorpay's, so the only writes are the actions.
    def has_add_permission(self, request):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'event_id', 'payment', 'processed', 'received_at')
    list_filter = ('event_type', 'processed')
    search_fields = ('event_id', 'payment__razorpay_order_id')
    readonly_fields = ('event_id', 'event_type', 'payload', 'payment',
                       'processed', 'error', 'received_at')

    def has_add_permission(self, request):
        return False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ('razorpay_payout_id', 'vendor', 'amount', 'mode',
                    'status', 'utr', 'is_live', 'created_at')
    list_filter = ('status', 'mode', 'is_live')
    search_fields = ('razorpay_payout_id', 'utr', 'payment__razorpay_order_id')
    readonly_fields = [f.name for f in Payout._meta.fields]

    # Payouts mirror what RazorpayX did. Editing one by hand makes our books
    # disagree with the bank, and there is no way to un-send money anyway.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

