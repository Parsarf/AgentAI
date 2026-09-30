"""Private production defaults. Secrets and state supplied by the deployment."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('AGENTAI_SESSION_SECRET', '')
if len(SECRET_KEY) < 48:
    raise ImproperlyConfigured('Provide AGENTAI_SESSION_SECRET (at least 48 random characters)')
DEBUG = False
PUBLIC_ORIGIN = os.environ.get('AGENTAI_PUBLIC_ORIGIN', 'https://localhost')
from urllib.parse import urlsplit
_origin = urlsplit(PUBLIC_ORIGIN)
if _origin.scheme != 'https' or not _origin.hostname or _origin.path or _origin.query or _origin.fragment or _origin.username:
    raise ImproperlyConfigured('AGENTAI_PUBLIC_ORIGIN must be an HTTPS origin')
ALLOWED_HOSTS = [_origin.hostname, 'localhost', '127.0.0.1']
CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN]
STATE_DIR = Path(os.environ.get('AGENTAI_STATE_DIR', BASE_DIR / 'data')).absolute()
for _private_path in [STATE_DIR,STATE_DIR/'platform.sqlite3']:
    if _private_path.is_symlink() or (_private_path.exists() and _private_path.stat().st_mode & 0o077):
        raise ImproperlyConfigured('Account state must be a direct private directory/file (0700/0600)')
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': STATE_DIR / 'platform.sqlite3',
                       'OPTIONS': {'timeout': 5, 'transaction_mode': 'IMMEDIATE'}}}
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'django_otp', 'django_otp.plugins.otp_totp', 'accounts']
MIDDLEWARE = ['accounts.middleware.BoundaryMiddleware', 'django.middleware.security.SecurityMiddleware',
              'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django_otp.middleware.OTPMiddleware',
              'accounts.middleware.AccountMiddleware']
ROOT_URLCONF = 'accounts.urls'
WSGI_APPLICATION = 'accounts.wsgi.application'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.csrf']}}]
AUTH_PASSWORD_VALIDATORS = [
 {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
 {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
 {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
 {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = '__Host-agentai_session'
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_AGE = 12 * 3600
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_NAME = '__Host-agentai_csrf'
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_FAILURE_VIEW = 'accounts.views.csrf_failure'
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
# Gunicorn runs behind a private loopback TLS proxy which overwrites this header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DATA_UPLOAD_MAX_MEMORY_SIZE = 200000
FILE_UPLOAD_MAX_MEMORY_SIZE = 0
DATA_UPLOAD_MAX_NUMBER_FIELDS = 12
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'UTC'
EMAIL_BACKEND = 'accounts.delivery.DisabledEmailBackend'
if os.environ.get('AGENTAI_MAIL_ENABLED') == '1':
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('AGENTAI_SMTP_HOST', '')
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('AGENTAI_SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('AGENTAI_SMTP_PASSWORD', '')
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get('AGENTAI_FROM_EMAIL', 'noreply@localhost')
if os.environ.get('AGENTAI_MAIL_ENABLED') == '1':
    from django.core.validators import validate_email
    validate_email(DEFAULT_FROM_EMAIL)
    if not EMAIL_HOST or DEFAULT_FROM_EMAIL.endswith('@localhost'):
        raise ImproperlyConfigured('Configured SMTP host and sender domain are required before mail activation')
LOGGING = {'version': 1, 'disable_existing_loggers': False,
 'handlers': {'null': {'class': 'logging.NullHandler'}},
 'loggers': {'django': {'handlers': ['null'], 'propagate': False}}}
