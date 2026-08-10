from rest_framework import serializers
from .models import SupportTicket, TicketMessage


class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = ['id', 'sender', 'message', 'created_at']


class SupportTicketSerializer(serializers.ModelSerializer):
    messages = TicketMessageSerializer(many=True, read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'subject', 'category', 'category_display',
            'status', 'status_display', 'booking',
            'created_at', 'updated_at', 'messages',
        ]


class SupportTicketCreateSerializer(serializers.ModelSerializer):
    message = serializers.CharField(write_only=True)

    class Meta:
        model = SupportTicket
        fields = ['id', 'subject', 'category', 'booking', 'message']

    def create(self, validated_data):
        message_text = validated_data.pop('message')
        customer = self.context['request'].user.customer_profile
        ticket = SupportTicket.objects.create(customer=customer, **validated_data)
        TicketMessage.objects.create(
            ticket=ticket, sender='CUSTOMER', message=message_text
        )
        return ticket