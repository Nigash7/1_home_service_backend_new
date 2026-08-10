from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from accounts.models import User
from .models import Customer


class CustomerRegisterSerializer(serializers.Serializer):
    """
    Used by the Customer app's signup screen.
    Creates BOTH the User (login) and Customer (profile) in one call.
    """
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, validators=[validate_password])
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=15)
    address = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data.get('last_name', ''),
            phone_number=validated_data['phone_number'],
            role=User.Role.CUSTOMER,
        )
        customer = Customer.objects.create(
            user=user,
            address=validated_data.get('address', ''),
            latitude=validated_data.get('latitude'),
            longitude=validated_data.get('longitude'),
        )
        return customer


class CustomerProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    first_name = serializers.CharField(source='user.first_name')
    last_name = serializers.CharField(source='user.last_name', required=False)
    phone_number = serializers.CharField(source='user.phone_number')
    email = serializers.EmailField(source='user.email', required=False, allow_blank=True)
    is_profile_complete = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'username', 'first_name', 'last_name', 'phone_number', 'email',
            'address', 'state', 'district', 'pincode', 'latitude', 'longitude',
            'is_profile_complete',
        ]

    def get_is_profile_complete(self, obj):
        return bool(
            obj.user.first_name
            and obj.address
            and obj.state
            and obj.district
            and obj.pincode
        )

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        for attr, value in user_data.items():
            setattr(instance.user, attr, value)
        instance.user.save()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance