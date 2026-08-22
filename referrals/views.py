from decimal import Decimal

from django.db.models import Sum
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCustomer
from .models import Referral, ReferralCode, ReferralProgram
from .serializers import ReferralInfoSerializer, MyReferralSerializer


class MyReferralInfoView(APIView):
    """
    GET /api/referrals/me/
    The customer's own referral code, the programme copy with amounts filled
    in, and how much they've earned so far. The code is minted on first call.
    """
    permission_classes = [IsCustomer]

    def get(self, request):
        customer = request.user.customer_profile
        program = ReferralProgram.get_solo()
        code = ReferralCode.for_customer(customer).code

        referrals = Referral.objects.filter(referrer=customer)
        earned = referrals.filter(
            status__in=[Referral.Status.EARNED, Referral.Status.SETTLED]
        )

        data = {
            'is_active': program.is_active,
            'code': code,
            'share_message': program.fill(program.share_message, code=code),
            'referrer_reward': program.referrer_reward,
            'friend_reward': program.friend_reward,
            'home_banner_title': program.fill(program.home_banner_title),
            'home_banner_subtitle': program.fill(program.home_banner_subtitle),
            'profile_card_title': program.fill(program.profile_card_title),
            'profile_card_subtitle': program.fill(program.profile_card_subtitle),
            'profile_card_button': program.fill(program.profile_card_button),
            'screen_title': program.fill(program.screen_title),
            'screen_description': program.fill(program.screen_description),
            'steps': [
                program.fill(program.step_one),
                program.fill(program.step_two),
                program.fill(program.step_three),
            ],
            'terms': program.fill(program.terms),
            'total_invited': referrals.count(),
            'total_earned_count': earned.count(),
            'total_earned_amount': earned.aggregate(
                total=Sum('reward_amount')
            )['total'] or Decimal('0'),
        }
        return Response(ReferralInfoSerializer(data).data)


class MyReferralListView(APIView):
    """
    GET /api/referrals/my-referrals/
    The friends this customer has invited, newest first.
    """
    permission_classes = [IsCustomer]

    def get(self, request):
        customer = request.user.customer_profile
        referrals = Referral.objects.filter(referrer=customer).select_related(
            'referred_customer__user'
        )
        return Response(MyReferralSerializer(referrals, many=True).data)
