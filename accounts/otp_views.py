from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .otp_serializers import SendOTPSerializer, VerifyOTPSerializer
from .email_otp_serializers import SendEmailOTPSerializer, VerifyEmailOTPSerializer


class SendOTPView(APIView):
    """
    POST /api/auth/send-otp/
    Body: { "phone_number": "9876543210" }
    Sends a 6-digit OTP to the phone (via console log in dev, real SMS in production).
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.create_and_send()
        return Response({"detail": "OTP sent successfully."}, status=status.HTTP_200_OK)


class VerifyOTPView(APIView):
    """
    POST /api/auth/verify-otp/
    Body: { "phone_number": "9876543210", "code": "123456",
            "first_name": "Ravi" (only needed for a brand new user),
            "last_name": "...", "address": "..." }
    Returns JWT tokens. Creates the customer account automatically if this
    is their first successful OTP verification.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.verify_and_login()
        return Response(result, status=status.HTTP_200_OK)


class SendEmailOTPView(APIView):
    """
    POST /api/auth/email/send-otp/
    Body: { "email": "someone@example.com" }
    Emails a 6-digit code to the address so the signed-in customer can prove
    it is theirs. The address is only written to the account once the code
    comes back verified.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SendEmailOTPSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.create_and_send()
        return Response(
            {"detail": "Verification code sent. Please check your inbox."},
            status=status.HTTP_200_OK,
        )


class VerifyEmailOTPView(APIView):
    """
    POST /api/auth/email/verify-otp/
    Body: { "email": "someone@example.com", "code": "123456" }
    Saves the address on the account and marks it verified.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = VerifyEmailOTPSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        result = serializer.confirm()
        return Response(result, status=status.HTTP_200_OK)
