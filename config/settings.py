from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
import os

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

    # our apps
    'accounts',
    'vendors',
    'customers',
    'services',
    'bookings',
    'promotions',
    'home_sections',
    'curations',
    'service_forms',
    'reviews',
    'discounts',
    'dashboard',
    'support',
    'notifications',
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
DATABASE_URL = config('DATABASE_URL', default='')

if not DATABASE_URL:
    raise ImproperlyConfigured(
        "DATABASE_URL is not set. Add it to your .env file for local "
        "development, or to the environment on the server."
    )

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

STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
)

# Media files (vendor documents, job-start photos)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

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



