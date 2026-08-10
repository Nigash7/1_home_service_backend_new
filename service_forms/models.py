from django.db import models


class ServiceForm(models.Model):
    """
    A multi-step form attached to a Service or SubCategory.
    Admin creates questions, customer fills them before booking.
    """
    name = models.CharField(max_length=200)
    service = models.ForeignKey(
        'services.Service', on_delete=models.CASCADE,
        null=True, blank=True, related_name='forms'
    )
    subcategory = models.ForeignKey(
        'services.SubCategory', on_delete=models.CASCADE,
        null=True, blank=True, related_name='forms'
    )
    category = models.ForeignKey(
        'services.ServiceCategory', on_delete=models.CASCADE,
        null=True, blank=True, related_name='forms'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Service Forms"

    def __str__(self):
        return self.name


class FormStep(models.Model):
    """One step/question in a ServiceForm."""

    class FieldType(models.TextChoices):
        SINGLE_SELECT = 'single_select', 'Single Select (radio)'
        MULTI_SELECT = 'multi_select', 'Multi Select (checkboxes)'
        TEXT = 'text', 'Text Input'
        NUMBER = 'number', 'Number Input'
        DATE = 'date', 'Date Picker'
        PHOTO = 'photo', 'Photo Upload'

    form = models.ForeignKey(
        ServiceForm, on_delete=models.CASCADE, related_name='steps'
    )
    title = models.CharField(max_length=200, help_text="e.g. Work Type, Scope")
    description = models.CharField(
        max_length=500, blank=True,
        help_text="e.g. Required — please select an option"
    )
    field_type = models.CharField(
        max_length=20, choices=FieldType.choices, default=FieldType.SINGLE_SELECT
    )
    is_required = models.BooleanField(default=True)
    allow_custom = models.BooleanField(
        default=False,
        help_text="Allow customer to type a custom option (for select types)"
    )
    step_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['step_order']

    def __str__(self):
        return f"{self.form.name} → Step {self.step_order}: {self.title}"


class FormOption(models.Model):
    """Predefined option for a single_select or multi_select step."""
    step = models.ForeignKey(
        FormStep, on_delete=models.CASCADE, related_name='options'
    )
    label = models.CharField(max_length=300)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return self.label


class FormSubmission(models.Model):
    """
    Customer's filled form. Linked to a booking after submission.
    """
    form = models.ForeignKey(
        ServiceForm, on_delete=models.CASCADE, related_name='submissions'
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE, related_name='form_submissions'
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='form_submissions'
    )
    responses = models.JSONField(
        default=list,
        help_text='[{"step_id": 1, "title": "Work Type", "answer": "New Installation"}, ...]'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Submission #{self.id} — {self.form.name} by {self.customer}"