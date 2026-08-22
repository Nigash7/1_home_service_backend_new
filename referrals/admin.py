from django.contrib import admin
from .models import Referral, ReferralCode, ReferralProgram


@admin.register(ReferralProgram)
class ReferralProgramAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'is_active', 'referrer_reward', 'friend_reward', 'updated_at')

    def has_add_permission(self, request):
        # Settings live in a single row.
        return not ReferralProgram.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'customer', 'created_at')
    search_fields = ('code',)


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        'referrer', 'referred_customer', 'code_used', 'status',
        'reward_amount', 'created_at', 'earned_at', 'settled_at',
    )
    list_filter = ('status',)
    search_fields = ('code_used',)
