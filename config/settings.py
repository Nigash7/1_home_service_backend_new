from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
import os
import sys

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-2dq$#73&w@z=#3x_lgo8or^%&d&vyh+z1!ladgd)2n3%l_jn!^')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=True, cast=bool)

# ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,192.168.1.11').split(',')
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,.onrender.com"
).split(",")

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    # Media (images/video) is served from Cloudinary's CDN, not from this
    # server. Listed after staticfiles because only media is delegated --
    # static files stay with whitenoise.
    'cloudinary',
    'cloudinary_storage',

    # our apps
    'accounts',
    'vendors',
    'customers',
    'services',
    'bookings',
    'payments',
    'promotions',
    'home_sections',
    'curations',
    'service_forms',
    'reviews',
    'discounts',
    'dashboard',
    'support',
    'notifications',
    'referrals',
    'branding',
    'tenders',
    'subscriptions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
     'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# --- CORS: allow Flutter app (running on emulator/device) to call the API ---
# During development, allow all. Lock this down to specific origins before production.
CORS_ALLOW_ALL_ORIGINS = True

# --- Custom user model (defined in accounts app) ---
AUTH_USER_MODEL = 'accounts.User'

# --- Django REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
}
# --- OTP / SMS settings ---
# SMS_BACKEND: 'console' (free, dev only, prints OTP to terminal) or
# 'fast2sms' / 'msg91' / 'twilio' for real SMS. See accounts/sms.py.

# ---------- Dashboard sign-in security ----------
# Sessions are only used by the admin dashboard and Django's own admin site;
# the mobile apps authenticate with JWTs and are unaffected by any of this.

# A signed-in dashboard session lasts a working day, then asks again.
SESSION_COOKIE_AGE = config('SESSION_COOKIE_AGE', default=12 * 60 * 60, cast=int)
SESSION_SAVE_EVERY_REQUEST = True  # the day is measured from last activity

# Behind a proxy (Render, nginx) every request arrives from the load balancer,
# so the per-IP part of the lockout would see one address for the whole world
# and lock everyone out at once. The header is client-supplied and therefore
# spoofable, which only lets an attacker dodge the IP counter -- never the
# per-username one. Set to False when the app is exposed directly.
ADMIN_LOGIN_TRUST_PROXY_HEADER = config(
    'ADMIN_LOGIN_TRUST_PROXY_HEADER', default=True, cast=bool
)

# Cookies carrying a signed-in session must not travel in the clear. Off in
# DEBUG so local development over plain http still works.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

SMS_BACKEND = config('SMS_BACKEND', default='console')
OTP_EXPIRY_MINUTES = config('OTP_EXPIRY_MINUTES', default=5, cast=int)
OTP_RESEND_COOLDOWN_SECONDS = config('OTP_RESEND_COOLDOWN_SECONDS', default=60, cast=int)

FAST2SMS_API_KEY = config('FAST2SMS_API_KEY', default='')
MSG91_AUTH_KEY = config('MSG91_AUTH_KEY', default='')
MSG91_SENDER_ID = config('MSG91_SENDER_ID', default='')
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER = config('TWILIO_FROM_NUMBER', default='')

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Puts the signed-in dashboard user and their permission set
                # into every template, so the sidebar can hide what a role
                # cannot open.
                'dashboard.context_processors.admin_user',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='homeservice_db'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='2742123'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Database

# Read through decouple, not os.environ: decouple checks real environment
# variables first (how Render supplies this) and falls back to the .env file
# (how local dev supplies it). os.environ alone can't see .env, which silently
# yields an unconfigured dummy backend.
# DATABASE_URL = config('DATABASE_URL', default='')

# if not DATABASE_URL:
#     raise ImproperlyConfigured(
#         "DATABASE_URL is not set. Add it to your .env file for local "
#         "development, or to the environment on the server."
#     )

# DATABASES = {
#     "default": dj_database_url.config(
#         default=DATABASE_URL,
#         conn_max_age=600,
#         # Managed Postgres requires SSL; a local sqlite:// URL rejects the flag.
#         ssl_require=DATABASE_URL.startswith("postgres"),
#     )
# }

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

# STATIC_URL = 'static/'
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (vendor documents, job-start photos)
# Kept for the local-disk fallback below, and because config/urls.py serves
# MEDIA_URL while DEBUG is on.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------- Cloudinary (image & video CDN) ----------
# Uploads go to Cloudinary instead of this server's disk, and are delivered
# from a CDN. That removes two problems at once: Python is no longer the thing
# streaming a 100 MB video to a phone, and an admin who uploads a 2 MB PNG as a
# category icon no longer ships 2 MB to every user -- it is re-encoded on
# delivery instead (see config/storages.py).
CLOUDINARY_CLOUD_NAME = config('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY = config('CLOUDINARY_API_KEY', default='')
CLOUDINARY_API_SECRET = config('CLOUDINARY_API_SECRET', default='')

# The test suite uploads real files in several places. Pointed at Cloudinary
# those uploads would cross the network on every run -- slow, flaky offline,
# and each run would leave test junk in the live account and burn credits.
# Tests therefore always use local disk, whatever .env says.
_RUNNING_TESTS = 'test' in sys.argv

# Empty cloud name = not configured yet. Falling back to local disk rather
# than erroring keeps offline work and a fresh clone runnable.
USE_CLOUDINARY = bool(
    CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET
) and not _RUNNING_TESTS

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': CLOUDINARY_CLOUD_NAME,
    'API_KEY': CLOUDINARY_API_KEY,
    'API_SECRET': CLOUDINARY_API_SECRET,
    # Tags every upload made by this project, so orphaned files can be found
    # and cleaned up later without touching anything uploaded by hand.
    'MEDIA_TAG': 'home_service_media',
}

# Images are the default because they are the overwhelming majority of fields.
# Video and vendor documents opt out per field, via FileField(storage=...) --
# Cloudinary cannot serve a video that was uploaded as an image.
if USE_CLOUDINARY:
    _DEFAULT_FILE_STORAGE = 'config.storages.OptimizedImageCloudinaryStorage'
else:
    _DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Django 5.1 removed DEFAULT_FILE_STORAGE and STATICFILES_STORAGE; both are now
# keys in STORAGES. The old STATICFILES_STORAGE line that used to live here was
# being silently ignored, so whitenoise's compression was never actually on.
# Manifest storage is only safe once collectstatic has written the manifest,
# which is a deploy step -- under DEBUG there is none, so it stays off there.
STORAGES = {
    'default': {
        'BACKEND': _DEFAULT_FILE_STORAGE,
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Email — for OTP delivery
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'otptbio@gmail.com'  # Replace with your Gmail
# EMAIL_HOST_PASSWORD = 'nkjc byoy lidm ycyg'  # Gmail App Password (not regular password)
# DEFAULT_FROM_EMAIL = 'Home Service Admin <otptbio@gmail.com>'
# ---------- Email / Admin OTP ----------

# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
# EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
# EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)

# EMAIL_HOST_USER = config('EMAIL_HOST_USER')
# EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')

# DEFAULT_FROM_EMAIL = config(
#     'DEFAULT_FROM_EMAIL',
#     default=EMAIL_HOST_USER
# )
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)


EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')

EMAIL_TIMEOUT = 10

DEFAULT_FROM_EMAIL = config(
    'DEFAULT_FROM_EMAIL',
    default=EMAIL_HOST_USER
)




# For development testing without SMTP setup:
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# ---------- Firebase Cloud Messaging ----------
FCM_ENABLED = True
FCM_PROJECT_ID = 'prohome-8f3c8'
FCM_CREDENTIALS_FILE = BASE_DIR / 'secrets' / 'fcm-service-account.json'




# ---------- Razorpay ----------
# Money is captured into the platform's own Razorpay account, not the vendor's.
# That capture IS the hold: nothing reaches a vendor until a payout is made
# separately, so a booking can be refunded in full while work is disputed.
RAZORPAY_KEY_ID = config('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = config('RAZORPAY_KEY_SECRET', default='')

# Set in the Razorpay dashboard when creating the webhook. Without it the
# webhook endpoint refuses every delivery rather than trusting unsigned calls.
RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')

RAZORPAY_CURRENCY = config('RAZORPAY_CURRENCY', default='INR')

# Live keys are 'rzp_live_*'. Anything else is a sandbox that cannot move real
# money, which the dashboard shows so nobody mistakes test takings for revenue.
RAZORPAY_IS_LIVE = RAZORPAY_KEY_ID.startswith('rzp_live_')

# ---------- RazorpayX (payouts) ----------
# A separate product from the payment gateway above, with its own dashboard,
# its own credentials, and a virtual account that money is paid out FROM.
# Sharing the gateway keys works on some accounts, hence the fallback.
# `or` rather than a config default: an empty value in .env is how someone
# says "I have not set this up", and that must still fall back.
RAZORPAYX_KEY_ID = config('RAZORPAYX_KEY_ID', default='') or RAZORPAY_KEY_ID
RAZORPAYX_KEY_SECRET = (
    config('RAZORPAYX_KEY_SECRET', default='') or RAZORPAY_KEY_SECRET
)

# The RazorpayX virtual account payouts are debited from. Found on the X
# dashboard under Account Details. Nothing can be paid out without it, which
# is why it alone decides whether the feature is on.
RAZORPAYX_ACCOUNT_NUMBER = config('RAZORPAYX_ACCOUNT_NUMBER', default='')

# IMPS settles in minutes and is capped around 5 lakh; NEFT is the fallback
# for larger amounts. Both are chosen per payout, this is just the default.
RAZORPAYX_PAYOUT_MODE = config('RAZORPAYX_PAYOUT_MODE', default='IMPS')

# Rupees. Above this a payout goes NEFT instead of IMPS.
RAZORPAYX_IMPS_LIMIT = config('RAZORPAYX_IMPS_LIMIT', default=200000, cast=int)

# Off until an account number is configured, so nothing about the existing
# release flow changes until someone deliberately turns this on.
RAZORPAYX_ENABLED = bool(RAZORPAYX_ACCOUNT_NUMBER)

# Penny-drop validation costs a small fee per check. On by default because
# paying the wrong account costs considerably more.
RAZORPAYX_VALIDATE_ACCOUNTS = config(
    'RAZORPAYX_VALIDATE_ACCOUNTS', default=True, cast=bool
)

# How close the bank's registered name must be to what the vendor typed
# before the account is auto-verified. Below this an admin looks at it.
RAZORPAYX_NAME_MATCH_THRESHOLD = config(
    'RAZORPAYX_NAME_MATCH_THRESHOLD', default=0.85, cast=float
)
