import random
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse
from django.utils import timezone
from django.db import models, transaction
from django.db.models import Avg, Q, Sum

from bookings.models import Booking
from payments.models import Payment
from payments import services as payment_services
from payments.gateway import PaymentError
from vendors import bank_services
from vendors import payout_services as vendor_payout_services
from payments import payoutx
from payments.payoutx import PayoutError
from tenders.models import Tender, TenderBid
from tenders import notifications as tender_notify
from vendors.models import Vendor, VendorDocument
from services.models import ServiceCategory  # adjust to your actual app name

from .notifications import notify_customer
from .decorators import admin_login_required
from services.models import ServiceCategory, SubCategory, Service
from customers.models import Customer
from vendors.distance import haversine_distance
from vendors.round_robin import get_rotation_queue, pick_next_vendor, mark_assigned



User = get_user_model()

OTP_SESSION_KEY = 'dashboard_otp'


def _generate_and_send_otp(request, user):
    otp = f"{random.randint(100000, 999999)}"
    request.session[OTP_SESSION_KEY] = {
        'code': otp,
        'user_id': user.id,
        'expires_at': (timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)).isoformat(),
        'last_sent_at': timezone.now().isoformat(),
    }
    send_mail(
        subject='Your Admin Login OTP',
        message=f'Your OTP code is {otp}. It expires in {settings.OTP_EXPIRY_MINUTES} minutes.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


# ---------- Login ----------

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        try:
            user = User.objects.get(email__iexact=email, is_staff=True)
        except User.DoesNotExist:
            messages.error(request, 'No admin account found with that email.')
            return render(request, 'dashboard/login.html')

        _generate_and_send_otp(request, user)
        request.session['pending_email'] = email
        messages.success(request, 'OTP sent to your email.')
        return redirect('dashboard_verify_otp')

    return render(request, 'dashboard/login.html')


# ---------- Verify OTP ----------

def verify_otp_view(request):
    otp_data = request.session.get(OTP_SESSION_KEY)

    if not otp_data:
        messages.error(request, 'Please log in first.')
        return redirect('dashboard_login')

    if request.method == 'POST':
        entered_otp = request.POST.get('code', '').strip()
        expires_at = timezone.datetime.fromisoformat(otp_data['expires_at'])

        if timezone.now() > expires_at:
            messages.error(request, 'OTP expired. Please request a new one.')
            return redirect('dashboard_login')

        if entered_otp != otp_data['code']:
            messages.error(request, 'Invalid OTP.')
            return render(request, 'dashboard/verify_otp.html')

        request.session['admin_user_id'] = otp_data['user_id']
        del request.session[OTP_SESSION_KEY]
        messages.success(request, 'Logged in successfully.')
        return redirect('dashboard')

    return render(request, 'dashboard/verify_otp.html')


# ---------- Resend OTP ----------

def resend_otp_view(request):
    otp_data = request.session.get(OTP_SESSION_KEY)
    if not otp_data:
        messages.error(request, 'Please log in first.')
        return redirect('dashboard_login')

    last_sent = timezone.datetime.fromisoformat(otp_data['last_sent_at'])
    cooldown = timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)

    if timezone.now() < last_sent + cooldown:
        wait = int((last_sent + cooldown - timezone.now()).total_seconds())
        messages.error(request, f'Please wait {wait}s before resending.')
        return redirect('dashboard_verify_otp')

    user = User.objects.get(id=otp_data['user_id'])
    _generate_and_send_otp(request, user)
    messages.success(request, 'OTP resent.')
    return redirect('dashboard_verify_otp')


# ---------- Logout ----------

def logout_view(request):
    request.session.flush()
    messages.success(request, 'Logged out.')
    return redirect('dashboard_login')


# ---------- Dashboard Home ----------

@admin_login_required
def dashboard_view(request):
    from customers.models import Customer  # adjust import path if different
    from django.db.models import Sum, Count

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    all_bookings = Booking.objects.all()

    # Revenue — adjust 'PAID' to match your actual PaymentStatus choice value
    total_revenue = all_bookings.filter(payment_status='PAID').aggregate(
        total=Sum('amount'))['total'] or 0
    month_revenue = all_bookings.filter(
        payment_status='PAID', created_at__gte=month_start
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Customers
    total_customers = Customer.objects.count()
    new_customers_week = Customer.objects.filter(
        user__date_joined__gte=week_start
    ).count()

    # Top categories by booking count
    top_categories = (
        ServiceCategory.objects.annotate(booking_count=Count('bookings'))
        .filter(booking_count__gt=0)
        .order_by('-booking_count')[:5]
    )

    # 7-day trend for chart
    chart_labels = []
    chart_data = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        chart_labels.append(day.strftime('%b %d'))
        chart_data.append(
            all_bookings.filter(created_at__date=day).count()
        )

    # Paginated recent bookings
    recent_qs = all_bookings.select_related(
        'customer__user', 'category'
    ).order_by('-created_at')
    paginator = Paginator(recent_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'dashboard',
        'total_bookings': all_bookings.count(),
        'today_bookings': all_bookings.filter(created_at__gte=today_start).count(),
        'week_bookings': all_bookings.filter(created_at__gte=week_start).count(),
        'pending_bookings': all_bookings.filter(status='PENDING').count(),
        'total_vendors': Vendor.objects.count(),
        'total_revenue': total_revenue,
        'month_revenue': month_revenue,
        'total_customers': total_customers,
        'new_customers_week': new_customers_week,
        'top_categories': top_categories,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'recent_bookings': page_obj,
        'page_obj': page_obj,
    }
    return render(request, 'dashboard/index.html', context)


# ---------- Bookings List ----------

@admin_login_required
def bookings_list_view(request):
    status = request.GET.get('status', '')
    payment_status = request.GET.get('payment_status', '')
    category_id = request.GET.get('category', '')
    search = request.GET.get('search', '').strip()

    bookings = Booking.objects.select_related(
        'customer__user', 'category', 'vendor__user', 'preferred_vendor__user'
    ).order_by('-created_at')

    if status:
        bookings = bookings.filter(status=status)
    if payment_status:
        bookings = bookings.filter(payment_status=payment_status)
    if category_id:
        bookings = bookings.filter(category_id=category_id)
    if search:
        bookings = bookings.filter(
            models.Q(id__icontains=search) |
            models.Q(customer__user__first_name__icontains=search) |
            models.Q(customer__user__last_name__icontains=search) |
            models.Q(customer_phone__icontains=search)
        )

    paginator = Paginator(bookings, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'bookings',
        'page_obj': page_obj,
        'status_choices': Booking.Status.choices,
        'payment_choices': Booking.PaymentStatus.choices,
        'categories': ServiceCategory.objects.filter(is_active=True),
        'current_status': status,
        'current_payment': payment_status,
        'current_category': category_id,
        'search': search,
    }
    return render(request, 'dashboard/bookings_list.html', context)


# ---------- Booking Detail ----------

@admin_login_required
def booking_detail_view(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related(
            'customer__user', 'category', 'subcategory', 'vendor__user',
            'preferred_vendor__user', 'form_submission__form',
        ).prefetch_related('form_submissions__form'),
        id=booking_id
    )

# Get round-robin rotation queue for assignment
    available_vendors = []
    if booking.status == 'PENDING':
        queue = get_rotation_queue(booking.category, booking)
        for v in queue:
            available_vendors.append({
                'vendor': v,
                'distance': getattr(v, 'distance_km', None),
                'active_jobs': v.active_jobs,
                'last_assigned': v.last_assigned_at,
            })

    context = {
        'admin_user': request.admin_user,
        'active_page': 'bookings',
        'booking': booking,
        'available_vendors': available_vendors,
        'payments': booking.payments.all(),
        # Where a release would actually send the money. Shown next to the
        # button so nobody releases into the dark.
        'payout_account': getattr(booking.vendor, 'bank_account', None)
        if booking.vendor_id else None,
        'payouts_enabled': payoutx.is_enabled(),
        # A booking with real gateway money on it must not also be edited by
        # hand, or our books and Razorpay's start disagreeing.
        'has_gateway_payment': booking.payments.exclude(
            status=Payment.Status.CREATED
        ).exists(),
    }
    return render(request, 'dashboard/booking_detail.html', context)


# ---------- Assign Vendor ----------

@admin_login_required
def assign_vendor_view(request, booking_id):
    if request.method != 'POST':
        return redirect('booking_detail', booking_id=booking_id)

    booking = get_object_or_404(Booking, id=booking_id)
    vendor_id = request.POST.get('vendor_id')

    if not vendor_id:
        messages.error(request, 'Please select a vendor.')
        return redirect('booking_detail', booking_id=booking_id)

    try:
        vendor = Vendor.objects.get(id=vendor_id, verification_status='VERIFIED')
    except Vendor.DoesNotExist:
        messages.error(request, 'Vendor not found or not verified.')
        return redirect('booking_detail', booking_id=booking_id)

    booking.vendor = vendor
    booking.status = 'ASSIGNED'
    booking.assigned_at = timezone.now()
    booking.assigned_by = 'Manual'
    booking.save()

    mark_assigned(vendor)

    # Notify customer
    vendor_name = vendor.user.get_full_name() or vendor.user.username
    notify_customer(
        customer=booking.customer,
        title='Vendor Assigned!',
        body=f'{vendor_name} has been assigned to your {booking.category.name} booking.',
        booking=booking,
    )

    messages.success(request, f'Vendor {vendor_name} assigned successfully.')
    return redirect('booking_detail', booking_id=booking_id)


# ---------- Cancel Booking ----------

@admin_login_required
def cancel_booking_view(request, booking_id):
    if request.method != 'POST':
        return redirect('booking_detail', booking_id=booking_id)

    booking = get_object_or_404(Booking, id=booking_id)
    reason = request.POST.get('reason', '').strip()

    booking.status = 'CANCELLED'
    if reason:
        booking.notes = f"{booking.notes}\n\n[Cancelled by admin: {reason}]"
    booking.save()

    notify_customer(
        customer=booking.customer,
        title='Booking Cancelled',
        body=f'Your {booking.category.name} booking has been cancelled. {reason if reason else ""}',
        booking=booking,
    )

    messages.success(request, 'Booking cancelled.')
    return redirect('booking_detail', booking_id=booking_id)


# ---------- Reschedule Booking ----------

@admin_login_required
def reschedule_booking_view(request, booking_id):
    if request.method != 'POST':
        return redirect('booking_detail', booking_id=booking_id)

    booking = get_object_or_404(Booking, id=booking_id)
    new_date = request.POST.get('new_date')
    new_time = request.POST.get('new_time')

    if not new_date or not new_time:
        messages.error(request, 'Please provide both date and time.')
        return redirect('booking_detail', booking_id=booking_id)

    old_date = booking.preferred_date
    old_time = booking.preferred_time
    booking.preferred_date = new_date
    booking.preferred_time = new_time
    booking.save()

    notify_customer(
        customer=booking.customer,
        title='Booking Rescheduled',
        body=f'Your booking has been rescheduled from {old_date} {old_time} to {new_date} {new_time}.',
        booking=booking,
    )

    messages.success(request, 'Booking rescheduled successfully.')
    return redirect('booking_detail', booking_id=booking_id)


# ---------- Update Payment ----------

@admin_login_required
def update_payment_view(request, booking_id):
    if request.method != 'POST':
        return redirect('booking_detail', booking_id=booking_id)

    booking = get_object_or_404(Booking, id=booking_id)
    amount = request.POST.get('amount')
    payment_status = request.POST.get('payment_status')

    # Once money has actually moved through Razorpay, this booking's payment
    # state belongs to the gateway. Editing it here would silently overwrite
    # what was really collected -- use Refund instead.
    if booking.payments.exclude(status=Payment.Status.CREATED).exists():
        messages.error(
            request,
            'This booking has a gateway payment, so its payment status is set '
            'by Razorpay. Use Refund to send money back.'
        )
        return redirect('booking_detail', booking_id=booking_id)

    if amount:
        booking.amount = amount
    if payment_status:
        booking.payment_status = payment_status
    booking.save()

    messages.success(request, 'Payment updated.')
    return redirect('booking_detail', booking_id=booking_id)


# ---------- Vendors List ----------

@admin_login_required
def vendors_list_view(request):
    verification = request.GET.get('verification', '')
    category_id = request.GET.get('category', '')
    availability = request.GET.get('availability', '')
    search = request.GET.get('search', '').strip()

    vendors = Vendor.objects.select_related('user').prefetch_related(
        'categories', 'subcategories', 'services'
    ).order_by('-id')

    if verification:
        vendors = vendors.filter(verification_status=verification)
    if category_id:
        vendors = vendors.for_category(category_id)
    if availability == 'available':
        vendors = vendors.filter(is_available=True)
    elif availability == 'unavailable':
        vendors = vendors.filter(is_available=False)
    if search:
        vendors = vendors.filter(
            models.Q(user__first_name__icontains=search) |
            models.Q(user__last_name__icontains=search) |
            models.Q(user__phone_number__icontains=search)
        )

    paginator = Paginator(vendors, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'vendors',
        'page_obj': page_obj,
        'categories': ServiceCategory.objects.filter(is_active=True),
        'current_verification': verification,
        'current_category': category_id,
        'current_availability': availability,
        'search': search,
    }
    return render(request, 'dashboard/vendors_list.html', context)


# ---------- Vendor Detail ----------

@admin_login_required
def vendor_detail_view(request, vendor_id):
    vendor = get_object_or_404(
        Vendor.objects.select_related('user').prefetch_related(
            'categories', 'subcategories', 'services', 'documents'
        ),
        id=vendor_id
    )

    # Assigned jobs
    jobs = Booking.objects.filter(vendor=vendor).select_related(
        'customer__user', 'category'
    ).order_by('-created_at')
    jobs_paginator = Paginator(jobs, 10)
    jobs_page = jobs_paginator.get_page(request.GET.get('jobs_page', 1))

    # Reviews
    reviews = vendor.reviews_received.select_related('customer__user', 'service_category').order_by('-created_at')
    reviews_paginator = Paginator(reviews, 10)
    reviews_page = reviews_paginator.get_page(request.GET.get('reviews_page', 1))

    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0

    context = {
        'admin_user': request.admin_user,
        'active_page': 'vendors',
        'vendor': vendor,
        'jobs_page': jobs_page,
        'reviews_page': reviews_page,
        'avg_rating': round(avg_rating, 2),
        'total_reviews': reviews.count(),
        'payout_account': getattr(vendor, 'bank_account', None),
        'bank_changes': vendor.bank_account_changes.all()[:5],
        'payouts_enabled': payoutx.is_enabled(),
    }
    return render(request, 'dashboard/vendor_detail.html', context)


# ---------- Verify Vendor ----------

@admin_login_required
def verify_vendor_view(request, vendor_id):
    if request.method != 'POST':
        return redirect('vendor_detail', vendor_id=vendor_id)

    vendor = get_object_or_404(Vendor, id=vendor_id)
    action = request.POST.get('action')

    if action == 'verify':
        vendor.verification_status = 'VERIFIED'
        messages.success(request, 'Vendor verified.')
    elif action == 'reject':
        vendor.verification_status = 'REJECTED'
        messages.success(request, 'Vendor rejected.')

    vendor.save()
    return redirect('vendor_detail', vendor_id=vendor_id)



# ---------- Categories List ----------

@admin_login_required
def categories_list_view(request):
    categories = ServiceCategory.objects.all().order_by('sort_order', 'name')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'categories': categories,
    }
    return render(request, 'dashboard/categories_list.html', context)


# ---------- Add Category ----------

@admin_login_required
def category_add_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        base_price = request.POST.get('base_price', '0')
        sort_order = request.POST.get('sort_order', '0')
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        icon = request.FILES.get('icon')

        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'dashboard/category_form.html', {
                'admin_user': request.admin_user,
                'active_page': 'categories',
                'is_edit': False,
            })

        try:
            category = ServiceCategory.objects.create(
                name=name,
                description=description,
                base_price=base_price or 0,
                sort_order=sort_order or 0,
                is_active=is_active,
            )
            if icon:
                category.icon = icon
                category.save()
            messages.success(request, f'Category "{name}" created.')
            return redirect('categories_list')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/category_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'is_edit': False,
    })


# ---------- Edit Category ----------

@admin_login_required
def category_edit_view(request, category_id):
    category = get_object_or_404(ServiceCategory, id=category_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        base_price = request.POST.get('base_price', '0')
        sort_order = request.POST.get('sort_order', '0')
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active') == 'on'
        icon = request.FILES.get('icon')

        if not name:
            messages.error(request, 'Category name is required.')
        else:
            category.name = name
            category.description = description
            category.base_price = base_price or 0
            category.sort_order = sort_order or 0
            category.is_active = is_active
            if icon:
                category.icon = icon
            category.save()
            messages.success(request, f'Category "{name}" updated.')
            return redirect('categories_list')

    return render(request, 'dashboard/category_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'is_edit': True,
        'category': category,
    })


# ---------- Delete Category ----------

@admin_login_required
def category_delete_view(request, category_id):
    if request.method != 'POST':
        return redirect('categories_list')

    category = get_object_or_404(ServiceCategory, id=category_id)
    name = category.name
    try:
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')
    except Exception as e:
        messages.error(request, f'Cannot delete — it has bookings or services attached.')

    return redirect('categories_list')  

# ---------- Subcategories List (per category) ----------

@admin_login_required
def subcategories_list_view(request, category_id):
    category = get_object_or_404(ServiceCategory, id=category_id)
    subcategories = category.subcategories.all().order_by('name')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': category,
        'subcategories': subcategories,
    }
    return render(request, 'dashboard/subcategories_list.html', context)


# ---------- Add Subcategory ----------

@admin_login_required
def subcategory_add_view(request, category_id):
    category = get_object_or_404(ServiceCategory, id=category_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        base_price = request.POST.get('base_price', '0')
        is_active = request.POST.get('is_active') == 'on'
        icon = request.FILES.get('icon')

        if not name:
            messages.error(request, 'Subcategory name is required.')
        else:
            try:
                sub = SubCategory.objects.create(
                    category=category,
                    name=name,
                    description=description,
                    base_price=base_price or 0,
                    is_active=is_active,
                )
                if icon:
                    sub.icon = icon
                    sub.save()
                messages.success(request, f'Subcategory "{name}" created.')
                return redirect('subcategories_list', category_id=category.id)
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/subcategory_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': category,
        'is_edit': False,
    })


# ---------- Edit Subcategory ----------

@admin_login_required
def subcategory_edit_view(request, subcategory_id):
    sub = get_object_or_404(SubCategory, id=subcategory_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        base_price = request.POST.get('base_price', '0')
        is_active = request.POST.get('is_active') == 'on'
        icon = request.FILES.get('icon')

        if not name:
            messages.error(request, 'Subcategory name is required.')
        else:
            sub.name = name
            sub.description = description
            sub.base_price = base_price or 0
            sub.is_active = is_active
            if icon:
                sub.icon = icon
            sub.save()
            messages.success(request, f'Subcategory "{name}" updated.')
            return redirect('subcategories_list', category_id=sub.category.id)

    return render(request, 'dashboard/subcategory_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': sub.category,
        'subcategory': sub,
        'is_edit': True,
    })


# ---------- Delete Subcategory ----------

@admin_login_required
def subcategory_delete_view(request, subcategory_id):
    if request.method != 'POST':
        sub = get_object_or_404(SubCategory, id=subcategory_id)
        return redirect('subcategories_list', category_id=sub.category.id)

    sub = get_object_or_404(SubCategory, id=subcategory_id)
    category_id = sub.category.id
    name = sub.name

    try:
        sub.delete()
        messages.success(request, f'Subcategory "{name}" deleted.')
    except Exception as e:
        messages.error(request, 'Cannot delete — it has services or bookings attached.')

    return redirect('subcategories_list', category_id=category_id)

# ---------- Services List (per category or subcategory) ----------

@admin_login_required
def services_list_view(request, category_id=None, subcategory_id=None):
    category = None
    subcategory = None
    services = Service.objects.select_related('category', 'subcategory').all()

    if subcategory_id:
        subcategory = get_object_or_404(SubCategory, id=subcategory_id)
        category = subcategory.category
        services = services.filter(subcategory=subcategory)
    elif category_id:
        category = get_object_or_404(ServiceCategory, id=category_id)
        # Services directly under category (no subcategory)
        services = services.filter(category=category, subcategory__isnull=True)

    services = services.order_by('name')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': category,
        'subcategory': subcategory,
        'services': services,
    }
    return render(request, 'dashboard/services_list.html', context)


# ---------- Add Service ----------

@admin_login_required
def service_add_view(request, category_id=None, subcategory_id=None):
    category = None
    subcategory = None

    if subcategory_id:
        subcategory = get_object_or_404(SubCategory, id=subcategory_id)
        category = subcategory.category
    elif category_id:
        category = get_object_or_404(ServiceCategory, id=category_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '0')
        duration_minutes = request.POST.get('duration_minutes', '60')
        is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')

        if not name:
            messages.error(request, 'Service name is required.')
        else:
            try:
                svc = Service.objects.create(
                    category=category,
                    subcategory=subcategory,
                    name=name,
                    description=description,
                    price=price or 0,
                    duration_minutes=duration_minutes or 60,
                    is_active=is_active,
                )
                if image:
                    svc.image = image
                    svc.save()
                messages.success(request, f'Service "{name}" created.')
                if subcategory:
                    return redirect('services_list_sub', subcategory_id=subcategory.id)
                return redirect('services_list_cat', category_id=category.id)
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/service_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': category,
        'subcategory': subcategory,
        'is_edit': False,
    })


# ---------- Edit Service ----------

@admin_login_required
def service_edit_view(request, service_id):
    svc = get_object_or_404(Service, id=service_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '0')
        duration_minutes = request.POST.get('duration_minutes', '60')
        is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')

        if not name:
            messages.error(request, 'Service name is required.')
        else:
            svc.name = name
            svc.description = description
            svc.price = price or 0
            svc.duration_minutes = duration_minutes or 60
            svc.is_active = is_active
            if image:
                svc.image = image
            svc.save()
            messages.success(request, f'Service "{name}" updated.')
            if svc.subcategory:
                return redirect('services_list_sub', subcategory_id=svc.subcategory.id)
            return redirect('services_list_cat', category_id=svc.category.id)

    return render(request, 'dashboard/service_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'categories',
        'category': svc.category,
        'subcategory': svc.subcategory,
        'service': svc,
        'is_edit': True,
    })


# ---------- Delete Service ----------

@admin_login_required
def service_delete_view(request, service_id):
    if request.method != 'POST':
        svc = get_object_or_404(Service, id=service_id)
        if svc.subcategory:
            return redirect('services_list_sub', subcategory_id=svc.subcategory.id)
        return redirect('services_list_cat', category_id=svc.category.id)

    svc = get_object_or_404(Service, id=service_id)
    category_id = svc.category.id
    subcategory_id = svc.subcategory.id if svc.subcategory else None
    name = svc.name

    try:
        svc.delete()
        messages.success(request, f'Service "{name}" deleted.')
    except Exception as e:
        messages.error(request, 'Cannot delete — it has bookings attached.')

    if subcategory_id:
        return redirect('services_list_sub', subcategory_id=subcategory_id)
    return redirect('services_list_cat', category_id=category_id)  

from branding.models import AppBranding


# ---------- App Branding (logos shown inside the mobile apps) ----------

@admin_login_required
def branding_view(request):
    if request.method == 'POST':
        app = request.POST.get('app', '')
        if app not in AppBranding.App.values:
            messages.error(request, 'Unknown app.')
            return redirect('branding')

        logo = request.FILES.get('logo')
        branding = AppBranding.objects.filter(app=app).first()

        if branding is None and not logo:
            messages.error(request, 'Upload a logo to set up this app.')
            return redirect('branding')

        try:
            if branding is None:
                branding = AppBranding(app=app)
            if logo:
                branding.logo = logo
            branding.app_name = request.POST.get('app_name', '').strip()
            branding.tagline = request.POST.get('tagline', '').strip()
            branding.save()
            messages.success(request, f'{branding.get_app_display()} branding updated.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('branding')

    existing = {b.app: b for b in AppBranding.objects.all()}
    return render(request, 'dashboard/branding.html', {
        'admin_user': request.admin_user,
        'active_page': 'branding',
        'customer_branding': existing.get(AppBranding.App.CUSTOMER),
        'vendor_branding': existing.get(AppBranding.App.VENDOR),
    })


from referrals.models import Referral, ReferralProgram


# ---------- Referral Program Settings ----------

REFERRAL_TEXT_FIELDS = [
    'home_banner_title', 'home_banner_subtitle',
    'profile_card_title', 'profile_card_subtitle', 'profile_card_button',
    'screen_title', 'screen_description',
    'step_one', 'step_two', 'step_three',
    'share_message', 'terms',
]


@admin_login_required
def referral_settings_view(request):
    program = ReferralProgram.get_solo()

    if request.method == 'POST':
        try:
            program.referrer_reward = request.POST.get('referrer_reward') or 0
            program.friend_reward = request.POST.get('friend_reward') or 0
            program.is_active = request.POST.get('is_active') == 'on'
            for field in REFERRAL_TEXT_FIELDS:
                setattr(program, field, request.POST.get(field, '').strip())
            program.save()
            messages.success(request, 'Referral programme updated.')
            return redirect('referral_settings')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/referral_settings.html', {
        'admin_user': request.admin_user,
        'active_page': 'referrals',
        'program': program,
    })


# ---------- Referral Ledger ----------

@admin_login_required
def referrals_list_view(request):
    status = request.GET.get('status', '')
    referrals = Referral.objects.select_related(
        'referrer__user', 'referred_customer__user', 'first_booking'
    )
    if status:
        referrals = referrals.filter(status=status)

    all_referrals = Referral.objects.all()
    owed = all_referrals.filter(status=Referral.Status.EARNED)

    return render(request, 'dashboard/referrals_list.html', {
        'admin_user': request.admin_user,
        'active_page': 'referrals',
        'referrals': referrals,
        'status_filter': status,
        'status_choices': Referral.Status.choices,
        'total_count': all_referrals.count(),
        'pending_count': all_referrals.filter(status=Referral.Status.PENDING).count(),
        'owed_count': owed.count(),
        'owed_amount': owed.aggregate(total=Sum('reward_amount'))['total'] or 0,
    })


@admin_login_required
def referral_settle_view(request, referral_id):
    if request.method != 'POST':
        return redirect('referrals_list')

    referral = get_object_or_404(Referral, id=referral_id)
    if referral.status != Referral.Status.EARNED:
        messages.error(request, 'Only an earned referral can be settled.')
    else:
        referral.mark_settled(request.POST.get('note', '').strip())
        messages.success(request, 'Referral marked as settled.')
    return redirect('referrals_list')


from promotions.models import SpotlightBanner, HeaderBanner, PromoCard


# ---------- Promo Cards List ----------

@admin_login_required
def promo_cards_list_view(request):
    cards = PromoCard.objects.select_related(
        'category', 'subcategory', 'after_section'
    ).order_by('sort_order', '-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'promo_cards',
        'cards': cards,
    }
    return render(request, 'dashboard/promo_cards_list.html', context)


def _pro_vendors_for_forms():
    """Pro vendors a banner may be pointed at — verified ones only."""
    return Vendor.objects.pro().select_related('user').order_by(
        'pro_sort_order', 'user__first_name'
    )


def _promo_card_form_context(request, card=None):
    from home_sections.models import HomeSection
    return {
        'admin_user': request.admin_user,
        'active_page': 'promo_cards',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'home_sections': HomeSection.objects.filter(is_active=True),
        'pro_vendors': _pro_vendors_for_forms(),
        'placement_choices': PromoCard.PLACEMENT_CHOICES,
        'card': card,
        'is_edit': card is not None,
    }


def _read_promo_card_post(request):
    """Pull the shared promo-card fields off the POST, returning (data, error)."""
    placement = request.POST.get('placement') or PromoCard.PLACEMENT_AFTER
    after_section_id = request.POST.get('after_section') or None

    valid_placements = [c[0] for c in PromoCard.PLACEMENT_CHOICES]
    if placement not in valid_placements:
        return None, 'Please choose a valid placement.'
    if placement == PromoCard.PLACEMENT_AFTER_SECTION and not after_section_id:
        return None, 'Pick which home section this card should follow.'

    data = {
        'badge_text': request.POST.get('badge_text', '').strip(),
        'badge_color': request.POST.get('badge_color', '').strip() or '#9C1458',
        'title': request.POST.get('title', '').strip(),
        'subtitle': request.POST.get('subtitle', '').strip(),
        'button_text': request.POST.get('button_text', '').strip() or 'Book now',
        'category_id': request.POST.get('category') or None,
        'subcategory_id': request.POST.get('subcategory') or None,
        'pro_vendor_id': request.POST.get('pro_vendor') or None,
        'placement': placement,
        'after_section_id': after_section_id,
        'sort_order': request.POST.get('sort_order', '0') or 0,
        'is_active': request.POST.get('is_active') == 'on',
    }
    if not data['title']:
        return None, 'Title is required.'
    return data, None


# ---------- Add Promo Card ----------

@admin_login_required
def promo_card_add_view(request):
    if request.method == 'POST':
        image = request.FILES.get('image')
        data, error = _read_promo_card_post(request)

        if error:
            messages.error(request, error)
        elif not image:
            messages.error(request, 'Image is required.')
        else:
            try:
                PromoCard.objects.create(image=image, **data)
                messages.success(request, f'Promo card "{data["title"]}" created.')
                return redirect('promo_cards_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/promo_card_form.html', _promo_card_form_context(request))


# ---------- Edit Promo Card ----------

@admin_login_required
def promo_card_edit_view(request, card_id):
    card = get_object_or_404(PromoCard, id=card_id)

    if request.method == 'POST':
        data, error = _read_promo_card_post(request)

        if error:
            messages.error(request, error)
        else:
            for field, value in data.items():
                setattr(card, field, value)
            image = request.FILES.get('image')
            if image:
                card.image = image
            card.save()
            messages.success(request, f'Promo card "{card.title}" updated.')
            return redirect('promo_cards_list')

    return render(request, 'dashboard/promo_card_form.html', _promo_card_form_context(request, card))


# ---------- Delete Promo Card ----------

@admin_login_required
def promo_card_delete_view(request, card_id):
    if request.method != 'POST':
        return redirect('promo_cards_list')

    card = get_object_or_404(PromoCard, id=card_id)
    title = card.title
    card.delete()
    messages.success(request, f'Promo card "{title}" deleted.')
    return redirect('promo_cards_list')


# ---------- Toggle Promo Card Active ----------

@admin_login_required
def promo_card_toggle_view(request, card_id):
    if request.method != 'POST':
        return redirect('promo_cards_list')

    card = get_object_or_404(PromoCard, id=card_id)
    card.is_active = not card.is_active
    card.save()
    status = 'activated' if card.is_active else 'deactivated'
    messages.success(request, f'Promo card {status}.')
    return redirect('promo_cards_list')


# ---------- Header Banners (hero carousel) List ----------

@admin_login_required
def header_banners_list_view(request):
    banners = HeaderBanner.objects.select_related('category', 'subcategory').order_by('sort_order', '-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'header_banners',
        'banners': banners,
    }
    return render(request, 'dashboard/header_banners_list.html', context)


# ---------- Add Header Banner ----------

@admin_login_required
def header_banner_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        pro_vendor_id = request.POST.get('pro_vendor') or None
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')

        if not image:
            messages.error(request, 'Image is required.')
        else:
            try:
                HeaderBanner.objects.create(
                    image=image,
                    title=title,
                    subtitle=subtitle,
                    category_id=category_id,
                    subcategory_id=subcategory_id,
                    pro_vendor_id=pro_vendor_id,
                    sort_order=sort_order or 0,
                    is_active=is_active,
                )
                messages.success(request, 'Header banner created.')
                return redirect('header_banners_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/header_banner_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'header_banners',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'pro_vendors': _pro_vendors_for_forms(),
        'is_edit': False,
    })


# ---------- Edit Header Banner ----------

@admin_login_required
def header_banner_edit_view(request, banner_id):
    banner = get_object_or_404(HeaderBanner, id=banner_id)

    if request.method == 'POST':
        banner.title = request.POST.get('title', '').strip()
        banner.subtitle = request.POST.get('subtitle', '').strip()
        banner.category_id = request.POST.get('category') or None
        banner.subcategory_id = request.POST.get('subcategory') or None
        banner.pro_vendor_id = request.POST.get('pro_vendor') or None
        banner.sort_order = request.POST.get('sort_order', '0') or 0
        banner.is_active = request.POST.get('is_active') == 'on'
        image = request.FILES.get('image')
        if image:
            banner.image = image
        banner.save()
        messages.success(request, 'Header banner updated.')
        return redirect('header_banners_list')

    return render(request, 'dashboard/header_banner_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'header_banners',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'pro_vendors': _pro_vendors_for_forms(),
        'banner': banner,
        'is_edit': True,
    })


# ---------- Delete Header Banner ----------

@admin_login_required
def header_banner_delete_view(request, banner_id):
    if request.method != 'POST':
        return redirect('header_banners_list')

    banner = get_object_or_404(HeaderBanner, id=banner_id)
    banner.delete()
    messages.success(request, 'Header banner deleted.')
    return redirect('header_banners_list')


# ---------- Toggle Header Banner Active ----------

@admin_login_required
def header_banner_toggle_view(request, banner_id):
    if request.method != 'POST':
        return redirect('header_banners_list')

    banner = get_object_or_404(HeaderBanner, id=banner_id)
    banner.is_active = not banner.is_active
    banner.save()
    status = 'activated' if banner.is_active else 'deactivated'
    messages.success(request, f'Header banner {status}.')
    return redirect('header_banners_list')


# ---------- Spotlights List ----------

@admin_login_required
def spotlights_list_view(request):
    spotlights = SpotlightBanner.objects.select_related('category', 'subcategory').order_by('sort_order', '-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'spotlights',
        'spotlights': spotlights,
    }
    return render(request, 'dashboard/spotlights_list.html', context)


# ---------- Add Spotlight ----------

@admin_login_required
def spotlight_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        button_text = request.POST.get('button_text', 'Book now').strip()
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        pro_vendor_id = request.POST.get('pro_vendor') or None
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        background_image = request.FILES.get('background_image')

        if not title:
            messages.error(request, 'Title is required.')
        elif not background_image:
            messages.error(request, 'Background image is required.')
        else:
            try:
                banner = SpotlightBanner.objects.create(
                    title=title,
                    subtitle=subtitle,
                    button_text=button_text or 'Book now',
                    category_id=category_id,
                    subcategory_id=subcategory_id,
                    pro_vendor_id=pro_vendor_id,
                    sort_order=sort_order or 0,
                    is_active=is_active,
                    background_image=background_image,
                )
                messages.success(request, f'Spotlight "{title}" created.')
                return redirect('spotlights_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/spotlight_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'spotlights',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'pro_vendors': _pro_vendors_for_forms(),
        'is_edit': False,
    })


# ---------- Edit Spotlight ----------

@admin_login_required
def spotlight_edit_view(request, spotlight_id):
    banner = get_object_or_404(SpotlightBanner, id=spotlight_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        button_text = request.POST.get('button_text', 'Book now').strip()
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        pro_vendor_id = request.POST.get('pro_vendor') or None
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        background_image = request.FILES.get('background_image')

        if not title:
            messages.error(request, 'Title is required.')
        else:
            banner.title = title
            banner.subtitle = subtitle
            banner.button_text = button_text or 'Book now'
            banner.category_id = category_id
            banner.subcategory_id = subcategory_id
            banner.pro_vendor_id = pro_vendor_id
            banner.sort_order = sort_order or 0
            banner.is_active = is_active
            if background_image:
                banner.background_image = background_image
            banner.save()
            messages.success(request, f'Spotlight "{title}" updated.')
            return redirect('spotlights_list')

    return render(request, 'dashboard/spotlight_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'spotlights',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'pro_vendors': _pro_vendors_for_forms(),
        'banner': banner,
        'is_edit': True,
    })


# ---------- Delete Spotlight ----------

@admin_login_required
def spotlight_delete_view(request, spotlight_id):
    if request.method != 'POST':
        return redirect('spotlights_list')

    banner = get_object_or_404(SpotlightBanner, id=spotlight_id)
    title = banner.title
    banner.delete()
    messages.success(request, f'Spotlight "{title}" deleted.')
    return redirect('spotlights_list')


# ---------- Toggle Spotlight Active ----------

@admin_login_required
def spotlight_toggle_view(request, spotlight_id):
    if request.method != 'POST':
        return redirect('spotlights_list')

    banner = get_object_or_404(SpotlightBanner, id=spotlight_id)
    banner.is_active = not banner.is_active
    banner.save()
    status = 'activated' if banner.is_active else 'deactivated'
    messages.success(request, f'Spotlight {status}.')
    return redirect('spotlights_list') 


from home_sections.models import HomeSection, HomeSectionItem


# ---------- Home Sections List ----------

@admin_login_required
def home_sections_list_view(request):
    sections = HomeSection.objects.prefetch_related('items__service').order_by('sort_order', '-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'home_sections',
        'sections': sections,
    }
    return render(request, 'dashboard/home_sections_list.html', context)


# ---------- Add Home Section ----------

@admin_login_required
def home_section_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        home_display_limit = request.POST.get('home_display_limit', '3')
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'

        if not title:
            messages.error(request, 'Title is required.')
        else:
            section = HomeSection.objects.create(
                title=title,
                subtitle=subtitle,
                home_display_limit=home_display_limit or 3,
                sort_order=sort_order or 0,
                is_active=is_active,
            )
            messages.success(request, f'Section "{title}" created.')
            return redirect('home_section_detail', section_id=section.id)

    return render(request, 'dashboard/home_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'home_sections',
        'is_edit': False,
    })


# ---------- Edit Home Section ----------

@admin_login_required
def home_section_edit_view(request, section_id):
    section = get_object_or_404(HomeSection, id=section_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        home_display_limit = request.POST.get('home_display_limit', '3')
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'

        if not title:
            messages.error(request, 'Title is required.')
        else:
            section.title = title
            section.subtitle = subtitle
            section.home_display_limit = home_display_limit or 3
            section.sort_order = sort_order or 0
            section.is_active = is_active
            section.save()
            messages.success(request, f'Section updated.')
            return redirect('home_section_detail', section_id=section.id)

    return render(request, 'dashboard/home_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'home_sections',
        'section': section,
        'is_edit': True,
    })


# ---------- Delete Home Section ----------

@admin_login_required
def home_section_delete_view(request, section_id):
    if request.method != 'POST':
        return redirect('home_sections_list')

    section = get_object_or_404(HomeSection, id=section_id)
    title = section.title
    section.delete()
    messages.success(request, f'Section "{title}" deleted.')
    return redirect('home_sections_list')


# ---------- Home Section Detail (Manage Items) ----------

@admin_login_required
def home_section_detail_view(request, section_id):
    section = get_object_or_404(HomeSection, id=section_id)
    items = section.items.select_related('service__category', 'service__subcategory').order_by('sort_order')

    # Services not already in this section
    existing_service_ids = items.values_list('service_id', flat=True)
    available_services = Service.objects.filter(is_active=True).exclude(
        id__in=existing_service_ids
    ).select_related('category', 'subcategory').order_by('category__name', 'name')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'home_sections',
        'section': section,
        'items': items,
        'available_services': available_services,
    }
    return render(request, 'dashboard/home_section_detail.html', context)


# ---------- Add Item to Section ----------

@admin_login_required
def home_section_add_item_view(request, section_id):
    if request.method != 'POST':
        return redirect('home_section_detail', section_id=section_id)

    section = get_object_or_404(HomeSection, id=section_id)
    service_id = request.POST.get('service_id')

    if not service_id:
        messages.error(request, 'Please select a service.')
        return redirect('home_section_detail', section_id=section_id)

    try:
        service = Service.objects.get(id=service_id)
        max_order = section.items.count()
        HomeSectionItem.objects.create(
            section=section,
            service=service,
            sort_order=max_order,
        )
        messages.success(request, f'"{service.name}" added.')
    except Service.DoesNotExist:
        messages.error(request, 'Service not found.')
    except Exception as e:
        messages.error(request, f'Error: {e}')

    return redirect('home_section_detail', section_id=section_id)


# ---------- Remove Item from Section ----------

@admin_login_required
def home_section_remove_item_view(request, item_id):
    if request.method != 'POST':
        return redirect('home_sections_list')

    item = get_object_or_404(HomeSectionItem, id=item_id)
    section_id = item.section.id
    item.delete()
    messages.success(request, 'Service removed from section.')
    return redirect('home_section_detail', section_id=section_id)


# ---------- Reorder Items ----------

@admin_login_required
def home_section_reorder_view(request, item_id):
    if request.method != 'POST':
        return redirect('home_sections_list')

    item = get_object_or_404(HomeSectionItem, id=item_id)
    direction = request.POST.get('direction')

    if direction == 'up':
        prev_item = HomeSectionItem.objects.filter(
            section=item.section, sort_order__lt=item.sort_order
        ).order_by('-sort_order').first()
        if prev_item:
            item.sort_order, prev_item.sort_order = prev_item.sort_order, item.sort_order
            item.save()
            prev_item.save()
    elif direction == 'down':
        next_item = HomeSectionItem.objects.filter(
            section=item.section, sort_order__gt=item.sort_order
        ).order_by('sort_order').first()
        if next_item:
            item.sort_order, next_item.sort_order = next_item.sort_order, item.sort_order
            item.save()
            next_item.save()

    return redirect('home_section_detail', section_id=item.section.id) 

from curations.models import CurationSection, CurationItem


# ---------- Curations List ----------

@admin_login_required
def curations_list_view(request):
    sections = CurationSection.objects.prefetch_related('items__service').order_by('sort_order', '-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'sections': sections,
    }
    return render(request, 'dashboard/curations_list.html', context)


# ---------- Add Curation Section ----------

@admin_login_required
def curation_section_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'

        if not title:
            messages.error(request, 'Title is required.')
        else:
            section = CurationSection.objects.create(
                title=title,
                subtitle=subtitle,
                sort_order=sort_order or 0,
                is_active=is_active,
            )
            messages.success(request, f'Curation section "{title}" created.')
            return redirect('curation_section_detail', section_id=section.id)

    return render(request, 'dashboard/curation_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'is_edit': False,
    })


# ---------- Edit Curation Section ----------

@admin_login_required
def curation_section_edit_view(request, section_id):
    section = get_object_or_404(CurationSection, id=section_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subtitle = request.POST.get('subtitle', '').strip()
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'

        if not title:
            messages.error(request, 'Title is required.')
        else:
            section.title = title
            section.subtitle = subtitle
            section.sort_order = sort_order or 0
            section.is_active = is_active
            section.save()
            messages.success(request, 'Section updated.')
            return redirect('curation_section_detail', section_id=section.id)

    return render(request, 'dashboard/curation_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'section': section,
        'is_edit': True,
    })


# ---------- Delete Curation Section ----------

@admin_login_required
def curation_section_delete_view(request, section_id):
    if request.method != 'POST':
        return redirect('curations_list')

    section = get_object_or_404(CurationSection, id=section_id)
    title = section.title
    section.delete()
    messages.success(request, f'Section "{title}" deleted.')
    return redirect('curations_list')


# ---------- Curation Section Detail (Manage Videos) ----------

@admin_login_required
def curation_section_detail_view(request, section_id):
    section = get_object_or_404(CurationSection, id=section_id)
    items = section.items.select_related('service__category').order_by('sort_order')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'section': section,
        'items': items,
    }
    return render(request, 'dashboard/curation_section_detail.html', context)


# ---------- Add Curation Item (Video) ----------

@admin_login_required
def curation_item_add_view(request, section_id):
    section = get_object_or_404(CurationSection, id=section_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        service_id = request.POST.get('service') or None
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        thumbnail = request.FILES.get('thumbnail')
        video = request.FILES.get('video')

        if not title:
            messages.error(request, 'Title is required.')
        elif not thumbnail:
            messages.error(request, 'Thumbnail is required.')
        elif not video:
            messages.error(request, 'Video file is required.')
        else:
            try:
                CurationItem.objects.create(
                    section=section,
                    title=title,
                    thumbnail=thumbnail,
                    video=video,
                    service_id=service_id,
                    sort_order=sort_order or 0,
                    is_active=is_active,
                )
                messages.success(request, f'Video "{title}" added.')
                return redirect('curation_section_detail', section_id=section.id)
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/curation_item_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'section': section,
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'is_edit': False,
    })


# ---------- Edit Curation Item ----------

@admin_login_required
def curation_item_edit_view(request, item_id):
    item = get_object_or_404(CurationItem, id=item_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        service_id = request.POST.get('service') or None
        sort_order = request.POST.get('sort_order', '0')
        is_active = request.POST.get('is_active') == 'on'
        thumbnail = request.FILES.get('thumbnail')
        video = request.FILES.get('video')

        if not title:
            messages.error(request, 'Title is required.')
        else:
            item.title = title
            item.service_id = service_id
            item.sort_order = sort_order or 0
            item.is_active = is_active
            if thumbnail:
                item.thumbnail = thumbnail
            if video:
                item.video = video
            item.save()
            messages.success(request, 'Video updated.')
            return redirect('curation_section_detail', section_id=item.section.id)

    return render(request, 'dashboard/curation_item_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'curations',
        'section': item.section,
        'item': item,
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'is_edit': True,
    })


# ---------- Delete Curation Item ----------

@admin_login_required
def curation_item_delete_view(request, item_id):
    if request.method != 'POST':
        return redirect('curations_list')

    item = get_object_or_404(CurationItem, id=item_id)
    section_id = item.section.id
    title = item.title
    item.delete()
    messages.success(request, f'"{title}" deleted.')
    return redirect('curation_section_detail', section_id=section_id)   


from service_forms.models import ServiceForm, FormStep, FormOption, FormSubmission


# ---------- Forms List ----------

@admin_login_required
def forms_list_view(request):
    forms = ServiceForm.objects.select_related(
        'category', 'subcategory', 'service'
    ).prefetch_related('steps').order_by('-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'forms': forms,
    }
    return render(request, 'dashboard/forms_list.html', context)


# ---------- Add Form ----------

@admin_login_required
def form_add_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        service_id = request.POST.get('service') or None
        is_active = request.POST.get('is_active') == 'on'

        if not name:
            messages.error(request, 'Form name is required.')
        elif not (category_id or subcategory_id or service_id):
            messages.error(request, 'Please link the form to a category, subcategory, or service.')
        else:
            form = ServiceForm.objects.create(
                name=name,
                category_id=category_id,
                subcategory_id=subcategory_id,
                service_id=service_id,
                is_active=is_active,
            )
            messages.success(request, f'Form "{name}" created. Now add steps.')
            return redirect('form_detail', form_id=form.id)

    return render(request, 'dashboard/form_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'is_edit': False,
    })


# ---------- Edit Form ----------

@admin_login_required
def form_edit_view(request, form_id):
    form = get_object_or_404(ServiceForm, id=form_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        service_id = request.POST.get('service') or None
        is_active = request.POST.get('is_active') == 'on'

        if not name:
            messages.error(request, 'Form name is required.')
        else:
            form.name = name
            form.category_id = category_id
            form.subcategory_id = subcategory_id
            form.service_id = service_id
            form.is_active = is_active
            form.save()
            messages.success(request, 'Form updated.')
            return redirect('form_detail', form_id=form.id)

    return render(request, 'dashboard/form_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'form': form,
        'is_edit': True,
    })


# ---------- Delete Form ----------

@admin_login_required
def form_delete_view(request, form_id):
    if request.method != 'POST':
        return redirect('forms_list')

    form = get_object_or_404(ServiceForm, id=form_id)
    name = form.name
    form.delete()
    messages.success(request, f'Form "{name}" deleted.')
    return redirect('forms_list')


# ---------- Form Detail (Manage Steps) ----------

@admin_login_required
def form_detail_view(request, form_id):
    form = get_object_or_404(ServiceForm, id=form_id)
    steps = form.steps.prefetch_related('options').order_by('step_order')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'form': form,
        'steps': steps,
        'submissions_count': form.submissions.count(),
    }
    return render(request, 'dashboard/form_detail.html', context)


# ---------- Add Step ----------

@admin_login_required
def form_step_add_view(request, form_id):
    form = get_object_or_404(ServiceForm, id=form_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        field_type = request.POST.get('field_type', 'single_select')
        is_required = request.POST.get('is_required') == 'on'
        allow_custom = request.POST.get('allow_custom') == 'on'

        if not title:
            messages.error(request, 'Step title is required.')
        else:
            next_order = (form.steps.count() or 0) + 1
            step = FormStep.objects.create(
                form=form,
                title=title,
                description=description,
                field_type=field_type,
                is_required=is_required,
                allow_custom=allow_custom,
                step_order=next_order,
            )

            # Add options if select type
            if field_type in ['single_select', 'multi_select']:
                options_text = request.POST.get('options', '').strip()
                if options_text:
                    for idx, line in enumerate(options_text.split('\n')):
                        line = line.strip()
                        if line:
                            FormOption.objects.create(
                                step=step, label=line, sort_order=idx
                            )

            messages.success(request, f'Step "{title}" added.')
            return redirect('form_detail', form_id=form.id)

    return render(request, 'dashboard/form_step_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'form': form,
        'field_type_choices': FormStep.FieldType.choices,
        'is_edit': False,
    })


# ---------- Edit Step ----------

@admin_login_required
def form_step_edit_view(request, step_id):
    step = get_object_or_404(FormStep, id=step_id)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        field_type = request.POST.get('field_type', 'single_select')
        is_required = request.POST.get('is_required') == 'on'
        allow_custom = request.POST.get('allow_custom') == 'on'

        if not title:
            messages.error(request, 'Step title is required.')
        else:
            step.title = title
            step.description = description
            step.field_type = field_type
            step.is_required = is_required
            step.allow_custom = allow_custom
            step.save()

            # Replace options
            if field_type in ['single_select', 'multi_select']:
                options_text = request.POST.get('options', '').strip()
                step.options.all().delete()
                if options_text:
                    for idx, line in enumerate(options_text.split('\n')):
                        line = line.strip()
                        if line:
                            FormOption.objects.create(
                                step=step, label=line, sort_order=idx
                            )
            else:
                step.options.all().delete()

            messages.success(request, 'Step updated.')
            return redirect('form_detail', form_id=step.form.id)

    options_text = '\n'.join(step.options.values_list('label', flat=True))

    return render(request, 'dashboard/form_step_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'form': step.form,
        'step': step,
        'options_text': options_text,
        'field_type_choices': FormStep.FieldType.choices,
        'is_edit': True,
    })


# ---------- Delete Step ----------

@admin_login_required
def form_step_delete_view(request, step_id):
    if request.method != 'POST':
        return redirect('forms_list')

    step = get_object_or_404(FormStep, id=step_id)
    form_id = step.form.id
    step.delete()
    messages.success(request, 'Step deleted.')
    return redirect('form_detail', form_id=form_id)


# ---------- Reorder Step ----------

@admin_login_required
def form_step_reorder_view(request, step_id):
    if request.method != 'POST':
        return redirect('forms_list')

    step = get_object_or_404(FormStep, id=step_id)
    direction = request.POST.get('direction')

    if direction == 'up':
        prev = FormStep.objects.filter(
            form=step.form, step_order__lt=step.step_order
        ).order_by('-step_order').first()
        if prev:
            step.step_order, prev.step_order = prev.step_order, step.step_order
            step.save()
            prev.save()
    elif direction == 'down':
        nxt = FormStep.objects.filter(
            form=step.form, step_order__gt=step.step_order
        ).order_by('step_order').first()
        if nxt:
            step.step_order, nxt.step_order = nxt.step_order, step.step_order
            step.save()
            nxt.save()

    return redirect('form_detail', form_id=step.form.id)


# ---------- Form Submissions ----------

@admin_login_required
def form_submissions_view(request, form_id):
    form = get_object_or_404(ServiceForm, id=form_id)
    submissions = form.submissions.select_related(
        'customer__user', 'booking'
    ).order_by('-submitted_at')

    paginator = Paginator(submissions, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'forms',
        'form': form,
        'page_obj': page_obj,
    }
    return render(request, 'dashboard/form_submissions.html', context)  

from discounts.models import Discount, Coupon, CouponUsage


# ---------- Discounts List ----------

@admin_login_required
def discounts_list_view(request):
    discounts = Discount.objects.select_related('category', 'subcategory', 'service').order_by('-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'discounts',
        'discounts': discounts,
    }
    return render(request, 'dashboard/discounts_list.html', context)


# ---------- Add Discount ----------

@admin_login_required
def discount_add_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', 'PERCENTAGE')
        value = request.POST.get('value', '0')
        max_discount = request.POST.get('max_discount') or None
        min_order_amount = request.POST.get('min_order_amount', '0')
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        service_id = request.POST.get('service') or None
        valid_from = request.POST.get('valid_from') or None
        valid_until = request.POST.get('valid_until') or None
        is_active = request.POST.get('is_active') == 'on'

        if not name or not value:
            messages.error(request, 'Name and value are required.')
        else:
            try:
                Discount.objects.create(
                    name=name,
                    description=description,
                    discount_type=discount_type,
                    value=value,
                    max_discount=max_discount,
                    min_order_amount=min_order_amount or 0,
                    category_id=category_id,
                    subcategory_id=subcategory_id,
                    service_id=service_id,
                    valid_from=valid_from or timezone.now(),
                    valid_until=valid_until,
                    is_active=is_active,
                )
                messages.success(request, f'Discount "{name}" created.')
                return redirect('discounts_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/discount_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'discounts',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'is_edit': False,
    })


# ---------- Edit Discount ----------

@admin_login_required
def discount_edit_view(request, discount_id):
    discount = get_object_or_404(Discount, id=discount_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', 'PERCENTAGE')
        value = request.POST.get('value', '0')
        max_discount = request.POST.get('max_discount') or None
        min_order_amount = request.POST.get('min_order_amount', '0')
        category_id = request.POST.get('category') or None
        subcategory_id = request.POST.get('subcategory') or None
        service_id = request.POST.get('service') or None
        valid_from = request.POST.get('valid_from') or None
        valid_until = request.POST.get('valid_until') or None
        is_active = request.POST.get('is_active') == 'on'

        if not name or not value:
            messages.error(request, 'Name and value are required.')
        else:
            discount.name = name
            discount.description = description
            discount.discount_type = discount_type
            discount.value = value
            discount.max_discount = max_discount
            discount.min_order_amount = min_order_amount or 0
            discount.category_id = category_id
            discount.subcategory_id = subcategory_id
            discount.service_id = service_id
            if valid_from:
                discount.valid_from = valid_from
            discount.valid_until = valid_until
            discount.is_active = is_active
            discount.save()
            messages.success(request, 'Discount updated.')
            return redirect('discounts_list')

    return render(request, 'dashboard/discount_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'discounts',
        'categories': ServiceCategory.objects.filter(is_active=True).prefetch_related('subcategories'),
        'services': Service.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name'),
        'discount': discount,
        'is_edit': True,
    })


# ---------- Delete Discount ----------

@admin_login_required
def discount_delete_view(request, discount_id):
    if request.method != 'POST':
        return redirect('discounts_list')

    discount = get_object_or_404(Discount, id=discount_id)
    name = discount.name
    discount.delete()
    messages.success(request, f'Discount "{name}" deleted.')
    return redirect('discounts_list')


# ---------- Coupons List ----------

@admin_login_required
def coupons_list_view(request):
    coupons = Coupon.objects.order_by('-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'coupons',
        'coupons': coupons,
    }
    return render(request, 'dashboard/coupons_list.html', context)


# ---------- Add Coupon ----------

@admin_login_required
def coupon_add_view(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', 'PERCENTAGE')
        value = request.POST.get('value', '0')
        max_discount = request.POST.get('max_discount') or None
        min_order_amount = request.POST.get('min_order_amount', '0')
        total_usage_limit = request.POST.get('total_usage_limit') or None
        per_customer_limit = request.POST.get('per_customer_limit', '1')
        valid_from = request.POST.get('valid_from') or None
        valid_until = request.POST.get('valid_until') or None
        is_active = request.POST.get('is_active') == 'on'

        if not code or not value:
            messages.error(request, 'Code and value are required.')
        elif Coupon.objects.filter(code__iexact=code).exists():
            messages.error(request, 'This code already exists.')
        else:
            try:
                Coupon.objects.create(
                    code=code,
                    description=description,
                    discount_type=discount_type,
                    value=value,
                    max_discount=max_discount,
                    min_order_amount=min_order_amount or 0,
                    total_usage_limit=total_usage_limit,
                    per_customer_limit=per_customer_limit or 1,
                    valid_from=valid_from or timezone.now(),
                    valid_until=valid_until,
                    is_active=is_active,
                )
                messages.success(request, f'Coupon "{code}" created.')
                return redirect('coupons_list')
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/coupon_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'coupons',
        'is_edit': False,
    })


# ---------- Edit Coupon ----------

@admin_login_required
def coupon_edit_view(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)

    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        description = request.POST.get('description', '').strip()
        discount_type = request.POST.get('discount_type', 'PERCENTAGE')
        value = request.POST.get('value', '0')
        max_discount = request.POST.get('max_discount') or None
        min_order_amount = request.POST.get('min_order_amount', '0')
        total_usage_limit = request.POST.get('total_usage_limit') or None
        per_customer_limit = request.POST.get('per_customer_limit', '1')
        valid_from = request.POST.get('valid_from') or None
        valid_until = request.POST.get('valid_until') or None
        is_active = request.POST.get('is_active') == 'on'

        if not code or not value:
            messages.error(request, 'Code and value are required.')
        elif Coupon.objects.filter(code__iexact=code).exclude(id=coupon.id).exists():
            messages.error(request, 'This code already exists.')
        else:
            coupon.code = code
            coupon.description = description
            coupon.discount_type = discount_type
            coupon.value = value
            coupon.max_discount = max_discount
            coupon.min_order_amount = min_order_amount or 0
            coupon.total_usage_limit = total_usage_limit
            coupon.per_customer_limit = per_customer_limit or 1
            if valid_from:
                coupon.valid_from = valid_from
            coupon.valid_until = valid_until
            coupon.is_active = is_active
            coupon.save()
            messages.success(request, 'Coupon updated.')
            return redirect('coupons_list')

    return render(request, 'dashboard/coupon_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'coupons',
        'coupon': coupon,
        'is_edit': True,
    })


# ---------- Delete Coupon ----------

@admin_login_required
def coupon_delete_view(request, coupon_id):
    if request.method != 'POST':
        return redirect('coupons_list')

    coupon = get_object_or_404(Coupon, id=coupon_id)
    code = coupon.code
    coupon.delete()
    messages.success(request, f'Coupon "{code}" deleted.')
    return redirect('coupons_list')


# ---------- Coupon Usage History ----------

@admin_login_required
def coupon_usage_view(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    usages = coupon.usages.select_related('customer__user', 'booking').order_by('-used_at')

    paginator = Paginator(usages, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'coupons',
        'coupon': coupon,
        'page_obj': page_obj,
    }
    return render(request, 'dashboard/coupon_usage.html', context)


from django.db.models import Count, Sum, Avg, Q
from django.db.models.functions import TruncDate, TruncMonth


# ================= REPORTS & ANALYTICS =================

@admin_login_required
def reports_view(request):
    now = timezone.now()
    today = now.date()

    # Date range filter
    date_range = request.GET.get('range', '30')
    try:
        days = int(date_range)
    except ValueError:
        days = 30
    start_date = now - timedelta(days=days)

    bookings_qs = Booking.objects.filter(created_at__gte=start_date)

    # Revenue by day
    revenue_by_day = bookings_qs.filter(payment_status='PAID').annotate(
        day=TruncDate('created_at')
    ).values('day').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('day')

    revenue_labels = []
    revenue_data = []
    booking_count_data = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        revenue_labels.append(day.strftime('%b %d'))
        entry = next((r for r in revenue_by_day if r['day'] == day), None)
        revenue_data.append(float(entry['total']) if entry else 0)
        booking_count_data.append(entry['count'] if entry else 0)

    # Status breakdown
    status_breakdown = bookings_qs.values('status').annotate(count=Count('id'))
    status_data = {s['status']: s['count'] for s in status_breakdown}

    # Top categories by revenue
    top_categories_revenue = ServiceCategory.objects.annotate(
        revenue=Sum('bookings__amount', filter=Q(bookings__payment_status='PAID', bookings__created_at__gte=start_date)),
        count=Count('bookings', filter=Q(bookings__created_at__gte=start_date))
    ).filter(count__gt=0).order_by('-revenue')[:10]

    # Top vendors by completed jobs
    top_vendors = Vendor.objects.annotate(
        completed=Count('assigned_bookings', filter=Q(assigned_bookings__status='COMPLETED', assigned_bookings__created_at__gte=start_date)),
        avg_rating=Avg('reviews_received__rating'),
    ).filter(completed__gt=0).select_related('user').order_by('-completed')[:10]

    # Summary stats
    total_revenue = bookings_qs.filter(payment_status='PAID').aggregate(t=Sum('amount'))['t'] or 0
    total_bookings = bookings_qs.count()
    completed_count = bookings_qs.filter(status='COMPLETED').count()
    cancelled_count = bookings_qs.filter(status='CANCELLED').count()
    completion_rate = (completed_count / total_bookings * 100) if total_bookings > 0 else 0
    cancellation_rate = (cancelled_count / total_bookings * 100) if total_bookings > 0 else 0
    avg_booking_value = (total_revenue / completed_count) if completed_count > 0 else 0

    # Customer stats
    new_customers = User.objects.filter(
        role=User.Role.CUSTOMER,
        date_joined__gte=start_date
    ).count()

    context = {
        'admin_user': request.admin_user,
        'active_page': 'reports',
        'date_range': date_range,
        'days': days,
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'completed_count': completed_count,
        'cancelled_count': cancelled_count,
        'completion_rate': round(completion_rate, 1),
        'cancellation_rate': round(cancellation_rate, 1),
        'avg_booking_value': round(avg_booking_value, 2),
        'new_customers': new_customers,
        'revenue_labels': revenue_labels,
        'revenue_data': revenue_data,
        'booking_count_data': booking_count_data,
        'status_data': status_data,
        'top_categories_revenue': top_categories_revenue,
        'top_vendors': top_vendors,
    }
    return render(request, 'dashboard/reports.html', context)


# ================= CUSTOMERS MANAGEMENT =================

@admin_login_required
def customers_list_view(request):
    search = request.GET.get('search', '').strip()

    customers = Customer.objects.select_related('user').annotate(
        booking_count=Count('bookings'),
        total_spent=Sum('bookings__amount', filter=Q(bookings__payment_status='PAID')),
    ).order_by('-created_at')

    if search:
        customers = customers.filter(
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(user__phone_number__icontains=search) |
            Q(user__email__icontains=search)
        )

    paginator = Paginator(customers, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'customers',
        'page_obj': page_obj,
        'search': search,
    }
    return render(request, 'dashboard/customers_list.html', context)


@admin_login_required
def customer_detail_view(request, customer_id):
    customer = get_object_or_404(
        Customer.objects.select_related('user'), id=customer_id
    )

    bookings = customer.bookings.select_related(
        'category', 'vendor__user', 'preferred_vendor__user'
    ).order_by('-created_at')
    bookings_paginator = Paginator(bookings, 10)
    bookings_page = bookings_paginator.get_page(request.GET.get('bookings_page', 1))

    total_spent = bookings.filter(payment_status='PAID').aggregate(t=Sum('amount'))['t'] or 0
    total_bookings = bookings.count()
    completed_bookings = bookings.filter(status='COMPLETED').count()

    context = {
        'admin_user': request.admin_user,
        'active_page': 'customers',
        'customer': customer,
        'bookings_page': bookings_page,
        'total_spent': total_spent,
        'total_bookings': total_bookings,
        'completed_bookings': completed_bookings,
    }
    return render(request, 'dashboard/customer_detail.html', context)


# ================= ADMIN USERS MANAGEMENT =================

@admin_login_required
def admin_users_list_view(request):
    # Only super admins can see this
    if not request.admin_user.is_super_admin:
        messages.error(request, 'Only super admins can manage admin users.')
        return redirect('dashboard')

    admins = AdminUser.objects.order_by('-created_at')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'admin_users',
        'admins': admins,
    }
    return render(request, 'dashboard/admin_users_list.html', context)


@admin_login_required
def admin_user_add_view(request):
    if not request.admin_user.is_super_admin:
        messages.error(request, 'Only super admins can manage admin users.')
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'STAFF')
        is_active = request.POST.get('is_active') == 'on'

        if not email or not full_name:
            messages.error(request, 'Email and name are required.')
        elif AdminUser.objects.filter(email__iexact=email).exists():
            messages.error(request, 'An admin with this email already exists.')
        else:
            AdminUser.objects.create(
                email=email,
                full_name=full_name,
                role=role,
                is_active=is_active,
                can_manage_bookings=request.POST.get('can_manage_bookings') == 'on',
                can_manage_vendors=request.POST.get('can_manage_vendors') == 'on',
                can_manage_customers=request.POST.get('can_manage_customers') == 'on',
                can_manage_services=request.POST.get('can_manage_services') == 'on',
                can_manage_content=request.POST.get('can_manage_content') == 'on',
                can_manage_discounts=request.POST.get('can_manage_discounts') == 'on',
                can_view_reports=request.POST.get('can_view_reports') == 'on',
            )
            messages.success(request, f'Admin "{full_name}" created.')
            return redirect('admin_users_list')

    return render(request, 'dashboard/admin_user_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'admin_users',
        'is_edit': False,
    })


@admin_login_required
def admin_user_edit_view(request, user_id):
    if not request.admin_user.is_super_admin:
        messages.error(request, 'Only super admins can manage admin users.')
        return redirect('dashboard')

    target = get_object_or_404(AdminUser, id=user_id)

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', 'STAFF')
        is_active = request.POST.get('is_active') == 'on'

        if not full_name:
            messages.error(request, 'Name is required.')
        else:
            target.full_name = full_name
            target.role = role
            target.is_active = is_active
            target.can_manage_bookings = request.POST.get('can_manage_bookings') == 'on'
            target.can_manage_vendors = request.POST.get('can_manage_vendors') == 'on'
            target.can_manage_customers = request.POST.get('can_manage_customers') == 'on'
            target.can_manage_services = request.POST.get('can_manage_services') == 'on'
            target.can_manage_content = request.POST.get('can_manage_content') == 'on'
            target.can_manage_discounts = request.POST.get('can_manage_discounts') == 'on'
            target.can_view_reports = request.POST.get('can_view_reports') == 'on'
            target.save()
            messages.success(request, 'Admin user updated.')
            return redirect('admin_users_list')

    return render(request, 'dashboard/admin_user_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'admin_users',
        'target_user': target,
        'is_edit': True,
    })


@admin_login_required
def admin_user_delete_view(request, user_id):
    if not request.admin_user.is_super_admin:
        return redirect('admin_users_list')
    if request.method != 'POST':
        return redirect('admin_users_list')

    target = get_object_or_404(AdminUser, id=user_id)

    if target.id == request.admin_user.id:
        messages.error(request, "You can't delete your own account.")
        return redirect('admin_users_list')

    name = target.full_name
    target.delete()
    messages.success(request, f'Admin "{name}" deleted.')
    return redirect('admin_users_list')

from support.models import SupportTicket, TicketMessage
from support.notifications import (
    notify_requester_of_reply, notify_requester_of_status,
)


@admin_login_required
def support_tickets_view(request):
    """
    One inbox for both audiences. `who` splits it into Customers / Vendors,
    `status` filters the workflow state, `q` searches subject and requester.
    """
    status_filter = request.GET.get('status', '')
    who_filter = request.GET.get('who', '')
    query = request.GET.get('q', '').strip()

    tickets = SupportTicket.objects.select_related(
        'customer__user', 'vendor__user', 'booking'
    ).prefetch_related('messages')

    if status_filter:
        tickets = tickets.filter(status=status_filter)

    if who_filter in (SupportTicket.RaisedBy.CUSTOMER, SupportTicket.RaisedBy.VENDOR):
        tickets = tickets.filter(raised_by=who_filter)

    if query:
        tickets = tickets.filter(
            Q(subject__icontains=query)
            | Q(customer__user__username__icontains=query)
            | Q(customer__user__first_name__icontains=query)
            | Q(customer__user__last_name__icontains=query)
            | Q(customer__user__phone_number__icontains=query)
            | Q(vendor__user__username__icontains=query)
            | Q(vendor__user__first_name__icontains=query)
            | Q(vendor__user__last_name__icontains=query)
            | Q(vendor__user__phone_number__icontains=query)
        )

    tickets = tickets.order_by('-updated_at')

    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    all_tickets = SupportTicket.objects.all()
    open_statuses = [SupportTicket.Status.OPEN, SupportTicket.Status.IN_PROGRESS]

    context = {
        'admin_user': request.admin_user,
        'active_page': 'support',
        'page_obj': page_obj,
        'current_status': status_filter,
        'current_who': who_filter,
        'query': query,
        'status_tabs': [('', 'All')] + list(SupportTicket.Status.choices),
        'open_count': all_tickets.filter(status=SupportTicket.Status.OPEN).count(),
        'customer_open_count': all_tickets.filter(
            raised_by=SupportTicket.RaisedBy.CUSTOMER, status__in=open_statuses
        ).count(),
        'vendor_open_count': all_tickets.filter(
            raised_by=SupportTicket.RaisedBy.VENDOR, status__in=open_statuses
        ).count(),
    }
    return render(request, 'dashboard/support_tickets.html', context)


@admin_login_required
def support_ticket_detail_view(request, ticket_id):
    ticket = get_object_or_404(
        SupportTicket.objects.select_related(
            'customer__user', 'vendor__user', 'booking'
        ).prefetch_related('messages'),
        id=ticket_id
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'reply':
            message = request.POST.get('message', '').strip()
            if message:
                TicketMessage.objects.create(
                    ticket=ticket, sender=TicketMessage.Sender.ADMIN, message=message
                )
                if ticket.status == SupportTicket.Status.OPEN:
                    ticket.status = SupportTicket.Status.IN_PROGRESS
                ticket.save()
                notify_requester_of_reply(ticket, message)
                messages.success(request, 'Reply sent.')

        elif action == 'update_status':
            new_status = request.POST.get('status')
            valid = dict(SupportTicket.Status.choices)
            if new_status in valid and new_status != ticket.status:
                ticket.status = new_status
                ticket.save()
                notify_requester_of_status(ticket)
                messages.success(request, 'Status updated.')

        return redirect('support_ticket_detail', ticket_id=ticket.id)

    if ticket.is_from_vendor:
        vendor = ticket.vendor
        recent_jobs = Booking.objects.filter(vendor=vendor).select_related(
            'category', 'customer__user'
        ).order_by('-created_at')[:5]
    else:
        vendor = None
        recent_jobs = None

    context = {
        'admin_user': request.admin_user,
        'active_page': 'support',
        'ticket': ticket,
        'vendor': vendor,
        'recent_jobs': recent_jobs,
    }
    return render(request, 'dashboard/support_ticket_detail.html', context)


# ================= ASSIGNMENT CENTER =================

@admin_login_required
def assignment_center_view(request):
    now = timezone.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    def pct_change(today_val, yest_val):
        if yest_val == 0:
            return 100 if today_val > 0 else 0
        return round(((today_val - yest_val) / yest_val) * 100, 0)

    # --- Stat cards ---
    total_bookings = Booking.objects.count()
    total_bookings_yest = Booking.objects.filter(created_at__date__lte=yesterday).count()
    total_bookings_trend = pct_change(total_bookings, total_bookings_yest)

    pending_bookings = Booking.objects.filter(status='PENDING').count()

    assigned_today = Booking.objects.filter(assigned_at__date=today).count()
    assigned_yest = Booking.objects.filter(assigned_at__date=yesterday).count()
    assigned_trend = pct_change(assigned_today, assigned_yest)

    completed_today = Booking.objects.filter(status='COMPLETED', completed_at__date=today).count()
    completed_yest = Booking.objects.filter(status='COMPLETED', completed_at__date=yesterday).count()
    completed_trend = pct_change(completed_today, completed_yest)

    total_vendors = Vendor.objects.count()

    # --- Pending bookings to assign ---
    pending_list = Booking.objects.filter(status='PENDING').select_related(
        'customer__user', 'category'
    ).order_by('preferred_date', 'preferred_time')[:10]

    # --- Recent assignments ---
    recent_assignments = Booking.objects.filter(
        vendor__isnull=False
    ).exclude(status='PENDING').select_related(
        'customer__user', 'category', 'vendor__user'
    ).order_by('-assigned_at')[:10]

    # --- Top performing vendors ---
    top_vendors = Vendor.objects.annotate(
        completed_jobs=Count('assigned_bookings', filter=Q(assigned_bookings__status='COMPLETED')),
        avg_rating=Avg('reviews_received__rating'),
    ).filter(completed_jobs__gt=0).select_related('user').order_by('-completed_jobs')[:5]
    # --- Map data: vendors with location + pending booking locations ---
    import json
    vendors_with_loc = Vendor.objects.filter(
        latitude__isnull=False, longitude__isnull=False
    ).select_related('user')

    vendor_pins = []
    for v in vendors_with_loc:
        active_jobs = Booking.objects.filter(
            vendor=v, status__in=['ASSIGNED', 'IN_PROGRESS']
        ).count()
        # 3-state status
        if v.status == 'OFFLINE':
            pin_status = 'offline'
        elif active_jobs > 0:
            pin_status = 'busy'
        else:
            pin_status = 'available'
        vendor_pins.append({
            'name': v.user.get_full_name() or v.user.username,
            'lat': float(v.latitude),
            'lng': float(v.longitude),
            'status': pin_status,
            'jobs': active_jobs,
            'id': v.id,
        })

    booking_pins = []
    for b in Booking.objects.filter(
        status='PENDING', location_lat__isnull=False, location_lng__isnull=False
    ).select_related('category')[:20]:
        booking_pins.append({
            'id': b.id,
            'category': b.category.name,
            'lat': float(b.location_lat),
            'lng': float(b.location_lng),
        })
        # --- Availability donut (all vendors, not just mapped ones) ---   ← ADD HERE
    all_vendors = Vendor.objects.all()
    donut_available = 0
    donut_busy = 0
    donut_offline = 0
    for v in all_vendors:
        cs = v.computed_status
        if cs == 'AVAILABLE':
            donut_available += 1
        elif cs == 'BUSY':
            donut_busy += 1
        else:
            donut_offline += 1

    donut_total = donut_available + donut_busy + donut_offline
    context = {
        'admin_user': request.admin_user,
        'active_page': 'assignment_center',
        'total_bookings': total_bookings,
        'total_bookings_trend': total_bookings_trend,
        'pending_bookings': pending_bookings,
        'assigned_today': assigned_today,
        'assigned_trend': assigned_trend,
        'completed_today': completed_today,
        'completed_trend': completed_trend,
        'total_vendors': total_vendors,
        'pending_list': pending_list,
        'recent_assignments': recent_assignments,
        'top_vendors': top_vendors,
        'vendor_pins_json': json.dumps(vendor_pins),
        'booking_pins_json': json.dumps(booking_pins),
        'available_count': sum(1 for v in vendor_pins if v['status'] == 'available'),
        'busy_count': sum(1 for v in vendor_pins if v['status'] == 'busy'),
        'offline_count': sum(1 for v in vendor_pins if v['status'] == 'offline'),
        'donut_available': donut_available,
        'donut_busy': donut_busy,
        'donut_offline': donut_offline,
        'donut_total': donut_total,
    }
    return render(request, 'dashboard/assignment_center.html', context)    

def _coverage_tree():
    """
    Categories -> their subcategories -> services, for the coverage picker.

    Built here rather than in the template because a category's `services`
    reverse accessor holds everything in it, subcategory ones included, and a
    template cannot split those apart.
    """
    categories = ServiceCategory.objects.filter(is_active=True).prefetch_related(
        'subcategories__services', 'services'
    ).order_by('name')

    tree = []
    for category in categories:
        tree.append({
            'category': category,
            'direct_services': [
                s for s in category.services.all()
                if s.subcategory_id is None and s.is_active
            ],
            'subcategories': [
                {
                    'subcategory': sub,
                    'services': [s for s in sub.services.all() if s.is_active],
                }
                for sub in category.subcategories.all()
            ],
        })
    return tree


def _apply_vendor_coverage(request, vendor):
    """
    Stores which subcategories / services this vendor actually handles.

    Empty means "the whole category", which is how every vendor worked before
    these fields existed, so an untouched form keeps the old behaviour.
    """
    vendor.subcategories.set(request.POST.getlist('subcategories'))
    vendor.services.set(request.POST.getlist('services'))


def _apply_pro_vendor_fields(request, vendor):
    """
    Copies the Pro Vendor showcase panel off the vendor form onto the vendor.

    Images are only replaced when a new file is actually chosen, so saving the
    form without touching the file inputs keeps the photo already on file.
    """
    vendor.is_pro = request.POST.get('is_pro') == 'on'
    vendor.pro_title = request.POST.get('pro_title', '').strip()
    vendor.pro_tagline = request.POST.get('pro_tagline', '').strip()
    vendor.pro_bio = request.POST.get('pro_bio', '').strip()
    vendor.experience_years = request.POST.get('experience_years') or 0
    vendor.pro_sort_order = request.POST.get('pro_sort_order') or 0

    photo = request.FILES.get('pro_photo')
    if photo:
        vendor.pro_photo = photo
    banner = request.FILES.get('pro_banner')
    if banner:
        vendor.pro_banner = banner


def _save_vendor_documents(request, vendor):
    """
    Stores any files posted by the Documents rows on the vendor form.

    The template disables the type dropdown of any row with no file chosen, so
    the two lists arrive the same length and line up index for index.
    Returns how many documents were saved.
    """
    doc_types = request.POST.getlist('doc_type[]')
    doc_files = request.FILES.getlist('doc_file[]')

    saved = 0
    for doc_type, doc_file in zip(doc_types, doc_files):
        if not doc_file:
            continue
        VendorDocument.objects.create(
            vendor=vendor,
            doc_type=doc_type or VendorDocument.DocType.OTHER,
            file=doc_file,
        )
        saved += 1
    return saved


@admin_login_required
def vendor_add_view(request):
    if request.method == 'POST':
        # User fields
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()

        # Vendor fields
        service_area = request.POST.get('service_area', '').strip()
        address = request.POST.get('address', '').strip()
        latitude = request.POST.get('latitude') or None
        longitude = request.POST.get('longitude') or None
        verification_status = request.POST.get('verification_status', 'PENDING')
        is_available = request.POST.get('is_available') == 'on'
        status = request.POST.get('status', 'AVAILABLE')
        category_ids = request.POST.getlist('categories')

        if not username or not password:
            messages.error(request, 'Username and password are required.')
        elif not first_name:
            messages.error(request, 'First name is required.')
        elif not service_area:
            messages.error(request, 'Service area is required.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'This username is already taken.')
        elif phone_number and User.objects.filter(phone_number=phone_number).exists():
            messages.error(request, 'A user with this phone number already exists.')
        else:
            try:
                user = User.objects.create(
                    username=username,
                    phone_number=phone_number or None,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    role='VENDOR',
                )
                user.set_password(password)
                user.save()

                vendor = Vendor.objects.create(
                    user=user,
                    service_area=service_area,
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                    verification_status=verification_status,
                    is_available=is_available,
                    status=status,
                )
                if category_ids:
                    vendor.categories.set(category_ids)
                _apply_vendor_coverage(request, vendor)

                _apply_pro_vendor_fields(request, vendor)
                vendor.save()

                saved_docs = _save_vendor_documents(request, vendor)

                messages.success(request, f'Vendor "{first_name}" created with login "{username}".')
                if saved_docs:
                    messages.success(request, f'{saved_docs} document(s) uploaded.')
                return redirect('vendor_detail', vendor_id=vendor.id)
            except Exception as e:
                messages.error(request, f'Error: {e}')

    return render(request, 'dashboard/vendor_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'vendors',
        'categories': ServiceCategory.objects.filter(is_active=True).order_by('name'),
        'coverage_tree': _coverage_tree(),
        'is_edit': False,
    })

@admin_login_required
def vendor_edit_view(request, vendor_id):
    vendor = get_object_or_404(Vendor.objects.select_related('user'), id=vendor_id)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        service_area = request.POST.get('service_area', '').strip()
        address = request.POST.get('address', '').strip()
        latitude = request.POST.get('latitude') or None
        longitude = request.POST.get('longitude') or None
        verification_status = request.POST.get('verification_status', 'PENDING')
        is_available = request.POST.get('is_available') == 'on'
        status = request.POST.get('status', 'AVAILABLE')
        category_ids = request.POST.getlist('categories')

        if not username:
            messages.error(request, 'Username is required.')
        elif not first_name:
            messages.error(request, 'First name is required.')
        elif not service_area:
            messages.error(request, 'Service area is required.')
        elif User.objects.filter(username=username).exclude(id=vendor.user.id).exists():
            messages.error(request, 'This username is already taken.')
        elif phone_number and User.objects.filter(phone_number=phone_number).exclude(id=vendor.user.id).exists():
            messages.error(request, 'This phone number is already used by another account.')
        else:
            vendor.user.username = username
            vendor.user.first_name = first_name
            vendor.user.last_name = last_name
            vendor.user.email = email
            vendor.user.phone_number = phone_number or None
            if new_password:
                vendor.user.set_password(new_password)
            vendor.user.save()

            vendor.service_area = service_area
            vendor.address = address
            vendor.latitude = latitude
            vendor.longitude = longitude
            vendor.verification_status = verification_status
            vendor.is_available = is_available
            vendor.status = status
            _apply_pro_vendor_fields(request, vendor)
            vendor.save()

            vendor.categories.set(category_ids)
            _apply_vendor_coverage(request, vendor)

            saved_docs = _save_vendor_documents(request, vendor)

            if new_password:
                messages.success(request, 'Vendor updated and password reset.')
            else:
                messages.success(request, 'Vendor updated.')
            if saved_docs:
                messages.success(request, f'{saved_docs} document(s) uploaded.')
            return redirect('vendor_detail', vendor_id=vendor.id)

    return render(request, 'dashboard/vendor_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'vendors',
        'categories': ServiceCategory.objects.filter(is_active=True).order_by('name'),
        'coverage_tree': _coverage_tree(),
        'vendor': vendor,
        'vendor_category_ids': list(vendor.categories.values_list('id', flat=True)),
        'vendor_subcategory_ids': list(vendor.subcategories.values_list('id', flat=True)),
        'vendor_service_ids': list(vendor.services.values_list('id', flat=True)),
        'is_edit': True,
    })
    # ---------- Auto-Assign (Round Robin) ----------

@admin_login_required
def auto_assign_view(request, booking_id):
    if request.method != 'POST':
        return redirect('booking_detail', booking_id=booking_id)

    booking = get_object_or_404(Booking, id=booking_id)

    if booking.status != 'PENDING':
        messages.error(request, 'This booking is already assigned.')
        return redirect('booking_detail', booking_id=booking_id)

    vendor = pick_next_vendor(booking.category, booking)

    if not vendor:
        messages.error(request, 'No eligible vendors available for this category.')
        return redirect('booking_detail', booking_id=booking_id)

    booking.vendor = vendor
    booking.status = 'ASSIGNED'
    booking.assigned_at = timezone.now()
    booking.assigned_by = 'Auto'
    booking.save()

    mark_assigned(vendor)

    vendor_name = vendor.user.get_full_name() or vendor.user.username
    notify_customer(
        customer=booking.customer,
        title='Vendor Assigned!',
        body=f'{vendor_name} has been assigned to your {booking.category.name} booking.',
        booking=booking,
    )

    messages.success(request, f'Auto-assigned to {vendor_name} (round-robin).')
    return redirect('booking_detail', booking_id=booking_id)


# ---------- Bulk Auto-Assign All Pending ----------

@admin_login_required
def bulk_auto_assign_view(request):
    if request.method != 'POST':
        return redirect('assignment_center')

    pending = Booking.objects.filter(status='PENDING').select_related('category')
    assigned_count = 0

    for booking in pending:
        vendor = pick_next_vendor(booking.category, booking)
        if vendor:
            booking.vendor = vendor
            booking.status = 'ASSIGNED'
            booking.assigned_at = timezone.now()
            booking.assigned_by = 'Auto'
            booking.save()
            mark_assigned(vendor)

            vendor_name = vendor.user.get_full_name() or vendor.user.username
            notify_customer(
                customer=booking.customer,
                title='Vendor Assigned!',
                body=f'{vendor_name} has been assigned to your {booking.category.name} booking.',
                booking=booking,
            )
            assigned_count += 1

    messages.success(request, f'Auto-assigned {assigned_count} bookings via round-robin.')
    return redirect('assignment_center')


# ===========================================================================
# Pro Vendors — the vendors put on show in the Customer app, plus the
# sections that curate them onto the home screen.
# ===========================================================================

from home_sections.models import ProVendorSection, ProVendorSectionItem


@admin_login_required
def pro_vendors_list_view(request):
    """Every vendor currently flagged as a Pro, in the order customers see."""
    search = request.GET.get('search', '').strip()

    vendors = (
        Vendor.objects.filter(is_pro=True)
        .select_related('user')
        .prefetch_related('categories', 'subcategories', 'services')
        .with_review_stats()
        .order_by('pro_sort_order', 'id')
    )
    if search:
        vendors = vendors.filter(
            models.Q(user__first_name__icontains=search) |
            models.Q(user__last_name__icontains=search) |
            models.Q(pro_title__icontains=search)
        )

    context = {
        'admin_user': request.admin_user,
        'active_page': 'pro_vendors',
        'vendors': vendors,
        'search': search,
        # Anything not verified is invisible to customers — call it out rather
        # than letting an admin wonder why their pro never showed up.
        'unverified_count': vendors.exclude(verification_status='VERIFIED').count(),
    }
    return render(request, 'dashboard/pro_vendors_list.html', context)


@admin_login_required
def pro_vendor_toggle_view(request, vendor_id):
    if request.method != 'POST':
        return redirect('pro_vendors_list')

    vendor = get_object_or_404(Vendor.objects.select_related('user'), id=vendor_id)
    vendor.is_pro = not vendor.is_pro
    vendor.save(update_fields=['is_pro'])

    state = 'is now a Pro Vendor' if vendor.is_pro else 'is no longer a Pro Vendor'
    messages.success(request, f'{vendor.display_name} {state}.')
    return redirect(request.POST.get('next') or 'pro_vendors_list')


# ---------- Pro Vendor Sections ----------

@admin_login_required
def pro_vendor_sections_list_view(request):
    sections = ProVendorSection.objects.prefetch_related('items').order_by(
        'sort_order', '-created_at'
    )
    context = {
        'admin_user': request.admin_user,
        'active_page': 'pro_vendor_sections',
        'sections': sections,
    }
    return render(request, 'dashboard/pro_vendor_sections_list.html', context)


def _read_pro_vendor_section_post(request):
    """Shared field read for the add and edit forms. Returns (data, error)."""
    title = request.POST.get('title', '').strip()
    if not title:
        return None, 'Title is required.'

    return {
        'title': title,
        'subtitle': request.POST.get('subtitle', '').strip(),
        'home_display_limit': request.POST.get('home_display_limit') or 5,
        'sort_order': request.POST.get('sort_order') or 0,
        'is_active': request.POST.get('is_active') == 'on',
    }, None


@admin_login_required
def pro_vendor_section_add_view(request):
    if request.method == 'POST':
        data, error = _read_pro_vendor_section_post(request)
        if error:
            messages.error(request, error)
        else:
            section = ProVendorSection.objects.create(**data)
            messages.success(request, f'Section "{section.title}" created.')
            return redirect('pro_vendor_section_detail', section_id=section.id)

    return render(request, 'dashboard/pro_vendor_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'pro_vendor_sections',
        'is_edit': False,
    })


@admin_login_required
def pro_vendor_section_edit_view(request, section_id):
    section = get_object_or_404(ProVendorSection, id=section_id)

    if request.method == 'POST':
        data, error = _read_pro_vendor_section_post(request)
        if error:
            messages.error(request, error)
        else:
            for field, value in data.items():
                setattr(section, field, value)
            section.save()
            messages.success(request, 'Section updated.')
            return redirect('pro_vendor_section_detail', section_id=section.id)

    return render(request, 'dashboard/pro_vendor_section_form.html', {
        'admin_user': request.admin_user,
        'active_page': 'pro_vendor_sections',
        'section': section,
        'is_edit': True,
    })


@admin_login_required
def pro_vendor_section_delete_view(request, section_id):
    if request.method != 'POST':
        return redirect('pro_vendor_sections_list')

    section = get_object_or_404(ProVendorSection, id=section_id)
    title = section.title
    section.delete()
    messages.success(request, f'Section "{title}" deleted.')
    return redirect('pro_vendor_sections_list')


@admin_login_required
def pro_vendor_section_detail_view(request, section_id):
    section = get_object_or_404(ProVendorSection, id=section_id)
    items = section.items.select_related('vendor__user').prefetch_related(
        'vendor__categories', 'vendor__subcategories', 'vendor__services'
    ).order_by('sort_order')

    available_vendors = Vendor.objects.pro().exclude(
        id__in=items.values_list('vendor_id', flat=True)
    ).select_related('user').order_by('pro_sort_order', 'user__first_name')

    context = {
        'admin_user': request.admin_user,
        'active_page': 'pro_vendor_sections',
        'section': section,
        'items': items,
        'available_vendors': available_vendors,
    }
    return render(request, 'dashboard/pro_vendor_section_detail.html', context)


@admin_login_required
def pro_vendor_section_add_item_view(request, section_id):
    if request.method != 'POST':
        return redirect('pro_vendor_section_detail', section_id=section_id)

    section = get_object_or_404(ProVendorSection, id=section_id)
    vendor_id = request.POST.get('vendor_id')

    if not vendor_id:
        messages.error(request, 'Please select a pro vendor.')
        return redirect('pro_vendor_section_detail', section_id=section_id)

    vendor = Vendor.objects.pro().filter(id=vendor_id).select_related('user').first()
    if vendor is None:
        messages.error(request, 'That vendor is not a verified Pro Vendor.')
    else:
        _, created = ProVendorSectionItem.objects.get_or_create(
            section=section, vendor=vendor,
            defaults={'sort_order': section.items.count()},
        )
        if created:
            messages.success(request, f'"{vendor.display_name}" added.')
        else:
            messages.error(request, f'"{vendor.display_name}" is already in this section.')

    return redirect('pro_vendor_section_detail', section_id=section_id)


@admin_login_required
def pro_vendor_section_remove_item_view(request, item_id):
    if request.method != 'POST':
        return redirect('pro_vendor_sections_list')

    item = get_object_or_404(ProVendorSectionItem, id=item_id)
    section_id = item.section_id
    item.delete()
    messages.success(request, 'Vendor removed from section.')
    return redirect('pro_vendor_section_detail', section_id=section_id)


@admin_login_required
def pro_vendor_section_reorder_view(request, item_id):
    if request.method != 'POST':
        return redirect('pro_vendor_sections_list')

    item = get_object_or_404(ProVendorSectionItem, id=item_id)
    direction = request.POST.get('direction')
    siblings = ProVendorSectionItem.objects.filter(section_id=item.section_id)

    if direction == 'up':
        swap_with = siblings.filter(
            sort_order__lt=item.sort_order
        ).order_by('-sort_order').first()
    elif direction == 'down':
        swap_with = siblings.filter(
            sort_order__gt=item.sort_order
        ).order_by('sort_order').first()
    else:
        swap_with = None

    if swap_with:
        item.sort_order, swap_with.sort_order = swap_with.sort_order, item.sort_order
        item.save(update_fields=['sort_order'])
        swap_with.save(update_fields=['sort_order'])

    return redirect('pro_vendor_section_detail', section_id=item.section_id)


# ---------- Gateway Payments: release & refund ----------

@admin_login_required
def release_payment_view(request, payment_id):
    """
    Hand held money over to the vendor.

    This is the escrow release. It is the one action that makes a payment
    non-refundable, so it is deliberately the last step, not the default.
    """
    if request.method != 'POST':
        return redirect('payments_list')

    payment = get_object_or_404(Payment.objects.select_related('booking'), id=payment_id)

    try:
        payment_services.release_to_vendor(payment, by=request.admin_user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('booking_detail', booking_id=payment.booking_id)

    messages.success(
        request,
        f'₹{payment.amount} released to the vendor for booking '
        f'#{payment.booking_id}.'
    )

    # With payouts switched on, releasing and sending are one action -- an
    # admin having to press a second button is just a way for money to sit
    # released but unsent.
    if payoutx.is_enabled():
        _send_payout(request, payment)

    return redirect('booking_detail', booking_id=payment.booking_id)


def _send_payout(request, payment):
    """Attempt the transfer and turn the outcome into a message."""
    try:
        payout = payment_services.create_payout(payment, by=request.admin_user)
    except ValueError as exc:
        messages.warning(
            request,
            f'Released, but not sent: {exc} You can send it from this page '
            f'once that is fixed.'
        )
    except PayoutError as exc:
        if exc.retriable:
            messages.warning(
                request,
                'Released. RazorpayX did not confirm the transfer, so it may '
                'or may not have gone through — check the payout status '
                'before retrying.'
            )
        else:
            messages.error(request, f'Released, but the transfer failed: {exc}')
    else:
        if payout.status == payout.Status.QUEUED:
            messages.info(
                request,
                'Transfer queued — your RazorpayX balance is short. It will '
                'go out automatically once the account is topped up.'
            )
        else:
            messages.success(request, f'Transfer sent ({payout.get_status_display()}).')


@admin_login_required
def retry_payout_view(request, payment_id):
    """
    Send a payout that was released but never made it out.

    Only reachable for a payout RazorpayX definitively refused. Anything in
    flight is left alone -- retrying that is how a vendor gets paid twice.
    """
    if request.method != 'POST':
        return redirect('payments_list')

    payment = get_object_or_404(Payment.objects.select_related('booking'),
                                id=payment_id)
    _send_payout(request, payment)
    return redirect('booking_detail', booking_id=payment.booking_id)


@admin_login_required
def validate_bank_account_view(request, vendor_id):
    """Run the penny drop against a vendor's account on demand."""
    if request.method != 'POST':
        return redirect('vendor_detail', vendor_id=vendor_id)

    vendor = get_object_or_404(Vendor, id=vendor_id)
    account = getattr(vendor, 'bank_account', None)
    if account is None:
        messages.error(request, 'This vendor has not added payout details yet.')
        return redirect('vendor_detail', vendor_id=vendor_id)

    try:
        account = vendor_payout_services.validate_account(account)
    except ValueError as exc:
        messages.error(request, str(exc))
    except PayoutError as exc:
        messages.error(request, f'The check could not be completed: {exc}')
    else:
        if account.validation_status == account.ValidationStatus.ACTIVE:
            messages.success(
                request,
                f'The bank confirmed this account'
                + (f' as "{account.registered_name}".' if account.registered_name else '.')
            )
        elif account.validation_status == account.ValidationStatus.NAME_MISMATCH:
            messages.warning(
                request,
                f'The account is real but the bank has it under '
                f'"{account.registered_name}", not '
                f'"{account.account_holder_name}". Check before paying.'
            )
        else:
            messages.error(request, 'The bank says this account is not valid.')
    return redirect('vendor_detail', vendor_id=vendor_id)


@admin_login_required
def refund_payment_view(request, payment_id):
    """
    Send money back to the customer, in full or in part.

    A blank amount means the whole refundable balance, which is what an admin
    almost always wants and saves them retyping a figure they might get wrong.
    """
    if request.method != 'POST':
        return redirect('payments_list')

    payment = get_object_or_404(Payment.objects.select_related('booking'), id=payment_id)
    raw_amount = (request.POST.get('amount') or '').strip()
    reason = (request.POST.get('reason') or '').strip()

    amount = None
    if raw_amount:
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError):
            messages.error(request, 'Enter a valid refund amount.')
            return redirect('booking_detail', booking_id=payment.booking_id)

    try:
        payment_services.refund_payment(
            payment, amount_rupees=amount, reason=reason
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    except PaymentError as exc:
        messages.error(request, f'Razorpay refused the refund: {exc}')
    else:
        payment.refresh_from_db()
        messages.success(
            request,
            f'Refunded ₹{payment.amount_refunded} on booking '
            f'#{payment.booking_id}.'
        )
    return redirect('booking_detail', booking_id=payment.booking_id)


@admin_login_required
def payments_list_view(request):
    """
    Every gateway payment, so held money can be found without knowing which
    booking it sits on. Defaults to what needs attention: captured and held.
    """
    status = request.GET.get('status', '')
    payout = request.GET.get('payout', '')
    search = request.GET.get('search', '').strip()

    payments = Payment.objects.select_related(
        'booking', 'booking__vendor__user', 'customer__user', 'payout',
    ).order_by('-created_at')

    if status:
        payments = payments.filter(status=status)
    if payout:
        payments = payments.filter(payout_status=payout)
    if search:
        # Order/payment ids, or a bare booking number -- an admin chasing a
        # payment has one or the other in front of them, rarely both.
        match = Q(razorpay_order_id__icontains=search) | Q(
            razorpay_payment_id__icontains=search
        )
        if search.isdigit():
            match |= Q(booking_id=int(search))
        payments = payments.filter(match)

    held = Payment.objects.filter(
        status=Payment.Status.CAPTURED,
        payout_status=Payment.PayoutStatus.HELD,
    )
    totals = {
        'held_count': held.count(),
        'held_amount': held.aggregate(total=Sum('amount'))['total'] or 0,
    }

    paginator = Paginator(payments, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'payments',
        'payments': page,
        'page_obj': page,
        'status': status,
        'payout': payout,
        'search': search,
        'totals': totals,
        'status_choices': Payment.Status.choices,
        'payout_choices': Payment.PayoutStatus.choices,
        'is_live': settings.RAZORPAY_IS_LIVE,
        'payouts_enabled': payoutx.is_enabled(),
    }
    return render(request, 'dashboard/payments_list.html', context)


# ---------- Vendor payout account ----------

@admin_login_required
def verify_bank_account_view(request, vendor_id):
    """
    Confirm a vendor's payout details are really theirs.

    Only ever a manual check today -- somebody looks at the passbook or does a
    one-rupee transfer. The flag it sets is what stops money going out to an
    account nobody has ever looked at.
    """
    if request.method != 'POST':
        return redirect('vendor_detail', vendor_id=vendor_id)

    vendor = get_object_or_404(Vendor, id=vendor_id)

    try:
        bank_services.verify_bank_account(vendor, by=request.admin_user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'Payout account marked as verified.')
    return redirect('vendor_detail', vendor_id=vendor_id)
# ===========================================================================
# Tenders (customer-posted requirements vendors bid on)
# ===========================================================================

@admin_login_required
def tenders_list_view(request):
    """
    Every tender, newest first, with the approval queue reachable in one
    click -- that is the only part of this flow the admin is required for.
    """
    status = request.GET.get('status', '')
    category_id = request.GET.get('category', '')
    search = request.GET.get('search', '').strip()

    tenders = Tender.objects.select_related(
        'customer__user', 'category', 'subcategory', 'awarded_bid__vendor__user'
    ).with_bid_stats().order_by('-created_at')

    if status:
        tenders = tenders.filter(status=status)
    if category_id:
        tenders = tenders.filter(category_id=category_id)
    if search:
        tenders = tenders.filter(
            models.Q(id__icontains=search) |
            models.Q(title__icontains=search) |
            models.Q(customer__user__first_name__icontains=search) |
            models.Q(customer__user__last_name__icontains=search) |
            models.Q(address_pincode__icontains=search)
        )

    paginator = Paginator(tenders, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'admin_user': request.admin_user,
        'active_page': 'tenders',
        'page_obj': page_obj,
        'status_choices': Tender.Status.choices,
        'categories': ServiceCategory.objects.filter(is_active=True),
        'current_status': status,
        'current_category': category_id,
        'search': search,
        'tenders_pending_count': Tender.objects.filter(
            status=Tender.Status.PENDING_APPROVAL
        ).count(),
    }
    return render(request, 'dashboard/tenders_list.html', context)


@admin_login_required
def tender_detail_view(request, tender_id):
    """
    The whole story of one tender: the brief, the drawings, every bid side by
    side, and -- once awarded -- the milestones and progress the vendor posted.
    """
    tender = get_object_or_404(
        Tender.objects.select_related(
            'customer__user', 'category', 'subcategory', 'awarded_bid__vendor__user'
        ).prefetch_related(
            'attachments', 'bids__vendor__user', 'bids__milestones',
            'progress_updates__photos', 'progress_updates__vendor__user',
        ),
        id=tender_id,
    )

    bids = sorted(
        tender.bids.exclude(status=TenderBid.Status.WITHDRAWN),
        key=lambda b: b.amount,
    )

    # Who this would go out to, so whoever approves it can see the reach
    # before committing. Only worth computing while it still matters.
    matching_vendors = []
    if tender.status == Tender.Status.PENDING_APPROVAL:
        matching_vendors = list(tender.matching_vendors().select_related('user')[:50])

    context = {
        'admin_user': request.admin_user,
        'active_page': 'tenders',
        'tender': tender,
        'bids': bids,
        'matching_vendors': matching_vendors,
        'matching_count': len(matching_vendors),
        'review': getattr(tender, 'review', None),
        'tenders_pending_count': Tender.objects.filter(
            status=Tender.Status.PENDING_APPROVAL
        ).count(),
    }
    return render(request, 'dashboard/tender_detail.html', context)


@admin_login_required
def tender_approve_view(request, tender_id):
    """Publish a tender to every vendor who covers it."""
    if request.method != 'POST':
        return redirect('tender_detail', tender_id=tender_id)

    tender = get_object_or_404(Tender, id=tender_id)

    if tender.status != Tender.Status.PENDING_APPROVAL:
        messages.error(request, 'Only a tender awaiting approval can be published.')
        return redirect('tender_detail', tender_id=tender_id)

    tender.status = Tender.Status.OPEN
    tender.published_at = timezone.now()
    tender.rejection_reason = ''
    tender.save(update_fields=['status', 'published_at', 'rejection_reason', 'updated_at'])

    vendor_count = tender_notify.notify_vendors_of_new_tender(tender)
    tender_notify.notify_customer_approved(tender, vendor_count)

    if vendor_count:
        messages.success(
            request, f'Tender published. {vendor_count} vendor(s) have been notified.'
        )
    else:
        messages.success(
            request,
            'Tender published, but no verified vendor currently covers this '
            'category. Add coverage to a vendor and they will see it straight away.'
        )
    return redirect('tender_detail', tender_id=tender_id)


@admin_login_required
def tender_reject_view(request, tender_id):
    """Send a tender back to the customer with a reason they can act on."""
    if request.method != 'POST':
        return redirect('tender_detail', tender_id=tender_id)

    tender = get_object_or_404(Tender, id=tender_id)

    if tender.status != Tender.Status.PENDING_APPROVAL:
        messages.error(request, 'Only a tender awaiting approval can be rejected.')
        return redirect('tender_detail', tender_id=tender_id)

    reason = (request.POST.get('reason') or '').strip()
    if not reason:
        messages.error(request, 'Give the customer a reason so they can fix it.')
        return redirect('tender_detail', tender_id=tender_id)

    tender.status = Tender.Status.REJECTED
    tender.rejection_reason = reason
    tender.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    tender_notify.notify_customer_rejected(tender)

    messages.success(request, 'Tender sent back to the customer.')
    return redirect('tender_detail', tender_id=tender_id)


@admin_login_required
def tender_award_view(request, tender_id):
    """
    Award a tender on the customer's behalf -- for when they ask over the
    phone rather than tapping it in the app. Same effect as them choosing it:
    every other bid is turned down and all sides are told.
    """
    if request.method != 'POST':
        return redirect('tender_detail', tender_id=tender_id)

    tender = get_object_or_404(Tender, id=tender_id)
    bid_id = request.POST.get('bid_id')

    if tender.status != Tender.Status.OPEN:
        messages.error(request, 'Only an open tender can be awarded.')
        return redirect('tender_detail', tender_id=tender_id)

    try:
        bid = tender.bids.select_related('vendor__user').get(
            id=bid_id, status=TenderBid.Status.SUBMITTED
        )
    except TenderBid.DoesNotExist:
        messages.error(request, 'That bid is not available to accept.')
        return redirect('tender_detail', tender_id=tender_id)

    now = timezone.now()
    losing_bids = list(
        tender.bids.exclude(id=bid.id)
        .filter(status=TenderBid.Status.SUBMITTED)
        .select_related('vendor__user')
    )

    with transaction.atomic():
        bid.status = TenderBid.Status.ACCEPTED
        bid.decided_at = now
        bid.save(update_fields=['status', 'decided_at', 'updated_at'])

        tender.bids.exclude(id=bid.id).filter(
            status=TenderBid.Status.SUBMITTED
        ).update(status=TenderBid.Status.REJECTED, decided_at=now)

        tender.awarded_bid = bid
        tender.status = Tender.Status.AWARDED
        tender.awarded_at = now
        tender.save(update_fields=['awarded_bid', 'status', 'awarded_at', 'updated_at'])

    tender_notify.notify_customer_awarded(tender, bid)
    tender_notify.notify_vendor_won(tender, bid)
    tender_notify.notify_vendors_lost(tender, losing_bids)

    messages.success(request, f'{bid.vendor.display_name} has been awarded this tender.')
    return redirect('tender_detail', tender_id=tender_id)


@admin_login_required
def tender_cancel_view(request, tender_id):
    """Close a tender down. Anyone with a live bid is told it is over."""
    if request.method != 'POST':
        return redirect('tender_detail', tender_id=tender_id)

    tender = get_object_or_404(Tender, id=tender_id)

    if tender.status in (Tender.Status.COMPLETED, Tender.Status.CANCELLED):
        messages.error(request, 'This tender is already closed.')
        return redirect('tender_detail', tender_id=tender_id)

    live_bids = list(
        tender.bids.exclude(status=TenderBid.Status.WITHDRAWN)
        .select_related('vendor__user')
    )
    reason = (request.POST.get('reason') or '').strip()

    tender.status = Tender.Status.CANCELLED
    tender.cancellation_reason = reason
    tender.save(update_fields=['status', 'cancellation_reason', 'updated_at'])

    tender_notify.notify_vendors_tender_closed(tender, live_bids, reason=reason)

    messages.success(request, 'Tender cancelled.')
    return redirect('tender_detail', tender_id=tender_id)
