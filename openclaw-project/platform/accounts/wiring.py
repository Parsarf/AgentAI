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
    from agentai_platform.permissions import organization_of
    role = getattr(request, 'org_role', None)
    if role is None:
        from .services import role_of
        role = role_of(request.account_id, request.user.pk)
    from django.db import connection
    connection.ensure_connection()
    return Principal(request.account_id, str(request.user.pk), 'customer', organization_of(connection.connection, request.account_id), role or '')


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
    from agentai_platform import model_keys, organizations
    if not model_keys.enabled_for(model_keys.read_engine(settings.ENGINE_FILE), account_id):
        return False
    try:
        with store().connect() as con:
            return organizations.own_model_key_allowed(con, account_id)      # an organization may decide its members use Lumina's model only (roadmap #15)
    except Exception:
        return True


# ---- connected services and the action pipeline (roadmap Phase 3) ---------------------------------------------------------------------------------------

def connector_registry(db=None):
    """The connectors built on the contract that this host knows. The synthetic (test-only) one is always registered; whether an account may use it is the owner's
    `synthetic_connector` switch, asked per call. Real connectors register here as they are written (platform/CONNECTORS.md)."""
    from agentai_platform import synthetic_connector
    from agentai_platform.connector_kit import Registry
    registry = synthetic_connector.register(Registry(), db or store())
    for provider in sign_in_providers().values():           # mail and calendar providers whose sign-in app is configured on this host
        provider['register'](registry)
    return registry


def sign_in_providers():
    """The providers a customer can sign in to from the dashboard, by name: how to register each, where to send the customer, how to finish, how to renew its token.
    A provider is here only when its sign-in app is configured. This is the one place in the web layer that names a provider."""
    out = {}
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        from agentai_platform import google_hub
        cid, secret = settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
        out[google_hub.PROVIDER] = {'label': google_hub.DECLARATION.label, 'register': google_hub.register,
                                    'address': lambda redirect, state, challenge: google_hub.authorize_url(cid, redirect, state, challenge),
                                    'exchange': google_hub.exchanger(cid, secret), 'refresh': google_hub.refresher(cid, secret),
                                    'needs_any': (google_hub.MAIL_SCOPE, google_hub.CALENDAR_SCOPE)}
    return out


def connector_custody(db=None):
    """Sealed custody for connected services' tokens, or the fail-closed default when no key file is installed."""
    from agentai_platform.connector_custody import SealedCustody, keyring_from_file
    from agentai_platform.connectors import DisabledCustody
    ring = keyring_from_file(settings.CONNECTOR_KEY_FILE)
    return SealedCustody(db or store(), ring) if ring is not None else DisabledCustody()


def connector_service(db=None):
    from agentai_platform.connectors import ConnectorService
    db = db or store()
    events = event_service(db)

    def notify(account, connection, reason):
        # Told once, in the timeline of whatever the customer's assistant is doing now (the settings page shows it either way). Ids and fixed words only.
        with db.connect() as con:
            row = con.execute("SELECT id FROM customer_requests WHERE account_id=? AND state IN ('starting','running') ORDER BY sequence DESC LIMIT 1", (account,)).fetchone()
        if row:
            events.append(account, row['id'], 'progress', {'summary': 'A connected service needs you: reconnect it in Settings.', 'step': 'working'}, 'gateway')
    return ConnectorService(db, custody=connector_custody(db), registry=connector_registry(db), notify=notify)


def connector_client(db=None, connectors=None):
    from agentai_platform.connector_kit import ConnectorClient
    db = db or store()
    connectors = connectors or connector_service(db)
    return ConnectorClient(db, connectors, connectors.registry, limiter=_connector_limiter())


_LIMITER = []


def _connector_limiter():
    """One rate limiter for the process, so every call of an account on a provider shares what the provider said (the Phase 1 limiter)."""
    if not _LIMITER:
        from agentai_platform.model_keys import RouteLimiter
        _LIMITER.append(RouteLimiter(cap=20.0))
    return _LIMITER[0]


def connectors_on(account_id):
    """May this account use connected services built on the contract? The owner's linking switch, or the test-only switch for the synthetic service."""
    return switch_on('connectors_linking') or switch_on('synthetic_connector') or switch_on('mail_calendar_dashboard')      # the dashboard's accounts are connections too: their picker and their grants


def writes_on(account_id):
    return switch_on('connector_writes')


def hub_on(account_id):
    """Is the mail and calendar dashboard shown? The owner's switch."""
    return switch_on('mail_calendar_dashboard')


def hub_services(db=None):
    """-> (connectors, client, sync, hub): the dashboard's sync engine and its reading side, sharing one view of the connections."""
    from agentai_platform.hub import HubService
    from agentai_platform.hub_sync import HubSync
    db = db or store()
    connectors = connector_service(db)
    client = connector_client(db, connectors)
    sync = HubSync(db, connectors, client)
    return connectors, client, sync, HubService(db, connectors, client, sync)


def hub_service(db=None):
    return hub_services(db)[3]


def hub_tools(db=None):
    """The assistant's mail and calendar tools: the same copy the dashboard shows, read only."""
    from agentai_platform.hub_tools import HubTools
    db = db or store()
    return HubTools(db, hub_service(db), enabled=hub_on)


def action_services(db=None):
    """-> (connectors, client, actions, workflows): the action pipeline, built together so they share one view of the connections."""
    from agentai_platform.actions import ActionService
    from agentai_platform.workflows import WorkflowService
    db = db or store()
    connectors = connector_service(db)
    client = connector_client(db, connectors)
    actions = ActionService(db, connectors, client, writes_on=writes_on)
    return connectors, client, actions, WorkflowService(db, actions)


def action_runner(db=None):
    """What the request worker runs between requests: executes approved changes, advances workflows, ends waits that ran out, resumes the chats that waited."""
    from agentai_platform.action_runner import ActionRunner
    db = db or store()
    _connectors, _client, actions, workflows = action_services(db)
    return ActionRunner(db, actions, workflows, chat=chat_service(db))


def connector_tools(db=None):
    """The assistant's connector tools: read through a connected service, prepare a change for approval, ask the customer a question that can wait."""
    from agentai_platform.connector_tools import ConnectorTools
    db = db or store()
    connectors, client, actions, workflows = action_services(db)
    return ConnectorTools(db, connectors, client, actions, workflows, enabled=connectors_on, writes_on=writes_on)


def connector_refresher(db=None):
    from agentai_platform.connector_refresh import ConnectorRefresher
    from agentai_platform.synthetic_connector import SyntheticBench
    db = db or store()
    try:
        mcp = mcp_service(db)
    except Exception:
        mcp = None                                         # remote MCP is not configured on this host: there is nothing of it to refresh
    return ConnectorRefresher(db, connector_service(db), {'synthetic': SyntheticBench.refresher, **{name: p['refresh'] for name, p in sign_in_providers().items()}}, mcp=mcp)


def organization_service(db=None):
    from agentai_platform.organizations import OrganizationService

    def end_sessions(actor_id):
        # A role change or a removal takes effect on the next request: the person's sessions end, as "sign out everywhere" does.
        from accounts.models import Identity
        from accounts.services import models_f_epoch
        Identity.objects.filter(user_id=actor_id).update(epoch=models_f_epoch())
    return OrganizationService(db or store(), on_role_change=end_sessions)


def access_overview(db=None):
    from agentai_platform.access import AccessOverview
    db = db or store()
    connectors = connector_service(db)

    def tool_names(account):
        names = ['lumina_task_update', 'lumina_request_location', 'lumina_show']
        if switch_on('browse_tasks'):
            names += ['lumina_browser', 'lumina_browser_step']
        if storage_ready():
            names.append('lumina_file_deliver')
        if memory_on(account):
            names += ['lumina_memory_recall', 'lumina_memory_remember']
        if mcp_on(account):
            from agentai_platform.mcp_connections.relay import GENERIC
            names += [g['name'] for g in GENERIC]
        if connectors_on(account):
            from agentai_platform.connector_tools import ConnectorTools
            names += sorted(ConnectorTools.names)
        if hub_on(account):
            from agentai_platform.hub_tools import HubTools
            names += sorted(HubTools.names)
        return names

    def model_key(account):
        if not own_model_on(account):
            return None
        return model_key_store(sealed=False).public(account)

    def memory_count(account):
        if not memory_on(account):
            return None
        with db.connect() as con:
            return con.execute("SELECT count(*) FROM longterm_memories WHERE account_id=? AND status='active'", (account,)).fetchone()[0]
    return AccessOverview(db, connectors, connector_client(db, connectors), tool_names=tool_names, model_key=model_key, memory_count=memory_count)


def account_jobs(db=None):
    """Export, deletion and offboarding, with the adapter of every store outside the database. An adapter this host does not have is None (recorded as such by the job)."""
    from agentai_platform.data_lifecycle import AccountJobs
    from agentai_platform.lifecycle.coordinator import Coordinator
    db = db or store()
    connectors = connector_service(db)
    custody = connectors.custody

    def end_connections(account):
        ended = 0
        with db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM connector_connections WHERE account_id=? AND state!='revoked'", (account,))]
            remote = [(r[0], r[1]) for r in con.execute('SELECT id,name FROM mcp_connections WHERE account_id=?', (account,))]
            actor = con.execute("SELECT actor_id FROM memberships WHERE account_id=? AND role='customer' ORDER BY actor_id LIMIT 1", (account,)).fetchone()
        for connection in ids:
            ended += 1 if connectors.revoke_by_system(account, connection, 'offboarding') else 0
        if remote and actor:
            from agentai_platform.security import Principal
            service = mcp_service(db)
            for connection, _name in remote:
                try:
                    service.disconnect(Principal(account, actor[0], 'customer'), connection)
                    ended += 1
                except Exception:
                    pass                                   # an account that is already closed cannot disconnect; the rows and sealed credentials go with the database step
        connectors.purge_revoked()
        return {'ended': ended}

    def forget_memory(account):
        service = memory_service(db)
        if service is None:
            return 'not_on_this_host'
        service.forget_all(account)
        return 'bank removed'

    def remove_model_key(account):
        return 'removed' if model_key_store().delete(account) else 'none'

    def remove_cell(account):
        with db.connect() as con:
            cell = con.execute('''SELECT c.observed_state,d.generation,d.state FROM lifecycle_cells c JOIN deployments d ON d.account_id=c.account_id AND d.id=c.deployment_id
                WHERE c.account_id=?''', (account,)).fetchone()
            busy = con.execute("SELECT 1 FROM operations WHERE account_id=? AND state IN ('pending','running','uncertain')", (account,)).fetchone()
        if cell is None or cell['observed_state'] == 'absent' or cell['state'] == 'deleted':
            return 'done'
        if busy:
            return 'waiting'
        coordinator = Coordinator(db)
        try:
            if cell['observed_state'] == 'running':
                coordinator.request_system(account, key=f'offboard-stop-{cell["generation"]}', generation=cell['generation'], kind='stop')
            elif cell['observed_state'] == 'stopped':
                coordinator.request_account_deletion(account, key=f'offboard-delete-{cell["generation"]}', generation=cell['generation'])
        except Exception:
            pass                                           # the state moved under us: looked at again on the next pass
        return 'waiting'

    def anonymise_identity(account):
        # The sign-in identity: sessions and tokens are removed, the address and the password are erased, and one tombstone remains that says the account was deleted.
        from django.contrib.auth.models import User
        from django.contrib.sessions.models import Session
        from django.utils import timezone
        from accounts.models import ActionToken, EmailJob, Identity, Tombstone
        from accounts.services import models_f_epoch
        users = list(User.objects.filter(identity__account_id=account, identity__role='customer'))
        for user in users:
            ActionToken.objects.filter(user=user).delete()
            EmailJob.objects.filter(user=user, state__in=['pending', 'failed', 'uncertain']).exclude(purpose='offboarding').delete()
            for session in Session.objects.filter(expire_date__gt=timezone.now()):
                if str(session.get_decoded().get('_auth_user_id')) == str(user.pk):
                    session.delete()
            # Not an empty address: sign-in addresses are unique, so the second deleted customer could not be given an empty one too. A placeholder that names nobody.
            user.email, user.username, user.first_name, user.last_name, user.is_active = f'deleted-{user.pk}@deleted.invalid', f'deleted-{user.pk}', '', '', False
            user.set_unusable_password()
            user.save()
            Identity.objects.filter(user=user).update(verified=False, epoch=models_f_epoch())
        Tombstone.objects.get_or_create(account_id=account, object_id=account, kind='account')
        return {'identities': len(users)}

    def cancel_billing(account):
        service = billing_service(db)
        if service.api is None:
            return 'not_on_this_host'
        return service.cancel_for_account(account)

    def confirm(account, actor, report):
        # The confirmation is written before the identity is erased (the address is needed to send it): see offboarding_mail in accounts/lifecycle_data.py.
        from accounts.lifecycle_data import send_deletion_report
        return send_deletion_report(account, report)

    def scan_outside(account):
        found = {}
        if hasattr(custody, 'count'):
            found['connector_tokens'] = custody.count(account)
        try:
            found['model_key'] = 1 if model_key_store(sealed=False).public(account) else 0
        except Exception:
            found['model_key'] = 0
        with db.connect() as con:
            cell = con.execute("SELECT 1 FROM lifecycle_cells WHERE account_id=?", (account,)).fetchone()
        found['cell'] = 1 if cell else 0
        return found

    def scan_identity(account):
        from django.contrib.auth.models import User
        return User.objects.filter(identity__account_id=account, identity__role='customer').exclude(email__endswith='@deleted.invalid').count()

    files = file_store()
    adapters = {'connections': end_connections, 'custody': (lambda account: custody.delete_all(account)) if hasattr(custody, 'delete_all') else None, 'memory': forget_memory,
                'model_key': remove_model_key, 'cell': remove_cell, 'identity': anonymise_identity, 'billing': cancel_billing, 'mail': confirm, 'scan': scan_outside, 'scan_identity': scan_identity}
    return AccountJobs(db, storage=files, adapters=adapters, signing_key=settings.ARTIFACT_SIGNING_KEY.encode() if storage_ready() else b'', cooling_off=settings.ACCOUNT_COOLING_OFF_SECONDS)


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

def file_store():
    """The file store itself (uploads, files the assistant made, export archives), or None where this host has none."""
    if not storage_ready():
        return None
    from agentai_platform.storage import RootStore
    return RootStore(settings.STORAGE_DIR)


def storage_ready():
    return bool(settings.STORAGE_DIR) and settings.STORAGE_READY


def uploads_on():
    """May customers upload? The host has storage and uploads enabled in its configuration, and the owner's switch is on."""
    return storage_ready() and settings.UPLOADS_ENABLED and switch_on('customer_uploads')


def catalogue(db=None):
    from agentai_platform.catalogue import Catalogue
    return Catalogue(db or store())


def file_service(db=None):
    from agentai_platform.files import FileService
    from agentai_platform.storage import RootStore
    return FileService(db or store(), storage=RootStore(settings.STORAGE_DIR))


def artifact_service(db=None):
    from agentai_platform.artifacts import ArtifactService
    from agentai_platform.storage import RootStore
    key = settings.ARTIFACT_SIGNING_KEY
    return ArtifactService(db or store(), storage=RootStore(settings.STORAGE_DIR), signing_key=key.encode() if isinstance(key, str) else key)


def convert_on():
    return bool(settings.RENDER_SOCKET)


def renderer():
    """Client of the host render service (file conversions), or None where it is not installed: files are then delivered as written, never converted."""
    if not settings.RENDER_SOCKET:
        return None
    from agentai_platform.render.client import RenderRpc
    return RenderRpc(settings.RENDER_SOCKET)


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
    records a reservation (the customer's own task limit, or the no-limit marker) before it may run, needs the account's cell, and can steer a running task or act on a goal through the customer's gateway."""
    from agentai_platform.chat import ChatService, FixedRoute
    db = db or store()
    live = switch_on('customer_execution')
    # Without the owner switch no route is priced, so a send waits unfunded exactly as before.
    from agentai_platform import spend_limits
    # Lumina puts no ceiling on a task: the reservation is the no-limit marker unless the customer chose a task limit in Settings (ChatService._reservation).
    kwargs = {'pricer': FixedRoute(settings.CUSTOMER_RESERVATION_MICROUSD or spend_limits.NO_LIMIT, 'no-limit-v1')} if live else {}
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
