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
TELEGRAM_BOT_TOKEN = os.environ.get('AGENTAI_TELEGRAM_BOT_TOKEN', '')
TELEGRAM_WEBHOOK_SECRET = os.environ.get('AGENTAI_TELEGRAM_WEBHOOK_SECRET', '')
TELEGRAM_BOT_USERNAME = os.environ.get('AGENTAI_TELEGRAM_BOT_USERNAME', '').lstrip('@')
if TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_USERNAME:
    # Partial configuration must fail loudly; the ingress stays fail-closed.
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET or not TELEGRAM_BOT_USERNAME:
        raise ImproperlyConfigured('Telegram ingress requires bot token, webhook secret (>=32 chars) and bot username together')
    if len(TELEGRAM_WEBHOOK_SECRET) < 32:
        raise ImproperlyConfigured('Telegram webhook secret must be at least 32 characters')
    TELEGRAM_ENABLED = True
else:
    TELEGRAM_ENABLED = False
# Phase 8 storage: artifact/file content lives outside the metadata database.
STORAGE_DIR = os.environ.get('AGENTAI_STORAGE_DIR', '')
ARTIFACT_SIGNING_KEY = os.environ.get('AGENTAI_ARTIFACT_SIGNING_KEY', '')
STORAGE_READY = bool(STORAGE_DIR) and len(ARTIFACT_SIGNING_KEY) >= 32
if STORAGE_DIR and not STORAGE_READY:
    raise ImproperlyConfigured('Artifact storage requires AGENTAI_ARTIFACT_SIGNING_KEY (>=32 chars)')
# Documented scan capability (signature/UTF-8/JSON/binary validation). Without it,
# uploads stay disabled per the launch contract.
UPLOADS_ENABLED = os.environ.get('AGENTAI_UPLOADS_ENABLED') == '1'
DATA_UPLOAD_MAX_MEMORY_SIZE = 31457280  # 25MiB batch cap plus multipart overhead
LOGGING = {'version': 1, 'disable_existing_loggers': False,
 'handlers': {'null': {'class': 'logging.NullHandler'}},
 'loggers': {'django': {'handlers': ['null'], 'propagate': False}}}
# Owner feature switches (written by the private ops dashboard, read-only here). Missing = everything off.
SWITCHES_FILE = os.environ.get('AGENTAI_SWITCHES_FILE', '')
SWITCH_FACTS_FILE = os.environ.get('AGENTAI_SWITCH_FACTS_FILE', '')
# Host cell bridge socket and the per-message spend reserved before a customer request may run.
CELL_BRIDGE_SOCKET = os.environ.get('AGENTAI_CELL_BRIDGE_SOCKET', '/run/agentai-cell-bridge/bridge.sock')
# Total provider spend the service will fund across all customers: 2 trial accounts x $25 included usage.
SERVICE_ALLOCATION_MICROUSD = int(os.environ.get('AGENTAI_SERVICE_ALLOCATION_MICROUSD', '50000000'))
ROUTING_CONFIG_FILE = os.environ.get('AGENTAI_ROUTING_CONFIG_FILE', '/var/lib/agentai-platform/routing/routing.json')
TYPESAFE_KEY_FILE = os.environ.get('AGENTAI_TYPESAFE_KEY_FILE', '/var/lib/agentai-platform/routing/typesafe.key')
UI_BUNDLE_DIR = os.environ.get('AGENTAI_UI_BUNDLE_DIR', '/var/lib/agentai-platform/ui')
BROWSE_SOCKET = os.environ.get('AGENTAI_BROWSE_SOCKET', '/run/agentai-browse/browse.sock')
# Native execution: the browser tool relay cells reach over the bridge address (see agentai_platform/tool_relay.py), and how long a "keep working until complete" goal may run.
TOOL_RELAY_BIND = os.environ.get('AGENTAI_TOOL_RELAY_BIND', '10.77.0.1')
TOOL_RELAY_PORT = int(os.environ.get('AGENTAI_TOOL_RELAY_PORT', '4100'))
GOAL_CHAIN_LIMIT = int(os.environ.get('AGENTAI_GOAL_CHAIN_LIMIT', '20'))      # turns of one goal before the customer decides whether to resume it
# Live view: the frame gateway is a separate process; this file holds the secret both sides use to sign and check watch tickets.
LIVE_SECRET_FILE = os.environ.get('AGENTAI_LIVE_SECRET_FILE', '')
LIVE_PATH = os.environ.get('AGENTAI_LIVE_PATH', '/v1/live')
# Side panel in the customer's own Chrome: the key that signs its tickets (app user only, never readable by the browse service; no file = feature off) and the extension
# origins allowed to call /v1/panel/* (comma separated, each exactly chrome-extension://<32 letters>; none = feature off).
PANEL_SECRET_FILE = os.environ.get('AGENTAI_PANEL_SECRET_FILE', '')
PANEL_ORIGINS = [o.strip() for o in os.environ.get('AGENTAI_PANEL_ORIGINS', '').split(',') if o.strip()]
SAFETY_SNAPSHOT_FILE = os.environ.get('AGENTAI_SAFETY_SNAPSHOT', str(STATE_DIR / 'safety-switches.json'))   # the switch settings other processes read (the browse service, the supervisor); written by the app on every change
SAFETY_OWNER_ACCOUNT = os.environ.get('AGENTAI_SAFETY_OWNER_ACCOUNT', '')   # the one account that may see and change its own safety switches; empty = nobody
VAULT_KEY_FILE = os.environ.get('AGENTAI_VAULT_KEY_FILE', '')          # saved logins and cards; without this root-only key file the vault is off
MODEL_KEY_STORE = os.environ.get('AGENTAI_MODEL_KEY_STORE', str(STATE_DIR / 'model-keys.json'))     # customers' own model keys, encrypted (agentai_platform/model_keys.py)
MODEL_KEY_FILE = os.environ.get('AGENTAI_MODEL_KEY_FILE', '')            # optional dedicated encryption key for them; without it a key derived from the app secret is used
ENGINE_FILE = os.environ.get('AGENTAI_ENGINE_FILE', '/var/lib/agentai-platform/own-model-keys.json')   # who may use their own model key: {"own_model_keys": true | [account ids]}
CUSTOMER_RESERVATION_MICROUSD = int(os.environ.get('AGENTAI_CUSTOMER_RESERVATION_MICROUSD', '1000000'))

# Billing (Stripe TEST mode first). Secrets live in private files read at call time, never in settings values.
BILLING_SECRET_KEY_FILE = os.environ.get('AGENTAI_BILLING_SECRET_KEY_FILE', '')
BILLING_WEBHOOK_SECRET_FILE = os.environ.get('AGENTAI_BILLING_WEBHOOK_SECRET_FILE', '')   # one whsec_ per line (rotation overlap)
BILLING_API_VERSION = os.environ.get('AGENTAI_BILLING_API_VERSION', '')                   # pinned Stripe API version, required
BILLING_PRICE_ID = os.environ.get('AGENTAI_BILLING_PRICE_ID', '')                         # the one launch plan price
BILLING_PLAN_FILE = os.environ.get('AGENTAI_BILLING_PLAN_FILE', '')                       # product/plan.json copy
BILLING_PUBLIC_ORIGIN = os.environ.get('AGENTAI_BILLING_PUBLIC_ORIGIN', 'https://getlumina.pro')
BILLING_ALLOW_LIVE = os.environ.get('AGENTAI_BILLING_ALLOW_LIVE') == '1'                   # owner-only, off by default

# Remote MCP custody uses the host-only encryption key; no credentials enter cells.
MCP_KEY_FILE = os.environ.get('AGENTAI_MCP_KEY_FILE', '')
MCP_OAUTH_CLIENTS_FILE = os.environ.get('AGENTAI_MCP_OAUTH_CLIENTS_FILE', '')
ASANA_MCP_CLIENT_ID = os.environ.get('ASANA_MCP_CLIENT_ID', '')
ASANA_MCP_CLIENT_SECRET = os.environ.get('ASANA_MCP_CLIENT_SECRET', '')
