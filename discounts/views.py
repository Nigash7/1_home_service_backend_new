from decimal import Decimal
from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from accounts.permissions import IsCustomer
from .models import Discount, Coupon, CouponUsage
from .serializers import DiscountSerializer, CouponValidateSerializer


def calculate_discount_amount(discount_type, value, max_discount, cart_total):
    """Calculates the discount amount from a percentage/flat rule."""
    cart_total = Decimal(str(cart_total))
    value = Decimal(str(value))

    if discount_type == 'PERCENTAGE':
        amount = (cart_total * value) / Decimal('100')
        if max_discount:
            amount = min(amount, Decimal(str(max_discount)))
    else:  # FLAT
        amount = value

    return min(amount, cart_total)  # Never exceed cart total


class ApplicableDiscountsView(APIView):
    """
    POST /api/discounts/applicable/
    Body: { "items": [{ "service_id": 1, "category_id": 2, "subcategory_id": 3, "price": 500, "qty": 1 }] }
    Returns the best auto-applied discount for the cart.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        items = request.data.get('items', [])
        if not items:
            return Response({'discount': None, 'discount_amount': 0})

        cart_total = sum(
            Decimal(str(item.get('price', 0))) * int(item.get('qty', 1))
            for item in items
        )

        # Find all applicable discounts and pick the best one
        best_discount = None
        best_amount = Decimal('0')

        service_ids = [item.get('service_id') for item in items if item.get('service_id')]
        subcategory_ids = [item.get('subcategory_id') for item in items if item.get('subcategory_id')]
        category_ids = [item.get('category_id') for item in items if item.get('category_id')]

        active_discounts = Discount.objects.filter(is_active=True)

        for discount in active_discounts:
            if not discount.is_valid_now():
                continue
            if cart_total < discount.min_order_amount:
                continue

            # Check target match
            applies = False
            if discount.service_id in service_ids:
                applies = True
            elif discount.subcategory_id in subcategory_ids:
                applies = True
            elif discount.category_id in category_ids:
                applies = True
            elif not discount.service and not discount.subcategory and not discount.category:
                applies = True  # Site-wide discount

            if not applies:
                continue

            amount = calculate_discount_amount(
                discount.discount_type,
                discount.value,
                discount.max_discount,
                cart_total,
            )

            if amount > best_amount:
                best_amount = amount
                best_discount = discount

        if best_discount:
            return Response({
                'discount': DiscountSerializer(best_discount).data,
                'discount_amount': str(best_amount),
                'cart_total': str(cart_total),
                'final_total': str(cart_total - best_amount),
            })

        return Response({
            'discount': None,
            'discount_amount': '0',
            'cart_total': str(cart_total),
            'final_total': str(cart_total),
        })


class ValidateCouponView(APIView):
    """
    POST /api/discounts/coupon/
    Body: { "code": "WELCOME50", "cart_total": 1000 }
    """
    permission_classes = [IsCustomer]

    def post(self, request):
        code = request.data.get('code', '').strip().upper()
        cart_total = Decimal(str(request.data.get('cart_total', 0)))

        if not code:
            return Response(
                {'error': 'Please enter a coupon code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            coupon = Coupon.objects.get(code__iexact=code)
        except Coupon.DoesNotExist:
            return Response(
                {'error': 'Invalid coupon code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not coupon.is_valid_now():
            return Response(
                {'error': 'This coupon has expired or is not currently active.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cart_total < coupon.min_order_amount:
            return Response(
                {'error': f'Minimum order of ₹{coupon.min_order_amount} required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check per-customer limit
        customer = request.user.customer_profile
        usage_count = CouponUsage.objects.filter(coupon=coupon, customer=customer).count()
        if usage_count >= coupon.per_customer_limit:
            return Response(
                {'error': 'You have already used this coupon.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        discount_amount = calculate_discount_amount(
            coupon.discount_type,
            coupon.value,
            coupon.max_discount,
            cart_total,
        )

        return Response({
            'coupon': CouponValidateSerializer(coupon).data,
            'discount_amount': str(discount_amount),
            'final_total': str(cart_total - discount_amount),
        })