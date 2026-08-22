from django.contrib import admin
from .models import SupportTicket, TicketMessage


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ('sender', 'message', 'created_at')


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'requester_name', 'raised_by', 'category', 'status', 'updated_at')
    list_filter = ('raised_by', 'status', 'category')
    search_fields = ('subject', 'customer__user__username', 'vendor__user__username')
    inlines = [TicketMessageInline]

    @admin.display(description='Raised by')
    def requester_name(self, obj):
        return obj.requester_name
