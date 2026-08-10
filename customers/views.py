from rest_framework import generics, permissions, status
from rest_framework.response import Response
from accounts.permissions import IsCustomer
from .models import Customer
from .serializers import CustomerRegisterSerializer, CustomerProfileSerializer


class CustomerRegisterView(generics.CreateAPIView):
    """
    POST /api/customers/register/
    Public signup endpoint for the Customer app.
    Body: username, password, first_name, last_name, phone_number, address, latitude, longitude
    """
    serializer_class = CustomerRegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        # Return the newly created profile using the PROFILE serializer,
        # not the registration input serializer (which has no `username`
        # attribute directly on the Customer model).
        output = CustomerProfileSerializer(customer)
        return Response(output.data, status=status.HTTP_201_CREATED)


class CustomerMeView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/customers/me/  -> view own profile
    PATCH /api/customers/me/ -> update own profile
    Requires a logged-in customer (JWT token in Authorization header).
    """
    serializer_class = CustomerProfileSerializer
    permission_classes = [IsCustomer]

    def get_object(self):
        return self.request.user.customer_profile
