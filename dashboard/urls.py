from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='dashboard_login'),
    path('verify-otp/', views.verify_otp_view, name='dashboard_verify_otp'),
    path('resend-otp/', views.resend_otp_view, name='dashboard_resend_otp'),
    path('logout/', views.logout_view, name='dashboard_logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Bookings
    path('bookings/', views.bookings_list_view, name='bookings_list'),
    path('bookings/<int:booking_id>/', views.booking_detail_view, name='booking_detail'),
    path('bookings/<int:booking_id>/assign-vendor/', views.assign_vendor_view, name='assign_vendor'),
    path('bookings/<int:booking_id>/cancel/', views.cancel_booking_view, name='cancel_booking'),
    path('bookings/<int:booking_id>/reschedule/', views.reschedule_booking_view, name='reschedule_booking'),
    path('bookings/<int:booking_id>/update-payment/', views.update_payment_view, name='update_payment'),

    # Vendors
    path('vendors/', views.vendors_list_view, name='vendors_list'),
    path('vendors/add/', views.vendor_add_view, name='vendor_add'),
    path('vendors/<int:vendor_id>/', views.vendor_detail_view, name='vendor_detail'),
    path('vendors/<int:vendor_id>/edit/', views.vendor_edit_view, name='vendor_edit'),
    path('vendors/<int:vendor_id>/verify/', views.verify_vendor_view, name='verify_vendor'),

    # Categories
    path('categories/', views.categories_list_view, name='categories_list'),
    path('categories/add/', views.category_add_view, name='category_add'),
    path('categories/<int:category_id>/edit/', views.category_edit_view, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'),

    # Subcategories
    path('categories/<int:category_id>/subcategories/', views.subcategories_list_view, name='subcategories_list'),
    path('categories/<int:category_id>/subcategories/add/', views.subcategory_add_view, name='subcategory_add'),
    path('subcategories/<int:subcategory_id>/edit/', views.subcategory_edit_view, name='subcategory_edit'),
    path('subcategories/<int:subcategory_id>/delete/', views.subcategory_delete_view, name='subcategory_delete'),

    # Services
    path('categories/<int:category_id>/services/', views.services_list_view, name='services_list_cat'),
    path('subcategories/<int:subcategory_id>/services/', views.services_list_view, name='services_list_sub'),
    path('categories/<int:category_id>/services/add/', views.service_add_view, name='service_add_cat'),
    path('subcategories/<int:subcategory_id>/services/add/', views.service_add_view, name='service_add_sub'),
    path('services/<int:service_id>/edit/', views.service_edit_view, name='service_edit'),
    path('services/<int:service_id>/delete/', views.service_delete_view, name='service_delete'),


    # App branding
    path('branding/', views.branding_view, name='branding'),

    # Refer & Earn
    path('referrals/', views.referrals_list_view, name='referrals_list'),
    path('referrals/settings/', views.referral_settings_view, name='referral_settings'),
    path('referrals/<int:referral_id>/settle/', views.referral_settle_view, name='referral_settle'),

    # Promo Cards (large home page cards around the home sections)
    path('promo-cards/', views.promo_cards_list_view, name='promo_cards_list'),
    path('promo-cards/add/', views.promo_card_add_view, name='promo_card_add'),
    path('promo-cards/<int:card_id>/edit/', views.promo_card_edit_view, name='promo_card_edit'),
    path('promo-cards/<int:card_id>/delete/', views.promo_card_delete_view, name='promo_card_delete'),
    path('promo-cards/<int:card_id>/toggle/', views.promo_card_toggle_view, name='promo_card_toggle'),

    # Header Banners (home hero carousel)
    path('header-banners/', views.header_banners_list_view, name='header_banners_list'),
    path('header-banners/add/', views.header_banner_add_view, name='header_banner_add'),
    path('header-banners/<int:banner_id>/edit/', views.header_banner_edit_view, name='header_banner_edit'),
    path('header-banners/<int:banner_id>/delete/', views.header_banner_delete_view, name='header_banner_delete'),
    path('header-banners/<int:banner_id>/toggle/', views.header_banner_toggle_view, name='header_banner_toggle'),

    # Spotlights
    path('spotlights/', views.spotlights_list_view, name='spotlights_list'),
    path('spotlights/add/', views.spotlight_add_view, name='spotlight_add'),
    path('spotlights/<int:spotlight_id>/edit/', views.spotlight_edit_view, name='spotlight_edit'),
    path('spotlights/<int:spotlight_id>/delete/', views.spotlight_delete_view, name='spotlight_delete'),
    path('spotlights/<int:spotlight_id>/toggle/', views.spotlight_toggle_view, name='spotlight_toggle'),

    # Home Sections
    path('home-sections/', views.home_sections_list_view, name='home_sections_list'),
    path('home-sections/add/', views.home_section_add_view, name='home_section_add'),
    path('home-sections/<int:section_id>/', views.home_section_detail_view, name='home_section_detail'),
    path('home-sections/<int:section_id>/edit/', views.home_section_edit_view, name='home_section_edit'),
    path('home-sections/<int:section_id>/delete/', views.home_section_delete_view, name='home_section_delete'),
    path('home-sections/<int:section_id>/add-item/', views.home_section_add_item_view, name='home_section_add_item'),
    path('home-section-items/<int:item_id>/remove/', views.home_section_remove_item_view, name='home_section_remove_item'),
    path('home-section-items/<int:item_id>/reorder/', views.home_section_reorder_view, name='home_section_reorder'),



    # Curations
    path('curations/', views.curations_list_view, name='curations_list'),
    path('curations/add/', views.curation_section_add_view, name='curation_section_add'),
    path('curations/<int:section_id>/', views.curation_section_detail_view, name='curation_section_detail'),
    path('curations/<int:section_id>/edit/', views.curation_section_edit_view, name='curation_section_edit'),
    path('curations/<int:section_id>/delete/', views.curation_section_delete_view, name='curation_section_delete'),
    path('curations/<int:section_id>/add-video/', views.curation_item_add_view, name='curation_item_add'),
    path('curation-items/<int:item_id>/edit/', views.curation_item_edit_view, name='curation_item_edit'),
    path('curation-items/<int:item_id>/delete/', views.curation_item_delete_view, name='curation_item_delete'),



    # Service Forms
    path('forms/', views.forms_list_view, name='forms_list'),
    path('forms/add/', views.form_add_view, name='form_add'),
    path('forms/<int:form_id>/', views.form_detail_view, name='form_detail'),
    path('forms/<int:form_id>/edit/', views.form_edit_view, name='form_edit'),
    path('forms/<int:form_id>/delete/', views.form_delete_view, name='form_delete'),
    path('forms/<int:form_id>/submissions/', views.form_submissions_view, name='form_submissions'),
    path('forms/<int:form_id>/add-step/', views.form_step_add_view, name='form_step_add'),
    path('form-steps/<int:step_id>/edit/', views.form_step_edit_view, name='form_step_edit'),
    path('form-steps/<int:step_id>/delete/', views.form_step_delete_view, name='form_step_delete'),
    path('form-steps/<int:step_id>/reorder/', views.form_step_reorder_view, name='form_step_reorder'),

    # Discounts
    path('discounts/', views.discounts_list_view, name='discounts_list'),
    path('discounts/add/', views.discount_add_view, name='discount_add'),
    path('discounts/<int:discount_id>/edit/', views.discount_edit_view, name='discount_edit'),
    path('discounts/<int:discount_id>/delete/', views.discount_delete_view, name='discount_delete'),

    # Coupons
    path('coupons/', views.coupons_list_view, name='coupons_list'),
    path('coupons/add/', views.coupon_add_view, name='coupon_add'),
    path('coupons/<int:coupon_id>/edit/', views.coupon_edit_view, name='coupon_edit'),
    path('coupons/<int:coupon_id>/delete/', views.coupon_delete_view, name='coupon_delete'),
    path('coupons/<int:coupon_id>/usage/', views.coupon_usage_view, name='coupon_usage'),

    # Reports
    path('reports/', views.reports_view, name='reports'),

    # Customers
    path('customers/', views.customers_list_view, name='customers_list'),
    path('customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),

    # Admin Users
    path('admin-users/', views.admin_users_list_view, name='admin_users_list'),
    path('admin-users/add/', views.admin_user_add_view, name='admin_user_add'),
    path('admin-users/<int:user_id>/edit/', views.admin_user_edit_view, name='admin_user_edit'),
    path('admin-users/<int:user_id>/delete/', views.admin_user_delete_view, name='admin_user_delete'),
    path('support/', views.support_tickets_view, name='support_tickets'),
    path('support/<int:ticket_id>/', views.support_ticket_detail_view, name='support_ticket_detail'),
    path('assignment-center/', views.assignment_center_view, name='assignment_center'),
    path('bookings/<int:booking_id>/auto-assign/', views.auto_assign_view, name='auto_assign'),
    path('bulk-auto-assign/', views.bulk_auto_assign_view, name='bulk_auto_assign'),
    
]