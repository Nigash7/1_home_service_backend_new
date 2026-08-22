from rest_framework import serializers

from .models import Referral


class ReferralInfoSerializer(serializers.Serializer):
    """
    Everything the customer app needs for the home banner, the profile card
    and the Refer & Earn screen, with the reward amounts already substituted
    into the copy.
    """
    is_active = serializers.BooleanField()
    code = serializers.CharField()
    share_message = serializers.CharField()

    referrer_reward = serializers.DecimalField(max_digits=10, decimal_places=2)
    friend_reward = serializers.DecimalField(max_digits=10, decimal_places=2)

    home_banner_title = serializers.CharField()
    home_banner_subtitle = serializers.CharField()
    profile_card_title = serializers.CharField()
    profile_card_subtitle = serializers.CharField()
    profile_card_button = serializers.CharField()
    screen_title = serializers.CharField()
    screen_description = serializers.CharField()
    steps = serializers.ListField(child=serializers.CharField())
    terms = serializers.CharField()

    total_invited = serializers.IntegerField()
    total_earned_count = serializers.IntegerField()
    total_earned_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class MyReferralSerializer(serializers.ModelSerializer):
    """One invited friend, as shown in the customer's own referral list."""
    friend_name = serializers.SerializerMethodField()

    class Meta:
        model = Referral
        fields = ['id', 'friend_name', 'status', 'reward_amount', 'created_at', 'earned_at']

    def get_friend_name(self, obj):
        user = obj.referred_customer.user
        name = user.get_full_name().strip()
        return name or 'A friend'
