from rest_framework import serializers
from .models import ServiceForm, FormStep, FormOption, FormSubmission


class FormOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormOption
        fields = ['id', 'label', 'sort_order']


class FormStepSerializer(serializers.ModelSerializer):
    options = FormOptionSerializer(many=True, read_only=True)

    class Meta:
        model = FormStep
        fields = [
            'id', 'title', 'description', 'field_type',
            'is_required', 'allow_custom', 'step_order', 'options',
        ]


class ServiceFormSerializer(serializers.ModelSerializer):
    steps = FormStepSerializer(many=True, read_only=True)
    total_steps = serializers.SerializerMethodField()

    class Meta:
        model = ServiceForm
        fields = ['id', 'name', 'steps', 'total_steps']

    def get_total_steps(self, obj):
        return obj.steps.count()


class FormSubmissionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormSubmission
        fields = ['id', 'form', 'responses', 'submitted_at']
        read_only_fields = ['id', 'submitted_at']

    def create(self, validated_data):
        customer = self.context['request'].user.customer_profile
        return FormSubmission.objects.create(customer=customer, **validated_data)