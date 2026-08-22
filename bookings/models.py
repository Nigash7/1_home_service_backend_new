from django.db import models
from django.conf import settings


def normalise_form_responses(raw):
    """
    Turn stored form answers into a clean [{'title', 'answer'}] list.

    Answers arrive as strings, or as lists from multi-select steps. Blank
    answers are dropped so a question the customer skipped doesn't show up as
    an empty row for the admin or the vendor on site.
    """
    responses = []
    for entry in (raw or []):
        if not isinstance(entry, dict):
            continue
        answer = entry.get('answer')
        if isinstance(answer, (list, tuple)):
            answer = ', '.join(str(a) for a in answer if str(a).strip())
        answer = '' if answer is None else str(answer).strip()
        if not answer:
            continue
        responses.append({'title': str(entry.get('title') or ''), 'answer': answer})
    return responses


class Booking(models.Model):
    """
    A customer's service request. Starts as PENDING (no vendor yet).
    Admin manually assigns a vendor -> status becomes ASSIGNED.
    Vendor takes geotagged photo on arrival -> status becomes IN_PROGRESS.
    Vendor marks done -> COMPLETED.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Assignment'
        ASSIGNED = 'ASSIGNED', 'Vendor Assigned'
        IN_PROGRESS = 'IN_PROGRESS', 'Work In Progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PAID = 'PAID', 'Paid'
        PENDING = 'PENDING', 'Payment Pending'

    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='bookings')
    category = models.ForeignKey('services.ServiceCategory', on_delete=models.PROTECT, related_name='bookings')
    subcategory = models.ForeignKey(
        'services.SubCategory', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bookings'
    )
    services_json = models.JSONField(
        default=list, blank=True,
        help_text="List of selected services: [{id, name, price, qty}]"
    )
    discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Total discount applied"
    )
    coupon_code = models.CharField(max_length=50, blank=True)
    discount_details = models.JSONField(
        default=dict, blank=True,
        help_text="Applied discount/coupon details"
    )
    form_submission = models.ForeignKey(
        'service_forms.FormSubmission', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='bookings',
        help_text="Customer's filled form for this booking"
    )
    vendor = models.ForeignKey(
        'vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_bookings'
    )
    assigned_by = models.CharField(
        max_length=20, blank=True, default='',
        help_text="How the vendor was assigned: 'Manual' or 'Auto'"
    )

    preferred_date = models.DateField()
    preferred_time = models.TimeField()

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)

    notes = models.TextField(blank=True, help_text="Customer's description of the issue")

    # Exact location for THIS booking (captured via GPS + map pin-drop in the app).
    # Kept separate from Customer.address because a customer might book for a
    # different location than their saved profile address (e.g. office vs home).
    address_text = models.CharField(max_length=500, blank=True, help_text="Address snapshot for this booking")
    address_state = models.CharField(max_length=100, blank=True)
    address_district = models.CharField(max_length=100, blank=True)
    address_pincode = models.CharField(max_length=10, blank=True)
    customer_phone = models.CharField(max_length=15, blank=True)
    location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Booking #{self.id} - {self.customer} - {self.category} ({self.status})"

    @property
    def filled_forms(self):
        """
        FormSubmission rows for this booking.

        A submission can be linked either way round — the app attaches it via
        `Booking.form_submission` at checkout, while `FormSubmission.booking`
        is the reverse link. Reading only one of them silently loses answers,
        so this merges both and de-duplicates.
        """
        submissions = []
        seen = set()
        for submission in [self.form_submission, *self.form_submissions.all()]:
            if submission is not None and submission.pk not in seen:
                seen.add(submission.pk)
                submissions.append(submission)
        return submissions

    @property
    def form_answer_groups(self):
        """
        Every set of form answers on this booking, grouped by what they describe.

        The app records them two different ways and both are in active use:

          * Cart checkout answers the form locally and embeds the result in
            `services_json[i]['form_data']` — no FormSubmission row is ever
            created, so this is the only place those answers exist.
          * The direct booking flow POSTs a FormSubmission and links it.

        Reading either one alone loses the other's answers completely, which
        is why the answers were invisible for cart bookings.

        Returns [{'title': str, 'responses': [{'title': str, 'answer': str}]}].
        """
        groups = []

        for item in (self.services_json or []):
            if not isinstance(item, dict):
                continue
            responses = normalise_form_responses(item.get('form_data'))
            if responses:
                groups.append({
                    'title': item.get('name') or 'Service',
                    'responses': responses,
                })

        for submission in self.filled_forms:
            responses = normalise_form_responses(submission.responses)
            if responses:
                groups.append({
                    'title': submission.form.name,
                    'responses': responses,
                })

        return groups


class JobStartPhoto(models.Model):
    """
    Proof-of-arrival photo taken by the vendor inside the app.
    Latitude/longitude are captured by the Flutter app's GPS at the moment
    the photo is taken, and stored here alongside the image.
    """
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='start_photo')
    image = models.ImageField(upload_to='job_start_photos/')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    captured_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Start photo for Booking #{self.booking_id}"
