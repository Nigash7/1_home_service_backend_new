from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.permissions import IsCustomer, IsVendor
from .models import Booking, JobStartPhoto
from .serializers import BookingCreateSerializer, BookingListSerializer, JobStartPhotoSerializer


class BookingCreateView(generics.CreateAPIView):
    """
    POST /api/bookings/
    Customer creates a new booking (category + date + time + notes).
    Booking starts as PENDING with no vendor -- admin assigns one later from the admin panel.
    """
    serializer_class = BookingCreateSerializer
    permission_classes = [IsCustomer]


class MyBookingsListView(generics.ListAPIView):
    """
    GET /api/bookings/my/
    Customer app: "My Bookings" screen -- shows all of this customer's own bookings.
    """
    serializer_class = BookingListSerializer
    permission_classes = [IsCustomer]

    def get_queryset(self):
        return Booking.objects.filter(
            customer=self.request.user.customer_profile
        ).select_related(
            'customer__user', 'category', 'subcategory', 'vendor__user'
        ).order_by('-created_at')


class AssignedBookingsListView(generics.ListAPIView):
    """
    GET /api/bookings/assigned/
    Vendor app: "My Jobs" screen -- shows bookings assigned to this vendor.
    """
    serializer_class = BookingListSerializer
    permission_classes = [IsVendor]

    def get_queryset(self):
        return Booking.objects.filter(
            vendor=self.request.user.vendor_profile
        ).exclude(status=Booking.Status.PENDING).select_related(
            'customer__user', 'category', 'subcategory', 'vendor__user'
        ).order_by('-assigned_at')


class BookingStartPhotoUploadView(APIView):
    """
    POST /api/bookings/<id>/start-photo/
    Vendor app: called when the vendor arrives on-site and takes the geotagged photo.
    Body (multipart/form-data): image, latitude, longitude
    Effect: creates the JobStartPhoto AND flips booking.status -> IN_PROGRESS.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk)
        except Booking.DoesNotExist:
            return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

        # Security check: a vendor can only start a job THEY were assigned to
        if booking.vendor_id != request.user.vendor_profile.id:
            raise PermissionDenied("You are not assigned to this booking.")

        if booking.status != Booking.Status.ASSIGNED:
            raise ValidationError(f"Booking must be in ASSIGNED status to start. Current status: {booking.status}")

        if hasattr(booking, 'start_photo'):
            raise ValidationError("A start photo has already been submitted for this booking.")

        serializer = JobStartPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(booking=booking)

        booking.status = Booking.Status.IN_PROGRESS
        booking.save(update_fields=['status'])

        return Response(
            {"detail": "Job started successfully.", "start_photo": serializer.data, "booking_status": booking.status},
            status=status.HTTP_201_CREATED,
        )


class BookingCompleteView(APIView):
    """
    POST /api/bookings/<id>/complete/
    Vendor app: called when the vendor finishes the job.
    """
    permission_classes = [IsVendor]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(pk=pk)
        except Booking.DoesNotExist:
            return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

        if booking.vendor_id != request.user.vendor_profile.id:
            raise PermissionDenied("You are not assigned to this booking.")

        if booking.status != Booking.Status.IN_PROGRESS:
            raise ValidationError(f"Booking must be IN_PROGRESS to complete. Current status: {booking.status}")

        booking.status = Booking.Status.COMPLETED
        booking.completed_at = timezone.now()
        booking.save(update_fields=['status', 'completed_at'])

        return Response({"detail": "Job marked as completed.", "booking_status": booking.status})


class BookingCancelView(APIView):
    permission_classes = [IsCustomer]

    def post(self, request, pk):
        try:
            booking = Booking.objects.get(
                pk=pk,
                customer=request.user.customer_profile
            )
        except Booking.DoesNotExist:
            return Response(
                {"detail": "Booking not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        if booking.status != Booking.Status.PENDING:
            return Response(
                {"detail": "Only pending bookings can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])

        return Response({
            "detail": "Booking cancelled successfully.",
            "booking_status": booking.status
        })        
