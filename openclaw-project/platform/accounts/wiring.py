"""Composition root: the one place that turns settings into working services.

Every HTTP view and every worker command (request_worker, tool_relay, telegram_worker) gets its collaborators here. A view module owns its routes, its input
rules and its error-to-status mapping; it does not know which settings a service needs or how services are put together. That used to be rebuilt per module
(five differently wired chat services, seven switch readers, fifty database handles), which is how one surface ended up with a service that could not do what
another surface's could.

Rules:
  * Everything is built per call from current settings and files. Nothing is cached, so an owner switch, a rotated key or a changed rollout file takes effect on
    the next request without a restart, and `override_settings` works in tests.
  * Nothing here authenticates. `principal(request)` only packages what the middleware and `views.customer()` already verified.
  * Imports of heavy or optional parts stay inside the functions: importing this module must be cheap and must not create an import cycle with the view modules.

Three different "is it on?" questions, each with one owner:
  switch_on(name)                 the owner's global feature switch          agentai_platform/switches.py
  safety_on(account, feature)     a per-account protection, on by default    agentai_platform/safety.py
  own_model_on / mcp_on / memory_on(account)   per-account rollout lists     agentai_platform/rollout.py

Adding a feature: build its service here (one function), gate it with one of the three questions above, and call that function from the view and from any
worker that needs it. See docs/architecture/code-map.md.
"""
from django.conf import settings
from django.db import connection

from agentai_platform.security import Principal
from .store import AccountStore


# ---- identity and storage -----------------------------------------------------------------------------------------------------------------------------

def store():
    return AccountStore(connection.settings_dict['NAME'])


def principal(request):
    """The verified customer of this request. Call only after `views.customer(request)` let it through."""
    return Principal(request.account_id, str(request.user.pk), 'customer')


# ---- the three kinds of switch ------------------------------------------------------------------------------------------------------------------------

def switches():
    from agentai_platform.switches import SwitchStore
    return SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None)


def switch_on(name):
    """One of the owner's global switches (customer_execution, browse_tasks, billing_checkout, open_access, open_signups, connectors_linking, ...). Missing file = off."""
    return switches().is_on(name)


def safety_on(account_id, feature):
    """A per-account protection (agentai_platform/safety.py). Fails closed: any error means the protection applies."""
    from agentai_platform import safety
    try:
        with store().connect() as con:
            return safety.is_on(con, account_id, feature)
    except Exception:
        return True


def own_model_on(account_id):
    """May this account use its own model key at all (the owner's own-model-keys.json)?"""
    from agentai_platform import model_keys
    return model_keys.enabled_for(model_keys.read_engine(settings.ENGINE_FILE), account_id)


def mcp_on(account_id):
    from agentai_platform.mcp_connections import switch
    return switch.enabled(settings.MCP_SWITCH_FILE, account_id)


def memory_on(account_id):
    from agentai_platform import longterm_memory
    return longterm_memory.enabled(settings.LTM_SWITCH_FILE, account_id)


# ---- private files ------------------------------------------------------------------------------------------------------------------------------------

def read_text(path):
    """A configuration file's text, '' when it is not set or cannot be read. For files whose permissions the deployment owns (Stripe keys, the plan)."""
    try:
        with open(path) as handle:
            return handle.read()
    except (OSError, TypeError):
        return ''


def read_private(path, minimum=0):
    """A secret that must be a private regular file (not a symlink, not group/world readable), stripped. None if it is not usable."""
    import stat
    from pathlib import Path
    try:
        p = Path(path)
        if not path or p.is_symlink() or not p.is_file() or p.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return None
        value = p.read_text().strip()
        return value if len(value) >= minimum else None
    except OSError:
        return None


def live_secret():
    """The key the app and the frame gateway share to sign Live-view tickets. b'' = Live view cannot issue tickets."""
    path = getattr(settings, 'LIVE_SECRET_FILE', '')
    try:
        return open(path, 'rb').read().strip() if path else b''
    except OSError:
        return b''


def panel_secret():
    """The key that signs side-panel tickets; b'' when the panel is not configured (no origins or no key file)."""
    from agentai_platform.panel.offer import read_secret
    return read_secret(settings.PANEL_SECRET_FILE) if settings.PANEL_ORIGINS else b''


def vault_keyring():
    """The saved-logins keyring, or None when the vault is off (no key file)."""
    from agentai_platform import vault
    try:
        return vault.Keyring.from_file(getattr(settings, 'VAULT_KEY_FILE', ''))
    except vault.VaultOff:
        return None


# ---- the other processes on this host -----------------------------------------------------------------------------------------------------------------

def browse_rpc(account_id):
    """Client of the root browse service for one account ('' only for the device-token lookup, which names no account yet)."""
    from agentai_platform.browse.client import BrowseRpc
    return BrowseRpc(account_id, settings.BROWSE_SOCKET)


def cell_rpc(account_id):
    """Client of the root cell bridge for one account ('-' for calls that identify a cell rather than act for one)."""
    from agentai_platform.bridge_client import BridgeRpc
    return BridgeRpc(account_id, settings.CELL_BRIDGE_SOCKET)


def cell_gateway(account_id):
    """The customer's own assistant runtime, through the bridge."""
    from agentai_platform.gateway import NativeGateway
    return NativeGateway(cell_rpc(account_id))


# ---- files and artifacts ------------------------------------------------------------------------------------------------------------------------------

def storage_ready():
    return bool(settings.STORAGE_DIR) and settings.STORAGE_READY


def uploads_on():
    return storage_ready() and settings.UPLOADS_ENABLED


def file_service(db=None):
    from agentai_platform.files import FileService
    from agentai_platform.storage import RootStore
    return FileService(db or store(), storage=RootStore(settings.STORAGE_DIR))


def artifact_service(db=None):
    from agentai_platform.artifacts import ArtifactService
    from agentai_platform.storage import RootStore
    key = settings.ARTIFACT_SIGNING_KEY
    return ArtifactService(db or store(), storage=RootStore(settings.STORAGE_DIR), signing_key=key.encode() if isinstance(key, str) else key)


# ---- chat, queue, budget ------------------------------------------------------------------------------------------------------------------------------

def event_service(db=None, **kwargs):
    from agentai_platform.events import EventService
    return EventService(db or store(), **kwargs)


def ledger(db=None, *, funded=False):
    """The budget ledger. Only a `funded` ledger can admit work (it knows the service-wide allowance); the plain one reads summaries."""
    from agentai_platform.budget import BudgetLedger
    return BudgetLedger(db or store(), service_limit_microusd=settings.SERVICE_ALLOCATION_MICROUSD if funded else None)


def request_queue(db=None, *, require_cell=False):
    from agentai_platform.request_queue import RequestQueue
    return RequestQueue(db or store(), require_cell=require_cell,
                        model_selection=lambda account: model_key_store(sealed=False).choices(account)['selected'])


def model_key_store(*, sealed=True):
    """Customers' own model keys. `sealed=False` gives the reader that can see the non-secret facts (host, model, last four) but cannot open a key."""
    from agentai_platform import model_keys
    if not sealed:
        return model_keys.ModelKeyStore(settings.MODEL_KEY_STORE)
    return model_keys.ModelKeyStore(settings.MODEL_KEY_STORE, model_keys.ModelKeyring.derived(settings.SECRET_KEY, settings.MODEL_KEY_FILE or None))


def own_model_active(account_id):
    """True when this account's tasks run on its own model key right now: the feature is open to it and a key is selected. Never raises."""
    try:
        return own_model_on(account_id) and model_key_store(sealed=False).public(account_id) is not None
    except Exception:
        return False


def chat_service(db=None):
    """THE chat service: what the web app, the side panel, generated UI and the request worker all use.

    Its wiring follows the owner's `customer_execution` switch. Off: messages are recorded and wait unfunded, nothing is priced and no cell is contacted. On: a send
    reserves the plan's per-task amount before it may run, needs the account's cell, and can steer a running task or act on a goal through the customer's gateway."""
    from agentai_platform.chat import ChatService, FixedRoute
    db = db or store()
    live = switch_on('customer_execution')
    # Without the owner switch no route is priced, so a send waits unfunded exactly as before.
    kwargs = {'pricer': FixedRoute(settings.CUSTOMER_RESERVATION_MICROUSD, 'plan-reservation-v1')} if live else {}
    return ChatService(db, queue=request_queue(db, require_cell=live), ledger=ledger(db, funded=live), execution=live, browse=switch_on('browse_tasks'),
                       events=event_service(db), gateway_factory=cell_gateway if live else None,      # steering and goal controls talk to the customer's own cell
                       unmetered=own_model_active, **kwargs)


def intake_chat_service(db=None):
    """A chat service that can only RECORD: conversations, projects and messages are stored, but no route is priced and no ledger can admit, so nothing it accepts
    is ever funded or started. Telegram uses it today (its messages are stored and acknowledged; running them from Telegram is an open product decision, see
    docs/architecture/code-map.md). Do not use it for a surface whose messages are meant to run: use `chat_service()`."""
    from agentai_platform.chat import ChatService
    db = db or store()
    return ChatService(db, queue=request_queue(db), ledger=ledger(db))


# ---- integrations -------------------------------------------------------------------------------------------------------------------------------------

def mcp_service(db=None):
    """Remote MCP connections: custody of the customers' connection credentials, plus the OAuth client registrations the owner configured.
    Raises the feature's own ConnectionError('oauth_setup_required') when the registrations file is set but unusable (it must be a private regular file)."""
    import json
    from pathlib import Path
    from agentai_platform.mcp_connections.network import ConnectionError, endpoint_url
    from agentai_platform.mcp_connections.service import ConnectionService, ASANA_URL
    from agentai_platform.model_keys import ModelKeyring
    registrations = {}
    if settings.MCP_OAUTH_CLIENTS_FILE:
        try:
            p = Path(settings.MCP_OAUTH_CLIENTS_FILE)
            if p.is_symlink() or p.stat().st_mode & 0o077:
                raise ValueError('OAuth client registrations must be private')
            if not p.is_file() or p.stat().st_size > 65536: raise ValueError('invalid registration file')
            registrations = json.loads(p.read_text())
            if not isinstance(registrations, dict): raise ValueError('invalid registrations')
            for url, value in registrations.items():
                endpoint_url(url)
                if not isinstance(value, dict) or not isinstance(value.get('client_id'), str) or not value['client_id'] or not isinstance(value.get('issuer'), str):
                    raise ValueError('invalid registration')
                endpoint_url(value['issuer'])
                if value.get('client_secret') is not None and not isinstance(value['client_secret'], str): raise ValueError('invalid secret')
        except (OSError, ValueError):
            raise ConnectionError('oauth_setup_required', 'OAuth registration configuration is unavailable.') from None
    if settings.ASANA_MCP_CLIENT_ID and settings.ASANA_MCP_CLIENT_SECRET:
        registrations[ASANA_URL] = {'client_id': settings.ASANA_MCP_CLIENT_ID, 'client_secret': settings.ASANA_MCP_CLIENT_SECRET,
                                    'issuer': 'https://app.asana.com', 'token_endpoint_auth_method': 'client_secret_post'}
    db = db or store()
    return ConnectionService(db, ModelKeyring.derived(settings.SECRET_KEY, settings.MCP_KEY_FILE or settings.MODEL_KEY_FILE or None),
                             callback_url=settings.PUBLIC_ORIGIN + '/v1/account/mcp/callback', registrations=registrations, metadata_url=settings.MCP_CLIENT_METADATA_URL,
                             events=event_service(db))


def telegram_service(db=None):
    """Telegram ingress and replies. No transport (and so no outbound call) unless the bot is configured."""
    from agentai_platform import telegram
    db = db or store()
    return telegram.TelegramService(db, chat=intake_chat_service(db), transport=telegram.TelegramBotApi(settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_ENABLED else None,
                                    bot_username=settings.TELEGRAM_BOT_USERNAME)


def billing_webhook_secrets():
    return [line.strip() for line in read_text(settings.BILLING_WEBHOOK_SECRET_FILE).splitlines() if line.strip().startswith('whsec_')] \
        if settings.BILLING_WEBHOOK_SECRET_FILE else []


def billing_service(db=None):
    """Built per request so a rotated key or secret takes effect without a restart."""
    import json
    from agentai_platform import billing
    plans = []
    if settings.BILLING_PLAN_FILE:
        try:
            # Free access needs only the plan file; the Stripe price id matters once payments are configured.
            plans = [billing.plan_from_plan_json(json.loads(read_text(settings.BILLING_PLAN_FILE)), settings.BILLING_PRICE_ID or 'price_unconfigured')]
        except (ValueError, KeyError):
            plans = []
    api = None
    if settings.BILLING_SECRET_KEY_FILE and settings.BILLING_API_VERSION:
        api = billing.StripeHttp(lambda: read_text(settings.BILLING_SECRET_KEY_FILE), settings.BILLING_API_VERSION, allow_live=settings.BILLING_ALLOW_LIVE)
    return billing.BillingService(db or store(), api, plans, webhook_secrets=billing_webhook_secrets(),
                                  public_origin=settings.BILLING_PUBLIC_ORIGIN, allow_live=settings.BILLING_ALLOW_LIVE)


def access_mode():
    """How people get in: paid_required wins over open (turning payments on is what ends free access), else invite_only."""
    if switch_on('billing_checkout'): return 'paid_required'
    return 'open' if switch_on('open_access') else 'invite_only'


def memory_service(db=None):
    """The long-term memory service, or None when it is not fully configured (server address, private bank secret, optional key). Never raises."""
    from agentai_platform import longterm_memory as ltm
    try:
        secret = read_private(settings.HINDSIGHT_BANK_SECRET_FILE, 16)
        if not secret or not settings.HINDSIGHT_URL:
            return None
        key = read_private(settings.HINDSIGHT_KEY_FILE) if settings.HINDSIGHT_KEY_FILE else ''
        if key is None:
            return None
        return ltm.LongTermMemory(db or store(), ltm.HindsightClient(settings.HINDSIGHT_URL, key), secret.encode(), enabled=memory_on)
    except (ValueError, OSError):
        return None
