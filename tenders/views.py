from django.db import transaction
from django.db.models import Avg, F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCustomer, IsCustomerOrVendor, IsVendor

from . import notifications as notify_tender
from .models import (
    Tender,
    TenderAttachment,
    TenderBid,
    TenderMilestone,
)
from .serializers import (
    TenderAttachmentSerializer,
    TenderBidSerializer,
    TenderBidWriteSerializer,
    TenderDetailSerializer,
    TenderListSerializer,
    TenderProgressUpdateSerializer,
    TenderReviewSerializer,
    TenderWriteSerializer,
)


def tender_queryset():
    """
    Base queryset for anything that serialises a tender. Every relation the
    list and detail serialisers touch is pulled in here -- without it a page
    of twenty tenders costs a query per bid, per vendor and per photo.
    """
    return Tender.objects.select_related(
        'customer__user', 'category', 'subcategory',
        'awarded_bid__vendor__user', 'review',
    ).prefetch_related(
        'attachments',
        'bids__vendor__user',
        'awarded_bid__milestones',
        'progress_updates__photos',
        'progress_updates__vendor__user',
    )


def get_customer_tender(request, pk, statuses=None):
    """
    One of the requesting customer's own tenders, optionally restricted to
    certain statuses. A tender belonging to someone else is a 404, not a 403 --
    there is no reason to confirm it exists.
    """
    tender = get_object_or_404(
        tender_queryset(), pk=pk, customer=request.user.customer_profile
    )
    if statuses is not None and tender.status not in statuses:
        raise ValidationError(
            f"This cannot be done while the tender is {tender.get_status_display()}."
        )
    return tender


def get_awarded_vendor_tender(request, pk, statuses=None):
    """The tender this vendor actually won, for the execution endpoints."""
    tender = get_object_or_404(tender_queryset(), pk=pk)
    vendor = request.user.vendor_profile
    if tender.awarded_vendor is None or tender.awarded_vendor.id != vendor.id:
        raise PermissionDenied("You are not the vendor on this project.")
    if statuses is not None and tender.status not in statuses:
        raise ValidationError(
            f"This cannot be done while the tender is {tender.get_status_display()}."
        )
    return tender


# ===========================================================================
# 1-3. Customer creates the tender and publishes it
# ===========================================================================
class TenderCreateView(generics.CreateAPIView):
    """
    POST /api/tenders/
    Customer app: create a tender. It starts as DRAFT so drawings can be
    attached before it goes anywhere -- publishing is a separate, deliberate
    step.
    """
    serializer_class = TenderWriteSerializer
    permission_classes = [IsCustomer]


class MyTendersListView(generics.ListAPIView):
    """
    GET /api/tenders/my/
    Customer app: "My Tenders". Optional ?status= to filter.
    """
    serializer_class = TenderListSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        qs = tender_queryset().filter(
            customer=self.request.user.customer_profile
        ).with_bid_stats()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class TenderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/tenders/<id>/   Customer who owns it, or a vendor who may see it.
    PATCH  /api/tenders/<id>/   Owner only, and only before it goes out.
    DELETE /api/tenders/<id>/   Owner only, drafts only.
    """
    permission_classes = [IsCustomerOrVendor]

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return TenderWriteSerializer
        return TenderDetailSerializer

    def get_queryset(self):
        return tender_queryset()

    def get_object(self):
        tender = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        vendor = getattr(self.request.user, 'vendor_profile', None)

        if vendor is not None:
            if self.request.method != 'GET':
                raise PermissionDenied("Vendors cannot edit a tender.")
            if not self._vendor_may_view(tender, vendor):
                raise PermissionDenied("This tender is not open to you.")
            return tender

        if tender.customer_id != self.request.user.customer_profile.id:
            raise PermissionDenied("This is not your tender.")

        if self.request.method in ('PATCH', 'PUT', 'DELETE'):
            if tender.status not in Tender.EDITABLE_STATUSES:
                raise ValidationError(
                    "A tender can only be changed while it is a draft or after "
                    "it has been sent back."
                )
        return tender

    def _vendor_may_view(self, tender, vendor):
        """
        A vendor sees a tender if it is open to them, if they bid on it, or if
        they won it. Past bidders keep access so their history stays readable.
        """
        if tender.bids.filter(vendor=vendor).exists():
            return True
        if tender.awarded_vendor is not None and tender.awarded_vendor.id == vendor.id:
            return True
        if tender.status != Tender.Status.OPEN:
            return False
        return Tender.objects.filter(pk=tender.pk).for_vendor(vendor).exists()


class TenderPublishView(APIView):
    """
    POST /api/tenders/<id>/publish/
    Customer app: send the tender for review. An admin approves it before any
    vendor sees it, so this lands on PENDING_APPROVAL rather than OPEN.
    """
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        tender = get_customer_tender(request, pk, statuses=Tender.EDITABLE_STATUSES)

        tender.status = Tender.Status.PENDING_APPROVAL
        tender.submitted_at = timezone.now()
        tender.rejection_reason = ''
        tender.save(update_fields=['status', 'submitted_at', 'rejection_reason', 'updated_at'])

        notify_tender.notify_customer_submitted(tender)
        notify_tender.notify_admins_submitted(tender)

        return Response({
            'detail': 'Tender sent for review. We will publish it to vendors shortly.',
            'tender': TenderDetailSerializer(tender, context={'request': request}).data,
        })


class TenderCancelView(APIView):
    """
    POST /api/tenders/<id>/cancel/
    Customer app: pull a tender before work starts. Anyone who bid is told,
    because they were waiting on an answer.
    """
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        tender = get_customer_tender(request, pk)

        if tender.status in (Tender.Status.COMPLETED, Tender.Status.CANCELLED):
            raise ValidationError("This tender is already closed.")
        if tender.status == Tender.Status.IN_PROGRESS:
            raise ValidationError(
                "Work has already started. Contact support to close this project."
            )

        live_bids = list(tender.active_bids.select_related('vendor__user'))

        tender.status = Tender.Status.CANCELLED
        tender.cancellation_reason = (request.data.get('reason') or '').strip()
        tender.save(update_fields=['status', 'cancellation_reason', 'updated_at'])

        notify_tender.notify_vendors_tender_closed(
            tender, live_bids, reason=tender.cancellation_reason
        )
        notify_tender.notify_admins_cancelled(tender)

        return Response({'detail': 'Tender cancelled.', 'status': tender.status})


class TenderAttachmentUploadView(APIView):
    """
    POST /api/tenders/<id>/attachments/
    Customer app: attach a drawing or site photo. Multipart: file, caption.
    """
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        tender = get_customer_tender(request, pk, statuses=Tender.EDITABLE_STATUSES)

        # The request has to be in context or `file` comes back as a bare
        # media path, which the apps cannot load.
        serializer = TenderAttachmentSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(tender=tender)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TenderAttachmentDeleteView(APIView):
    """
    DELETE /api/tenders/attachments/<id>/
    Customer app: remove an attachment while the tender is still editable.
    """
    permission_classes = [IsCustomer]

    def delete(self, request, pk):
        attachment = get_object_or_404(
            TenderAttachment, pk=pk, tender__customer=request.user.customer_profile
        )
        if attachment.tender.status not in Tender.EDITABLE_STATUSES:
            raise ValidationError("This tender has already gone out to vendors.")
        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# 4. Vendors browse and bid
# ===========================================================================
class OpenTendersListView(generics.ListAPIView):
    """
    GET /api/tenders/open/
    Vendor app: "Browse Tenders" -- everything open that this vendor covers.
    Filters: ?category=<id> ?project_type=<key> ?pincode= ?district=
    """
    serializer_class = TenderListSerializer
    permission_classes = [IsVendor]

    def get_queryset(self):
        vendor = self.request.user.vendor_profile
        qs = tender_queryset().open_for_bids().for_vendor(vendor).with_bid_stats()

        params = self.request.query_params
        if params.get('category'):
            qs = qs.filter(category_id=params['category'])
        if params.get('project_type'):
            qs = qs.filter(project_type=params['project_type'])
        if params.get('pincode'):
            qs = qs.filter(address_pincode=params['pincode'])
        if params.get('district'):
            qs = qs.filter(address_district__icontains=params['district'])
        return qs


class MyBidsListView(generics.ListAPIView):
    """
    GET /api/tenders/my-bids/
    Vendor app: every bid this vendor has placed, newest first.
    """
    serializer_class = TenderBidSerializer
    permission_classes = [IsVendor]

    def get_queryset(self):
        return TenderBid.objects.filter(
            vendor=self.request.user.vendor_profile
        ).select_related(
            'tender__category', 'vendor__user'
        ).prefetch_related('milestones').order_by('-created_at')


class MyProjectsListView(generics.ListAPIView):
    """
    GET /api/tenders/awarded/
    Vendor app: the projects this vendor won -- their execution list.
    """
    serializer_class = TenderListSerializer
    permission_classes = [IsVendor]

    def get_queryset(self):
        return tender_queryset().filter(
            awarded_bid__vendor=self.request.user.vendor_profile
        ).with_bid_stats()


class TenderMyBidView(APIView):
    """
    POST   /api/tenders/<id>/bid/   Vendor app: submit a bid.
    PATCH  /api/tenders/<id>/bid/   Revise it while bidding is open.
    DELETE /api/tenders/<id>/bid/   Withdraw it.

    One bid per vendor per tender, revised rather than re-submitted, so the
    customer never compares two quotes from the same outfit.
    """
    permission_classes = [IsVendor]

    def _tender(self, pk):
        return get_object_or_404(tender_queryset(), pk=pk)

    def _my_bid(self, tender, vendor):
        return tender.bids.filter(vendor=vendor).first()

    def post(self, request, pk):
        tender = self._tender(pk)
        vendor = request.user.vendor_profile

        if not tender.is_bidding_open:
            raise ValidationError("This tender is no longer accepting bids.")
        if not Tender.objects.filter(pk=tender.pk).for_vendor(vendor).exists():
            raise PermissionDenied("This tender is not open to you.")
        if self._my_bid(tender, vendor) is not None:
            raise ValidationError(
                "You have already bid on this tender. Edit your bid instead."
            )

        serializer = TenderBidWriteSerializer(
            data=request.data, context={'request': request, 'tender': tender}
        )
        serializer.is_valid(raise_exception=True)
        bid = serializer.save()

        notify_tender.notify_customer_new_bid(tender, bid)

        return Response(
            TenderBidSerializer(bid, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, pk):
        tender = self._tender(pk)
        bid = self._my_bid(tender, request.user.vendor_profile)
        if bid is None:
            raise ValidationError("You have not bid on this tender.")
        if not bid.is_editable:
            raise ValidationError("This bid can no longer be changed.")

        serializer = TenderBidWriteSerializer(
            bid, data=request.data, partial=True,
            context={'request': request, 'tender': tender},
        )
        serializer.is_valid(raise_exception=True)
        bid = serializer.save()
        return Response(TenderBidSerializer(bid, context={'request': request}).data)

    def delete(self, request, pk):
        tender = self._tender(pk)
        bid = self._my_bid(tender, request.user.vendor_profile)
        if bid is None:
            raise ValidationError("You have not bid on this tender.")
        if bid.status != TenderBid.Status.SUBMITTED:
            raise ValidationError("This bid has already been decided.")

        bid.status = TenderBid.Status.WITHDRAWN
        bid.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'Bid withdrawn.', 'status': bid.status})


# ===========================================================================
# 5-6. Customer compares the bids and picks one
# ===========================================================================
class TenderBidsListView(generics.ListAPIView):
    """
    GET /api/tenders/<id>/bids/
    Customer app: "Compare Bids" -- every live quote with the vendor's rating,
    experience and reviews attached. Sorted cheapest first; ?sort=rating or
    ?sort=timeline reorders.
    """
    serializer_class = TenderBidSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        tender = get_object_or_404(
            Tender, pk=self.kwargs['pk'], customer=self.request.user.customer_profile
        )
        bids = tender.active_bids.select_related(
            'vendor__user'
        ).prefetch_related('milestones', 'vendor__reviews_received')

        sort = self.request.query_params.get('sort', 'amount')
        if sort == 'timeline':
            # Vendors who gave no timeline sort last -- an unanswered question
            # should not look like the fastest quote.
            return bids.order_by(F('timeline_days').asc(nulls_last=True), 'amount')
        if sort == 'rating':
            # Unrated vendors sort last for the same reason: no reviews is not
            # a good score.
            return bids.annotate(
                vendor_rating=Avg('vendor__reviews_received__rating')
            ).order_by(F('vendor_rating').desc(nulls_last=True), 'amount')
        return bids.order_by('amount', 'created_at')


class TenderBidAcceptView(APIView):
    """
    POST /api/tenders/bids/<id>/accept/
    Customer app: "Select Best Vendor". Awards the tender, turns down every
    other bid and tells all sides -- the deal-confirmed step of the flow.
    """
    permission_classes = [IsCustomer]

    @transaction.atomic
    def post(self, request, pk):
        bid = get_object_or_404(
            TenderBid.objects.select_related('tender', 'vendor__user'),
            pk=pk, tender__customer=request.user.customer_profile,
        )
        tender = bid.tender

        if tender.status != Tender.Status.OPEN:
            raise ValidationError(
                f"This tender is {tender.get_status_display()} and cannot be awarded."
            )
        if bid.status != TenderBid.Status.SUBMITTED:
            raise ValidationError("That bid is no longer available to accept.")

        now = timezone.now()
        losing_bids = list(
            tender.bids.exclude(pk=bid.pk)
            .filter(status=TenderBid.Status.SUBMITTED)
            .select_related('vendor__user')
        )

        bid.status = TenderBid.Status.ACCEPTED
        bid.decided_at = now
        bid.save(update_fields=['status', 'decided_at', 'updated_at'])

        tender.bids.exclude(pk=bid.pk).filter(
            status=TenderBid.Status.SUBMITTED
        ).update(status=TenderBid.Status.REJECTED, decided_at=now)

        tender.awarded_bid = bid
        tender.status = Tender.Status.AWARDED
        tender.awarded_at = now
        tender.save(update_fields=['awarded_bid', 'status', 'awarded_at', 'updated_at'])

        # After the row is safely committed, so a push failure can never undo
        # the award the customer just made.
        transaction.on_commit(lambda: notify_tender.notify_customer_awarded(tender, bid))
        transaction.on_commit(lambda: notify_tender.notify_vendor_won(tender, bid))
        transaction.on_commit(lambda: notify_tender.notify_vendors_lost(tender, losing_bids))
        transaction.on_commit(lambda: notify_tender.notify_admins_awarded(tender, bid))

        return Response({
            'detail': f'{bid.vendor.display_name} has been awarded this project.',
            'tender': TenderDetailSerializer(tender, context={'request': request}).data,
        })


# ===========================================================================
# Project execution: start, progress, milestones, completion, review
# ===========================================================================
class TenderStartView(APIView):
    """
    POST /api/tenders/<id>/start/
    Vendor app: begin the awarded project.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        tender = get_awarded_vendor_tender(
            request, pk, statuses=[Tender.Status.AWARDED]
        )

        tender.status = Tender.Status.IN_PROGRESS
        tender.started_at = timezone.now()
        tender.save(update_fields=['status', 'started_at', 'updated_at'])

        notify_tender.notify_customer_work_started(tender)
        return Response({'detail': 'Project started.', 'status': tender.status})


class TenderProgressCreateView(APIView):
    """
    POST /api/tenders/<id>/progress/add/
    Vendor app: post an update. Multipart: message, percent_complete, images[].
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        tender = get_awarded_vendor_tender(
            request, pk, statuses=[Tender.Status.IN_PROGRESS]
        )

        serializer = TenderProgressUpdateSerializer(
            data=request.data, context={'request': request, 'tender': tender}
        )
        serializer.is_valid(raise_exception=True)
        update = serializer.save()

        notify_tender.notify_customer_progress(tender, update)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TenderProgressListView(generics.ListAPIView):
    """
    GET /api/tenders/<id>/progress/
    Both apps: the update history for a project, newest first.
    """
    serializer_class = TenderProgressUpdateSerializer
    permission_classes = [IsCustomerOrVendor]

    def get_queryset(self):
        tender = get_object_or_404(Tender, pk=self.kwargs['pk'])
        vendor = getattr(self.request.user, 'vendor_profile', None)

        if vendor is not None:
            if tender.awarded_vendor is None or tender.awarded_vendor.id != vendor.id:
                raise PermissionDenied("You are not the vendor on this project.")
        elif tender.customer_id != self.request.user.customer_profile.id:
            raise PermissionDenied("This is not your tender.")

        return tender.progress_updates.select_related(
            'vendor__user'
        ).prefetch_related('photos')


class TenderMilestoneReachView(APIView):
    """
    POST /api/tenders/milestones/<id>/reach/
    Vendor app: mark a stage of work done, which is what puts the payment in
    front of the customer.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        milestone = get_object_or_404(
            TenderMilestone.objects.select_related('bid__tender', 'bid__vendor'), pk=pk
        )
        tender = milestone.tender
        vendor = request.user.vendor_profile

        if tender.awarded_bid_id != milestone.bid_id:
            raise PermissionDenied("That milestone is not part of the awarded bid.")
        if tender.awarded_vendor is None or tender.awarded_vendor.id != vendor.id:
            raise PermissionDenied("You are not the vendor on this project.")
        if tender.status != Tender.Status.IN_PROGRESS:
            raise ValidationError("The project is not currently running.")
        if milestone.status != TenderMilestone.Status.PENDING:
            raise ValidationError("That milestone has already been marked.")

        milestone.status = TenderMilestone.Status.REACHED
        milestone.reached_at = timezone.now()
        milestone.save(update_fields=['status', 'reached_at'])

        notify_tender.notify_customer_milestone_reached(tender, milestone)
        return Response({'detail': 'Milestone marked as reached.', 'status': milestone.status})


class TenderMilestonePayView(APIView):
    """
    POST /api/tenders/milestones/<id>/pay/
    Customer app: record that a milestone has been settled.

    This does not move money -- no gateway is wired in -- it records what the
    customer says they have paid, the same way Booking.payment_status does.
    """
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        milestone = get_object_or_404(
            TenderMilestone.objects.select_related('bid__tender'),
            pk=pk, bid__tender__customer=request.user.customer_profile,
        )
        tender = milestone.tender

        if tender.awarded_bid_id != milestone.bid_id:
            raise ValidationError("That milestone is not part of the awarded bid.")
        if milestone.status == TenderMilestone.Status.PAID:
            raise ValidationError("That milestone is already settled.")
        if milestone.status != TenderMilestone.Status.REACHED:
            raise ValidationError(
                "The vendor has not marked this stage complete yet."
            )

        milestone.status = TenderMilestone.Status.PAID
        milestone.paid_at = timezone.now()
        milestone.save(update_fields=['status', 'paid_at'])

        tender.refresh_payment_status()
        notify_tender.notify_vendor_milestone_paid(tender, milestone)

        return Response({
            'detail': 'Payment recorded.',
            'status': milestone.status,
            'payment_status': tender.payment_status,
        })


class TenderCompleteView(APIView):
    """
    POST /api/tenders/<id>/complete/
    Vendor app: mark the project finished, which prompts the customer to review.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        tender = get_awarded_vendor_tender(
            request, pk, statuses=[Tender.Status.IN_PROGRESS]
        )

        tender.status = Tender.Status.COMPLETED
        tender.completed_at = timezone.now()
        tender.save(update_fields=['status', 'completed_at', 'updated_at'])

        notify_tender.notify_customer_completed(tender)
        notify_tender.notify_admins_completed(tender)

        return Response({'detail': 'Project marked as completed.', 'status': tender.status})


class TenderReviewView(APIView):
    """
    POST /api/tenders/<id>/review/
    Customer app: rate the vendor once the project is done.

    Writes into the shared reviews.Review table so a tender counts towards the
    vendor's rating everywhere it is already shown -- pro vendor cards, the
    profile page, the dashboard.
    """
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        from reviews.models import Review

        tender = get_customer_tender(request, pk, statuses=[Tender.Status.COMPLETED])

        vendor = tender.awarded_vendor
        if vendor is None:
            raise ValidationError("This project has no vendor to review.")
        if Review.objects.filter(tender=tender).exists():
            raise ValidationError("You have already reviewed this project.")

        serializer = TenderReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review = Review.objects.create(
            tender=tender,
            customer=tender.customer,
            vendor=vendor,
            service_category=tender.category,
            rating=serializer.validated_data['rating'],
            comment=serializer.validated_data.get('comment', ''),
        )

        from notifications.services import notify
        notify(
            'vendor.review_received', vendor=vendor,
            context={
                'rating': review.rating,
                'customer_name': str(tender.customer),
                'service_name': tender.title,
            },
            data={'tender_id': tender.id},
        )

        return Response(
            {'detail': 'Thanks for the review.', 'rating': review.rating},
            status=status.HTTP_201_CREATED,
        )
