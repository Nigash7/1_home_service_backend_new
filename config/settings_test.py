"""
Settings for running the test suite.

Points Django at a throwaway SQLite file so `manage.py test` never has to
create or drop a database on the shared Postgres server the team develops
against. Everything else is inherited unchanged.

    python manage.py test --settings=config.settings_test
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Fast, deterministic hashing -- the real hasher dominates test runtime.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# django-axes locks accounts out after repeated logins, which several tests do.
AXES_ENABLED = False

FCM_ENABLED = False
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
