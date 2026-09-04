import json
import logging

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCustomer
from bookings.models import Booking

from . import gateway, services
from .models import Payment, Payout, WebhookEvent, to_rupees
from .serializers import (
    CreateOrderSerializer, PaymentSerializer, VerifyPaymentSerializer,
)

logger = logging.getLogger(__name__)


def _entity(payload, name):
    """Dig payload.entity.<name>.entity out of Razorpay's nested envelope."""
    try:
        return payload['payload'][name]['entity'] or {}
    except (KeyError, TypeError):
        return {}


class CreateOrderView(APIView):
    """
    POST /api/payments/order/   {"booking_id": 12}

    Opens a Razorpay order for a booking the caller owns and returns what the
    app needs to launch Checkout. The amount is taken from the booking, never
    from the request body.
    """
    permission_classes = [IsCustomer]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = request.user.customer_profile
        try:
            booking = Booking.objects.get(
                pk=serializer.validated_data['booking_id'], customer=customer
            )
        except Booking.DoesNotExist:
            return Response({"detail": "Booking not found."},
                            status=status.HTTP_404_NOT_FOUND)

        if booking.payment_status == Booking.PaymentStatus.PAID:
            return Response({"detail": "This booking is already paid."},
                            status=status.HTTP_400_BAD_REQUEST)
        if booking.status == Booking.Status.CANCELLED:
            return Response({"detail": "This booking was cancelled."},
                            status=status.HTTP_400_BAD_REQUEST)

        amount_paise = services.amount_due_paise(booking)
        if amount_paise <= 0:
            return Response({"detail": "This booking has no amount to pay."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Reuse the open order unless the booking has been re-priced since,
        # so backing out of Checkout and returning does not strand an order.
        existing = services.open_payment_for(booking)
        if existing and existing.amount_paise == amount_paise:
            payment = existing
        else:
            try:
                order = gateway.create_order(
                    amount_paise=amount_paise,
                    receipt=f"booking-{booking.pk}",
                    notes={'booking_id': str(booking.pk),
                           'customer_id': str(customer.pk)},
                )
            except gateway.PaymentError as exc:
                return Response({"detail": str(exc)},
                                status=status.HTTP_502_BAD_GATEWAY)

            payment = Payment.objects.create(
                booking=booking,
                customer=customer,
                razorpay_order_id=order['id'],
                amount=to_rupees(amount_paise),
                currency=settings.RAZORPAY_CURRENCY,
                is_live=settings.RAZORPAY_IS_LIVE,
            )

        return Response({
            'payment_id': payment.pk,
            'order_id': payment.razorpay_order_id,
            'amount': payment.amount_paise,       # paise, for Checkout
            'amount_display': str(payment.amount),
            'currency': payment.currency,
            'key_id': settings.RAZORPAY_KEY_ID,   # publishable, safe to send
            'booking_id': booking.pk,
            'is_live': payment.is_live,
        }, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    """
    POST /api/payments/verify/

    The app calls this with what Checkout returned. A valid signature is
    necessary but not sufficient: we also ask Razorpay directly what state the
    payment is in, because the signature only proves the ids are genuine, not
    that the money was actually captured.
    """
    permission_classes = [IsCustomer]

    def post(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = Payment.objects.get(
                razorpay_order_id=data['razorpay_order_id'],
                customer=request.user.customer_profile,
            )
        except Payment.DoesNotExist:
            return Response({"detail": "Unknown order."},
                            status=status.HTTP_404_NOT_FOUND)

        if not gateway.verify_checkout_signature(
            order_id=data['razorpay_order_id'],
            payment_id=data['razorpay_payment_id'],
            signature=data['razorpay_signature'],
        ):
            services.mark_failed(payment, reason="Signature verification failed.")
            logger.warning("payments: bad signature on order %s",
                           data['razorpay_order_id'])
            return Response({"detail": "Payment could not be verified."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            remote = gateway.fetch_payment(data['razorpay_payment_id'])
        except gateway.PaymentError as exc:
            # The webhook is the backstop here, so don't fail the payment.
            return Response({"detail": str(exc)},
                            status=status.HTTP_502_BAD_GATEWAY)

        if remote.get('order_id') != payment.razorpay_order_id:
            return Response({"detail": "Payment does not belong to this order."},
                            status=status.HTTP_400_BAD_REQUEST)

        if int(remote.get('amount') or 0) < payment.amount_paise:
            logger.error("payments: short payment on order %s",
                         payment.razorpay_order_id)
            return Response({"detail": "Paid amount does not match the booking."},
                            status=status.HTTP_400_BAD_REQUEST)

        if remote.get('status') != 'captured':
            services.mark_failed(
                payment,
                reason=remote.get('error_description') or f"Status: {remote.get('status')}",
                payment_id=data['razorpay_payment_id'],
            )
            return Response({"detail": "Payment was not completed."},
                            status=status.HTTP_400_BAD_REQUEST)

        services.mark_paid(
            payment,
            payment_id=data['razorpay_payment_id'],
            method=remote.get('method') or '',
            signature=data['razorpay_signature'],
        )
        payment.refresh_from_db()
        return Response({
            'detail': 'Payment successful.',
            'payment': PaymentSerializer(payment).data,
        })


class MyPaymentsListView(generics.ListAPIView):
    """GET /api/payments/my/ - the caller's own payment history."""
    serializer_class = PaymentSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return (Payment.objects
                .filter(customer=self.request.user.customer_profile)
                .select_related('booking'))


class BookingPaymentStatusView(APIView):
    """
    GET /api/payments/booking/<id>/

    Lets the app show the true state after a checkout it could not confirm --
    a killed app or a dropped connection still ends up correct here, because
    the webhook will have landed.
    """
    permission_classes = [IsCustomer]

    def get(self, request, pk):
        try:
            booking = Booking.objects.get(
                pk=pk, customer=request.user.customer_profile
            )
        except Booking.DoesNotExist:
            return Response({"detail": "Booking not found."},
                            status=status.HTTP_404_NOT_FOUND)

        payments = booking.payments.all()
        paid = payments.filter(status=Payment.Status.CAPTURED).first()
        return Response({
            'booking_id': booking.pk,
            'payment_status': booking.payment_status,
            'amount': str(booking.amount),
            'is_paid': paid is not None,
            'payments': PaymentSerializer(payments, many=True).data,
        })


@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    """
    POST /api/payments/webhook/razorpay/

    Razorpay's server-to-server callback, and the authoritative path: the
    browser callback can be lost, but this one is retried until it gets a 2xx.

    Unauthenticated by necessity, so the signature check is the only thing
    standing between this and a public endpoint that marks bookings paid.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        body = request.body
        signature = request.headers.get('X-Razorpay-Signature', '')

        if not gateway.verify_webhook_signature(body=body, signature=signature):
            logger.warning("payments: rejected webhook with bad/missing signature")
            return Response({"detail": "Invalid signature."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            data = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "Malformed payload."},
                            status=status.HTTP_400_BAD_REQUEST)

        event_type = data.get('event', '')
        # Razorpay's delivery id. Falling back to the payload's own id keeps
        # replays deduplicated even if the header is ever absent.
        event_id = (
            request.headers.get('X-Razorpay-Event-Id')
            or f"{event_type}:{_entity(data, 'payment').get('id', '')}"
        )

        event, created = WebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={'event_type': event_type, 'payload': data},
        )
        if not created:
            # Already handled. Answer 200 or Razorpay keeps retrying forever.
            return Response({"detail": "Already processed."},
                            status=status.HTTP_200_OK)

        try:
            self._handle(event, event_type, data)
        except Exception as exc:
            logger.exception("payments: webhook %s failed", event_id)
            event.error = str(exc)[:2000]
            event.save(update_fields=['error'])
            # 500 asks Razorpay to retry, which is what we want for a bug our
            # side; the get_or_create above stops that turning into a loop of
            # duplicate work once it succeeds.
            return Response({"detail": "Processing failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        event.processed = True
        event.save(update_fields=['processed', 'payment'])
        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    def _handle(self, event, event_type, data):
        # Payouts and validations come through the same webhook endpoint but
        # carry a different entity, so they are split off before the
        # payment-shaped handling below.
        if event_type.startswith('payout.'):
            return self._handle_payout(event_type, data)
        if event_type.startswith('fund_account.validation'):
            return self._handle_validation(data)

        entity = _entity(data, 'payment')
        order_id = entity.get('order_id')
        if not order_id:
            return

        payment = Payment.objects.filter(razorpay_order_id=order_id).first()
        if payment is None:
            # Not a booking. Tender confirmation fees are charged through the
            # same Razorpay account and so arrive on this endpoint too; they
            # keep their own records rather than a Payment row, because none
            # of the escrow half applies to a platform fee.
            if self._handle_tender_fee(event_type, order_id, entity):
                return
            logger.warning("payments: webhook for unknown order %s", order_id)
            return
        event.payment = payment

        if event_type in ('payment.captured', 'order.paid'):
            services.mark_paid(
                payment,
                payment_id=entity.get('id') or '',
                method=entity.get('method') or '',
            )
        elif event_type == 'payment.failed':
            services.mark_failed(
                payment,
                reason=entity.get('error_description') or '',
                payment_id=entity.get('id') or '',
            )
        elif event_type.startswith('refund.'):
            refunded = entity.get('amount_refunded')
            if refunded is None:
                refunded = _entity(data, 'refund').get('amount', 0)
            services.apply_refund(
                payment, amount_refunded_rupees=to_rupees(refunded)
            )

    def _handle_tender_fee(self, event_type, order_id, entity):
        """
        A tender confirmation fee settling. Returns True when the order was
        one, so the caller stops looking for a booking that was never there.

        Imported here rather than at module level: tenders reaches into
        payments for the gateway, and a top-level import back would close the
        loop.
        """
        from tenders import services as tender_services

        fee = tender_services.fee_for_order(order_id)
        if fee is None:
            return False

        if event_type in ('payment.captured', 'order.paid'):
            tender_services.mark_fee_paid(
                fee,
                payment_id=entity.get('id') or '',
                method=entity.get('method') or '',
            )
        elif event_type == 'payment.failed':
            tender_services.mark_fee_failed(
                fee,
                reason=entity.get('error_description') or '',
                payment_id=entity.get('id') or '',
            )
        return True

    def _handle_payout(self, event_type, data):
        """
        RazorpayX telling us what happened to a transfer.

        This is the authoritative path for payouts: creating one returns
        `queued` or `processing`, and only the webhook says whether the money
        actually landed.
        """
        entity = _entity(data, 'payout')
        payout_id = entity.get('id')
        if not payout_id:
            return

        payout = Payout.objects.filter(razorpay_payout_id=payout_id).first()
        if payout is None:
            # Match on the reference we set at creation, for the window where
            # the webhook beats our own response back.
            reference = entity.get('reference_id') or ''
            if reference.startswith('booking-'):
                payout = Payout.objects.filter(
                    payment__booking_id=reference.removeprefix('booking-'),
                ).order_by('-created_at').first()

        if payout is None:
            logger.warning("payments: payout webhook for unknown payout %s",
                           payout_id)
            return

        services.apply_payout_result(payout, entity)

    def _handle_validation(self, data):
        """A penny drop the bank answered after we stopped waiting."""
        from vendors.bank_models import VendorBankAccount
        from vendors import payout_services

        entity = _entity(data, 'fund_account.validation')
        fund_account_id = (entity.get('fund_account') or {}).get('id')
        if not fund_account_id:
            return

        account = VendorBankAccount.objects.filter(
            razorpayx_fund_account_id=fund_account_id
        ).first()
        if account is None:
            logger.warning("payments: validation webhook for unknown account")
            return

        payout_services.apply_validation_result(account, entity)
