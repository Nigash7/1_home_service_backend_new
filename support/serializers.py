from rest_framework import serializers
from .models import SupportTicket, TicketMessage


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_display = serializers.CharField(source='get_sender_display', read_only=True)
    is_support = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = ['id', 'sender', 'sender_display', 'is_support', 'message', 'created_at']

    def get_is_support(self, obj):
        return obj.sender == TicketMessage.Sender.ADMIN


class SupportTicketSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'subject', 'category', 'category_display',
            'status', 'status_display', 'raised_by', 'booking',
            'created_at', 'updated_at', 'messages',
        ]


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    """
    Used by both apps. The requester is taken from the authenticated user,
    never from the request body.
    """
    message = serializers.CharField(write_only=True)

    class Meta:
        model = SupportTicket
        fields = ['id', 'subject', 'category', 'booking', 'message']

    def validate_category(self, value):
        allowed = (
            SupportTicket.VENDOR_CATEGORIES
            if self._is_vendor()
            else SupportTicket.CUSTOMER_CATEGORIES
        )
        if value not in allowed:
            raise serializers.ValidationError(
                'That category is not available for your account type.'
            )
        return value

    def validate_booking(self, value):
        """A ticket can only be attached to a booking the requester is part of."""
        if value is None:
            return value
        user = self.context['request'].user
        if self._is_vendor():
            if value.vendor_id != getattr(user.vendor_profile, 'id', None):
                raise serializers.ValidationError('That job is not assigned to you.')
        else:
            if value.customer_id != getattr(user.customer_profile, 'id', None):
                raise serializers.ValidationError('That booking is not yours.')
        return value

    def create(self, validated_data):
        message_text = validated_data.pop('message')
        user = self.context['request'].user

        if self._is_vendor():
            ticket = SupportTicket.objects.create(
                vendor=user.vendor_profile,
                raised_by=SupportTicket.RaisedBy.VENDOR,
                **validated_data,
            )
            sender = TicketMessage.Sender.VENDOR
        else:
            ticket = SupportTicket.objects.create(
                customer=user.customer_profile,
                raised_by=SupportTicket.RaisedBy.CUSTOMER,
                **validated_data,
            )
            sender = TicketMessage.Sender.CUSTOMER

        TicketMessage.objects.create(ticket=ticket, sender=sender, message=message_text)

        from .notifications import notify_admins_new_ticket
        notify_admins_new_ticket(ticket)

        return ticket

    # ------------------------------------------------------------------ util
    def _is_vendor(self):
        from accounts.models import User
        return self.context['request'].user.role == User.Role.VENDOR
