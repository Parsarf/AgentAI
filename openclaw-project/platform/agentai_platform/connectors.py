"""Customer-owned connectors (Phase 11): protected linking, read-only gating,
failure handling, operation receipts, local drafts and credentialed browser
profiles.

Provider tokens never enter the database, responses, events, memory or project
execution: they live in a custody backend (native secret mechanism) behind
account-bound opaque references. ``DisabledCustody`` is the default, so every
link fails closed until a real custody backend and provider client
registrations exist. Writes are absent: the production catalog lists no
writable kind for any service, and a scope name alone is never approval.
"""
from __future__ import annotations
import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.parse import urlencode
from .events import redact
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal
from . import ssrf

LINK_TTL_SECONDS = 600
MAX_RETRIES = 2
MAX_BACKOFF_SECONDS = 60
MAX_DRAFTS = 50
MAX_PROFILES = 5
READ_KINDS = {'read'}
WRITE_KINDS = {'send', 'share', 'write', 'delete', 'push', 'merge', 'modify', 'invite'}
GOOGLE_IDENTITY = frozenset({'openid', 'email'})


class ConnectorError(Exception):
    """Message is always generic; provider detail never propagates."""


class ConnectorNotConfigured(ConnectorError):
    pass


class WrongAccount(ConnectorError):
    """A sign-in meant to add permissions to one account came back signed in as another: nothing changed."""


class WriteDisabled(ConnectorError):
    pass


@dataclass(frozen=True)
class Service:
    name: str
    label: str
    reader: str                       # the only agent allowed to receive raw content
    allowed_scopes: frozenset
    needs_selection: bool = False     # a repo / Drive item / mailbox window must be chosen
    writable_kinds: frozenset = frozenset()
    disclosure: str = ''
    launch_scope: str = 'later'


CATALOG = {
    'gmail': Service('gmail', 'Gmail (read-only)', 'researcher',
                     frozenset({'https://www.googleapis.com/auth/gmail.readonly'}) | GOOGLE_IDENTITY,
                     disclosure='Read-only mail access. Compose/send scopes are never requested: '
                                'a compose scope can also send, and a scope name is not approval.'),
    'calendar': Service('calendar', 'Google Calendar (read-only)', 'researcher',
                        frozenset({'https://www.googleapis.com/auth/calendar.readonly',
                                   'https://www.googleapis.com/auth/calendar.events.readonly'}) | GOOGLE_IDENTITY,
                        disclosure="Reads today's events in your timezone."),
    'drive': Service('drive', 'Google Drive (read-only)', 'researcher',
                     frozenset({'https://www.googleapis.com/auth/drive.file',
                                'https://www.googleapis.com/auth/drive.readonly'}) | GOOGLE_IDENTITY,
                     needs_selection=True,
                     disclosure='drive.readonly lets the connector read every file in your Drive; '
                                'drive.file limits access to items you pick. Prefer drive.file.'),
    'github': Service('github', 'GitHub (selected repositories, read-only)', 'researcher',
                      frozenset({'metadata:read', 'contents:read', 'issues:read', 'pull_requests:read'}),
                      needs_selection=True,
                      disclosure='Access is limited to the repositories you select at installation.'),
}


class Custody(Protocol):
    def put(self, account_id: str, label: str, secret: bytes) -> str: ...
    def get(self, account_id: str, ref: str) -> bytes: ...
    def delete(self, account_id: str, ref: str) -> None: ...


class DisabledCustody:
    def put(self, account_id, label, secret): raise ConnectorNotConfigured('custody unavailable')
    def get(self, account_id, ref): raise ConnectorNotConfigured('custody unavailable')
    def delete(self, account_id, ref): return None  # nothing can exist in an unconfigured backend; revoke must still work


class SyntheticCustody:
    """Test double with the real contract: references are account-bound."""

    def __init__(self):
        self._items: dict[str, tuple[str, bytes]] = {}

    def put(self, account_id, label, secret):
        ref = 'ref-' + uuid.uuid4().hex
        self._items[ref] = (account_id, bytes(secret))
        return ref

    def get(self, account_id, ref):
        owner, secret = self._items.get(ref, (None, None))
        if owner != account_id:
            raise NotFound('unavailable')
        return secret

    def delete(self, account_id, ref):
        if self._items.get(ref, (None,))[0] == account_id:
            del self._items[ref]



def custody_put(custody, con, account_id, label, secret):
    """Store a secret from inside the caller's transaction, on the caller's connection when the backend keeps its secrets in this database (so both commit together)."""
    return custody.put_in(con, account_id, label, secret) if hasattr(custody, 'put_in') else custody.put(account_id, label, secret)


def custody_delete(custody, con, account_id, ref):
    return custody.delete_in(con, account_id, ref) if hasattr(custody, 'delete_in') else custody.delete(account_id, ref)


@dataclass(frozen=True)
class ProviderConfig:
    client_id: str
    authorize_url: str
    redirect_uris: frozenset


@dataclass
class Exchange:
    """Result of a provider code exchange performed by a host-side adapter."""
    tokens: dict = field(repr=False)
    identity: str = ''
    granted_scopes: list = field(default_factory=list)


@dataclass(frozen=True)
class ReadGrant:
    connection_id: str
    service: str
    secret_ref: str = field(repr=False)
    scope: tuple = ()                 # ((resource kind, resource id or '*', access), ...): what this connection may reach (roadmap #13)


@dataclass(frozen=True)
class WriteGrant:
    connection_id: str
    service: str
    secret_ref: str = field(repr=False)
    scope: tuple = ()


SYSTEM_ACTOR = 'system'               # the actor recorded when Lumina itself ends a connection (the provider revoked it, a policy changed, the account is leaving)
REVOKE_SOURCES = ('customer', 'admin', 'policy', 'provider', 'offboarding')


@dataclass(frozen=True)
class FailureAction:
    action: str            # retry | reconnect | fail
    delay_seconds: int = 0


def next_delay(attempt: int, retry_after=None) -> int:
    if type(attempt) is not int or attempt < 0:
        raise ValueError('invalid attempt')
    base = int(retry_after) if isinstance(retry_after, (int, str)) and str(retry_after).isdigit() else 2 ** attempt
    return max(1, min(base, MAX_BACKOFF_SECONDS))


def classify_failure(status: int, attempt: int, retry_after=None) -> FailureAction:
    """Bounded retries: 429/5xx retry up to MAX_RETRIES; 401 means reconnect; others fail."""
    if status == 401:
        return FailureAction('reconnect')
    if (status == 429 or 500 <= status < 600) and attempt < MAX_RETRIES:
        return FailureAction('retry', next_delay(attempt, retry_after))
    return FailureAction('fail')


def attribute(service: str, source_ref: str, text: str) -> dict:
    """Wrap provider content as attributed untrusted data. Only restricted readers
    ever see ``text``; callers store/return this reference, never standing orders."""
    return {'service': service, 'source': str(source_ref)[:300], 'trust': 'untrusted_data',
            'instruction': False, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'excerpt': redact(text[:500])}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class ConnectorService:
    def __init__(self, store, *, custody: Custody | None = None, providers: dict | None = None,
                 catalog: dict | None = None, clock=time.time, registry=None, notify=None):
        self.store, self.clock = store, clock
        self.custody = custody or DisabledCustody()
        self.providers = providers or {}
        self.registry = registry         # connector_kit.Registry: the connectors built on the contract (Phase 3). Their write kinds come from their declarations
        self.notify = notify             # callable(account_id, connection_id, reason): tell the customer once that a connection needs them; None = say nothing
        self.catalog = dict(catalog or CATALOG)
        for provider in (registry.providers() if registry is not None else ()):
            d = registry.declaration(provider)
            self.catalog[provider] = Service(provider, d.label, 'researcher', frozenset(d.scopes), needs_selection=False,
                                             writable_kinds=frozenset(w.name for w in d.write_kinds), disclosure=d.disclosure)
        self.coordinator = Coordinator(store, clock=clock)

    def declared(self, service):
        return self.registry.declaration(service) if self.registry is not None else None

    def service_of(self, account_id, connection_id) -> str | None:
        """Which service a connection of this account is to (None when there is no such connection): the owner switch that governs changes depends on it."""
        with self.store.connect() as con:
            row = con.execute("SELECT service FROM connector_connections WHERE account_id=? AND id=? AND state!='revoked'", (account_id, str(connection_id or ''))).fetchone()
        return row['service'] if row else None

    # ---------- listing ----------

    def overview(self, principal: Principal) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = {r['service']: r for r in con.execute('''SELECT id,service,state,identity_label,granted_scopes,
                selected_resources FROM connector_connections WHERE account_id=? AND state!='revoked'
                ORDER BY created_epoch''', (principal.account_id,))}
        out = []
        for name, svc in self.catalog.items():
            row = rows.get(name)
            out.append({'service': name, 'label': svc.label, 'disclosure': svc.disclosure,
                        'writes': False, 'configured': name in self.providers,
                        'state': row['state'] if row else 'not_connected',
                        'connection_id': row['id'] if row else None,
                        'identity': row['identity_label'] if row else None,
                        'scopes': json.loads(row['granted_scopes']) if row else [],
                        'selected': json.loads(row['selected_resources']) if row else []})
        return out

    # ---------- OAuth linking ----------

    def begin_link(self, principal: Principal, service: str, redirect_uri: str,
                   selected_resources=()) -> dict:
        svc = self.catalog.get(service)
        provider = self.providers.get(service)
        if not svc or not provider:
            raise ConnectorNotConfigured('connector not configured')
        if redirect_uri not in provider.redirect_uris:
            raise ConnectorError('redirect not allowed')
        selected = self._selection(svc, selected_resources)
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            verifier_ref = custody_put(self.custody, con, principal.account_id, 'pkce', verifier.encode())
            con.execute('DELETE FROM connector_link_states WHERE expires_epoch<?', (now,))
            con.execute('''INSERT INTO connector_link_states(account_id,state_hash,actor_id,service,redirect_uri,
                verifier_ref,selected_resources,expires_epoch) VALUES (?,?,?,?,?,?,?,?)''',
                        (principal.account_id, hashlib.sha256(state.encode()).hexdigest(), principal.actor_id,
                         service, redirect_uri, verifier_ref, json.dumps(selected), now + LINK_TTL_SECONDS))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, service,
                                    'connector.link.begin', 'completed')
        query = urlencode({'client_id': provider.client_id, 'redirect_uri': redirect_uri, 'state': state,
                           'response_type': 'code', 'code_challenge': challenge, 'code_challenge_method': 'S256',
                           'scope': ' '.join(sorted(svc.allowed_scopes - GOOGLE_IDENTITY)),
                           'access_type': 'offline', 'include_granted_scopes': 'false'})
        return {'authorize_url': provider.authorize_url + '?' + query, 'expires_in': LINK_TTL_SECONDS}

    def _selection(self, svc, selected):
        selected = [str(item) for item in selected]
        if svc.needs_selection and not selected:
            raise ConnectorError('a selection is required')
        if len(selected) > 20 or any(not item or len(item) > 200 for item in selected):
            raise ConnectorError('invalid selection')
        return selected

    def complete_link(self, principal: Principal, state: str, code: str, redirect_uri: str,
                      exchange: Callable[[str, str, str], Exchange],
                      revoke_tokens: Callable[[dict], None] | None = None) -> str:
        digest = hashlib.sha256(str(state).encode()).hexdigest()
        now = int(self.clock())
        # Transaction 1: burn the state before any provider call, so a failed or
        # replayed callback can never be used again.
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            cur = con.execute('''UPDATE connector_link_states SET used_epoch=? WHERE state_hash=? AND account_id=?
                AND actor_id=? AND used_epoch IS NULL AND expires_epoch>=?''',
                              (now, digest, principal.account_id, principal.actor_id, now))
            if cur.rowcount != 1:
                raise ConnectorError('link failed')
            row = con.execute('''SELECT service,redirect_uri,verifier_ref,selected_resources
                FROM connector_link_states WHERE state_hash=?''', (digest,)).fetchone()
            row = dict(row)
        verifier = self.custody.get(principal.account_id, row['verifier_ref']).decode()
        self.custody.delete(principal.account_id, row['verifier_ref'])
        if redirect_uri != row['redirect_uri']:
            raise ConnectorError('link failed')
        svc = self.catalog[row['service']]
        try:
            result = exchange(code, verifier, redirect_uri)
        except Exception:
            raise ConnectorError('link failed') from None
        granted = set(result.granted_scopes)
        if (not granted or not granted <= svc.allowed_scopes or not (granted - GOOGLE_IDENTITY)
                or not result.identity or len(result.identity) > 320):
            if revoke_tokens:
                try:
                    revoke_tokens(result.tokens)
                except Exception:
                    pass
            raise ConnectorError('granted scopes exceed the allowed read-only set or identity unverified')
        # Transaction 2: store the connection; replacing an older one revokes it.
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            secret_ref = custody_put(self.custody, con, principal.account_id, row['service'], json.dumps(result.tokens).encode())
            for old in con.execute('''SELECT id,secret_ref FROM connector_connections WHERE account_id=?
                AND service=? AND state!='revoked' ''', (principal.account_id, row['service'])).fetchall():
                self._revoke(con, principal, old['id'], old['secret_ref'])
            connection_id = uuid.uuid4().hex
            con.execute('''INSERT INTO connector_connections(account_id,id,service,state,identity_label,
                granted_scopes,selected_resources,secret_ref,created_epoch,updated_epoch)
                VALUES (?,?,?,'connected',?,?,?,?,?,?)''',
                        (principal.account_id, connection_id, row['service'], result.identity,
                         json.dumps(sorted(granted)), row['selected_resources'], secret_ref, now, now))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id,
                                    'connector.link.complete', 'completed')
            return connection_id

    # ---------- linking a connector built on the contract (its provider module builds the sign-in address and does the exchange) ----------

    def start_link(self, principal: Principal, service: str, redirect_uri: str, *, upgrade: str | None = None) -> dict:
        """Begin signing in to a declared provider. -> {'state', 'challenge', 'expires_in'}: the provider's module puts these in its sign-in address. The state is single
        use, bound to this person, and expires; the PKCE verifier waits in custody, never in a row a view reads. `upgrade` is a connection of this person to `service` that
        the sign-in adds permissions to (finish_link then changes it in place); -> also {'identity'}, the address to sign in as."""
        from .security import require
        if self.declared(service) is None:
            raise ConnectorNotConfigured('connector not configured')
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'connection.create', con=con)
            from . import organizations
            if not organizations.connector_allowed(con, principal.account_id, service):
                raise ConnectorError('your organization does not allow this service')
            identity = None
            if upgrade is not None:
                target = con.execute("SELECT identity_label FROM connector_connections WHERE account_id=? AND id=? AND service=? AND state!='revoked'",
                                     (principal.account_id, str(upgrade), service)).fetchone()
                if target is None:
                    raise ConnectorError('link failed')
                require(principal, 'connection.use', con=con)
                identity = target['identity_label']
            verifier_ref = custody_put(self.custody, con, principal.account_id, 'pkce', verifier.encode())
            con.execute('DELETE FROM connector_link_states WHERE expires_epoch<?', (now,))
            con.execute("""INSERT INTO connector_link_states(account_id,state_hash,actor_id,service,redirect_uri,verifier_ref,selected_resources,expires_epoch,upgrade_connection_id)
                VALUES (?,?,?,?,?,?,'[]',?,?)""", (principal.account_id, hashlib.sha256(state.encode()).hexdigest(), principal.actor_id, service, redirect_uri, verifier_ref,
                                                   now + LINK_TTL_SECONDS, str(upgrade) if upgrade is not None else None))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, upgrade or service, 'connector.link.begin', 'completed')
        out = {'state': state, 'challenge': _b64(hashlib.sha256(verifier.encode()).digest()), 'expires_in': LINK_TTL_SECONDS}
        if identity is not None:
            out['identity'] = identity
        return out

    def link_service(self, principal: Principal, state: str) -> str | None:
        """Which provider a sign-in that is still open belongs to (None when there is none for this person): the callback asks before it finishes, so the right exchange is used."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT service FROM connector_link_states WHERE state_hash=? AND account_id=? AND actor_id=? AND used_epoch IS NULL AND expires_epoch>=?',
                              (hashlib.sha256(str(state).encode()).hexdigest(), principal.account_id, principal.actor_id, int(self.clock()))).fetchone()
        return row['service'] if row else None

    def finish_link(self, principal: Principal, state: str, code: str, redirect_uri: str, exchange: Callable[[str, str, str], Exchange], *, needs_any=()) -> str:
        """Finish signing in: the state is burnt before the provider is called (a failed or replayed callback can never be used again), the code is exchanged, and the
        connection is recorded with NO grants. Refused when the identity is unverified, when a scope outside the declaration came back, or when none of `needs_any` (the
        scopes that make the connection useful) was granted. -> the connection id."""
        digest, now = hashlib.sha256(str(state).encode()).hexdigest(), int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if con.execute("""UPDATE connector_link_states SET used_epoch=? WHERE state_hash=? AND account_id=? AND actor_id=? AND used_epoch IS NULL AND expires_epoch>=?""",
                           (now, digest, principal.account_id, principal.actor_id, now)).rowcount != 1:
                raise ConnectorError('link failed')
            row = dict(con.execute('SELECT service,redirect_uri,verifier_ref,upgrade_connection_id FROM connector_link_states WHERE state_hash=?', (digest,)).fetchone())
        verifier = self.custody.get(principal.account_id, row['verifier_ref']).decode()
        self.custody.delete(principal.account_id, row['verifier_ref'])
        declared = self.declared(row['service'])
        if redirect_uri != row['redirect_uri'] or declared is None:
            raise ConnectorError('link failed')
        try:
            result = exchange(code, verifier, redirect_uri)
        except Exception:
            raise ConnectorError('link failed') from None
        granted = set(result.granted_scopes)
        if not result.identity or len(result.identity) > 320 or not granted <= set(declared.scopes) or (needs_any and not granted & set(needs_any)):
            raise ConnectorError('the account could not be verified, or it gave none of the access that was asked for')
        expires = result.tokens.get('expires_in') if isinstance(result.tokens, dict) else None
        expires = int(expires) if isinstance(expires, (int, float)) and expires > 0 else None
        if row['upgrade_connection_id']:
            return self._upgrade(principal, row['service'], row['upgrade_connection_id'], result.identity, result.tokens, sorted(granted), expires)
        return self.connect_declared(principal, row['service'], result.identity, tokens=result.tokens, scopes=sorted(granted), expires_in=expires)

    def _upgrade(self, principal, service, connection_id, identity, tokens, scopes, expires_in) -> str:
        """A sign-in that added permissions to an existing connection: the same account (or it is refused, and nothing changes), its tokens replaced in custody and its
        permissions set to what the provider now says, in place. Its grants, its synced copy and its id stay. -> the connection id."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            old = con.execute("SELECT secret_ref,identity_label FROM connector_connections WHERE account_id=? AND id=? AND service=? AND state!='revoked'",
                              (principal.account_id, connection_id, service)).fetchone()
            if old is None or str(identity).lower() != str(old['identity_label']).lower():
                raise WrongAccount('signed in as a different account')
            secret_ref = custody_put(self.custody, con, principal.account_id, service, json.dumps(tokens).encode()) if tokens else old['secret_ref']
            con.execute("""UPDATE connector_connections SET state='connected',needs_reason=NULL,needs_notified_epoch=NULL,granted_scopes=?,secret_ref=?,updated_epoch=?,
                expires_epoch=?,refresh_after_epoch=NULL WHERE account_id=? AND id=?""",
                        (json.dumps(sorted(scopes)), secret_ref, now, now + expires_in if expires_in else None, principal.account_id, connection_id))
            if old['secret_ref'] and old['secret_ref'] != secret_ref:
                custody_delete(self.custody, con, principal.account_id, old['secret_ref'])
            self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id, 'connector.link.upgrade', 'completed')
        return connection_id

    # ---------- read gating ----------

    def authorize_read(self, principal: Principal, service: str, resource: str | None = None, *, resource_kind: str | None = None) -> ReadGrant:
        """May this person's assistant read `resource` through their connection to `service`? -> a grant carrying the connection's whole scope.
        A connector built on the contract (a declaration with resource kinds) reaches only what its customer chose: with no grant it reaches nothing."""
        return self._authorize(principal, service, resource, resource_kind, 'read', ReadGrant)

    def authorize_write(self, principal: Principal, service: str, resource: str, *, resource_kind: str) -> WriteGrant:
        """The same for a change: the resource must be granted for writing. This is not approval of any particular change (that is the action record: actions.py)."""
        return self._authorize(principal, service, resource, resource_kind, 'write', WriteGrant)

    def _authorize(self, principal, service, resource, resource_kind, access, kind):
        svc = self.catalog.get(service)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT id,state,secret_ref,selected_resources FROM connector_connections
                WHERE account_id=? AND service=? AND state!='revoked' ORDER BY created_epoch DESC LIMIT 1''',
                              (principal.account_id, service)).fetchone()
            scope = self.scope(con, principal.account_id, row['id']) if row else ()
            declared = self.declared(service)
            if svc and row and row['state'] == 'connected' and declared is not None and declared.resource_kinds:
                if resource is None or resource_kind is None or not self.granted(con, principal.account_id, row['id'], resource_kind, resource, access):
                    raise NotFound('unavailable')
        if not svc or not row:
            raise NotFound('unavailable')
        if row['state'] != 'connected':
            raise ConnectorError('reconnect required')
        if access == 'write' and (declared is None or not declared.resource_kinds):
            raise WriteDisabled('provider writes are not enabled for this connector')
        if svc.needs_selection and resource not in json.loads(row['selected_resources']):
            raise NotFound('unavailable')
        return kind(row['id'], service, row['secret_ref'], scope)

    # ---------- resource grants (roadmap #13) ----------

    @staticmethod
    def scope(con, account_id, connection_id) -> tuple:
        try:
            return tuple((r[0], r[1], r[2]) for r in con.execute('SELECT resource_kind,resource_id,access FROM connector_grants WHERE account_id=? AND connection_id=? ORDER BY resource_kind,resource_id',
                                                                (account_id, connection_id)))
        except Exception as error:
            if 'no such table' in str(error):
                return ()
            raise

    @staticmethod
    def granted(con, account_id, connection_id, resource_kind, resource_id, access='read') -> bool:
        """Is this one resource covered? By its own grant or by "everything" of its kind; a write needs a write grant, which also covers reading."""
        rows = con.execute('SELECT access FROM connector_grants WHERE account_id=? AND connection_id=? AND resource_kind=? AND resource_id IN (?,?)',
                           (account_id, connection_id, str(resource_kind), str(resource_id), '*')).fetchall()
        return any(r[0] == 'write' or access == 'read' for r in rows)

    def grants(self, principal: Principal, connection_id: str) -> list[dict]:
        with self.store.connect() as con:
            self._connection(con, principal, connection_id)
            return [dict(r) for r in con.execute('''SELECT resource_kind,resource_id,resource_name,access,granted_epoch FROM connector_grants
                WHERE account_id=? AND connection_id=? ORDER BY resource_kind,resource_name,resource_id''', (principal.account_id, connection_id))]

    def set_grants(self, principal: Principal, connection_id: str, grants) -> list[dict]:
        """Replace what a connection may reach with exactly this list: [{'kind','id','name'?,'access'}]. An id of '*' is "everything of this kind" and has to be asked for
        in so many words; an empty list means it can reach nothing again."""
        from .security import require
        if not isinstance(grants, list) or len(grants) > 500:
            raise ValueError('invalid grants')
        clean = {}
        for g in grants:
            if (not isinstance(g, dict) or not isinstance(g.get('kind'), str) or not isinstance(g.get('id'), str) or not 1 <= len(g['kind']) <= 40
                    or not 1 <= len(g['id']) <= 300 or g.get('access', 'read') not in ('read', 'write') or not isinstance(g.get('name', ''), str)):
                raise ValueError('invalid grant')
            clean[(g['kind'], g['id'])] = (g.get('name', '')[:200], g.get('access', 'read'))
        with self.coordinator.transaction() as con:
            row = self._connection(con, principal, connection_id)
            require(principal, 'connection.create', con=con)
            if row['state'] == 'revoked':
                raise NotFound('unavailable')
            declared = self.declared(row['service'])
            if declared is not None and {kind for kind, _ in clean} - set(declared.resource_kinds):
                raise ValueError('this service has no such kind of resource')
            if declared is not None and not declared.write_kinds and any(access == 'write' for _, access in clean.values()):
                raise ValueError('this service cannot be changed through Lumina')
            now = int(self.clock())
            con.execute('DELETE FROM connector_grants WHERE account_id=? AND connection_id=?', (principal.account_id, connection_id))
            for (kind, rid), (name, access) in sorted(clean.items()):
                con.execute('INSERT INTO connector_grants(account_id,connection_id,resource_kind,resource_id,resource_name,access,granted_by,granted_epoch) VALUES (?,?,?,?,?,?,?,?)',
                            (principal.account_id, connection_id, kind, rid, name, access, principal.actor_id, now))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id, 'connector.grants.set', 'completed')
        return self.grants(principal, connection_id)

    @staticmethod
    def describe_scope(scope, declared=None) -> str:
        """The plain sentence of the permission page, from the same rows enforcement reads: "Can read: 2 calendars. Cannot change anything." """
        def count(rows):
            parts = []
            for kind in sorted({k for k, _i, _a in rows}):
                ids = [i for k, i, _a in rows if k == kind]
                parts.append(f'every {kind}' if '*' in ids else f'{len(ids)} {kind}{"s" if len(ids) != 1 else ""}')
            return ', '.join(parts)
        if not scope:
            return 'Can read: nothing yet (nothing has been chosen). Cannot change anything.'
        writes = [g for g in scope if g[2] == 'write']
        return f'Can read: {count(scope)}. ' + (f'Can change (each change still needs your approval): {count(writes)}.' if writes else 'Cannot change anything.')

    # ---------- connectors built on the contract ----------

    def connect_declared(self, principal: Principal, service: str, identity: str, *, tokens: dict | None = None, scopes=(), expires_in=None, mcp_connection_id=None) -> str:
        """Host-side: record a connection to a connector built on the contract, after its own linking step succeeded (an OAuth exchange, a token the customer entered in a
        protected form, or a remote MCP connection that already exists). Tokens go to custody; the connection starts with NO grants."""
        from . import organizations
        from .security import require
        declared = self.declared(service)
        if declared is None:
            raise ConnectorNotConfigured('connector not configured')
        if not isinstance(identity, str) or not 1 <= len(identity) <= 320:
            raise ConnectorError('link failed')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'connection.create', con=con)
            if not organizations.connector_allowed(con, principal.account_id, service):
                raise ConnectorError('your organization does not allow this service')
            secret_ref = custody_put(self.custody, con, principal.account_id, service, json.dumps(tokens).encode()) if tokens else None
            # A provider with several accounts per person (declared `several_accounts`, the dashboard's mail and calendar providers: #D2) keeps its other accounts:
            # connecting again replaces only the connection to the same identity. Every other connector has one connection, replaced by a new one.
            several = bool(getattr(declared, 'several_accounts', False))
            for old in con.execute("SELECT id,secret_ref,identity_label FROM connector_connections WHERE account_id=? AND service=? AND state!='revoked'", (principal.account_id, service)).fetchall():
                if not several or old['identity_label'].lower() == identity.lower():
                    self._revoke(con, principal, old['id'], old['secret_ref'])
            connection_id = uuid.uuid4().hex
            con.execute('''INSERT INTO connector_connections(account_id,id,service,state,identity_label,granted_scopes,selected_resources,secret_ref,created_epoch,updated_epoch,
                expires_epoch,refresh_after_epoch,mcp_connection_id) VALUES (?,?,?,'connected',?,?,'[]',?,?,?,?,?,?)''',
                        (principal.account_id, connection_id, service, identity, json.dumps(sorted(scopes)), secret_ref, now, now,
                         now + int(expires_in) if expires_in else None, None, mcp_connection_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id, 'connector.link.complete', 'completed')
            return connection_id

    def needs_customer(self, account_id: str, connection_id: str, reason: str = 'reconnect') -> bool:
        """A connection can no longer be used without its customer (the provider refused the token, a refresh needs a new consent). Marked once, told once. -> True when it
        was newly marked."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            changed = con.execute('''UPDATE connector_connections SET state='reconnect_required',needs_reason=?,updated_epoch=? WHERE account_id=? AND id=? AND state='connected' ''',
                                  (str(reason)[:40], now, account_id, connection_id)).rowcount == 1
            tell = con.execute('UPDATE connector_connections SET needs_notified_epoch=? WHERE account_id=? AND id=? AND state=\'reconnect_required\' AND needs_notified_epoch IS NULL',
                               (now, account_id, connection_id)).rowcount == 1
            if changed:
                self.coordinator._audit(con, account_id, SYSTEM_ACTOR, connection_id, 'connector.reconnect_required', 'completed')
        if tell and self.notify is not None:
            try:
                self.notify(account_id, connection_id, reason)
            except Exception:
                pass                             # the page still shows it; the notice is a convenience
        return changed

    def credential_for(self, principal: Principal, grant: ReadGrant) -> dict:
        """Host-side adapters only. Binds the reference to the caller's account."""
        return json.loads(self.custody.get(principal.account_id, grant.secret_ref))

    # ---------- failures, disconnect ----------

    def report_failure(self, principal: Principal, connection_id: str, status: int, attempt: int,
                       retry_after=None) -> FailureAction:
        action = classify_failure(status, attempt, retry_after)
        if action.action == 'reconnect':
            with self.coordinator.transaction() as con:
                self._connection(con, principal, connection_id)
                con.execute('''UPDATE connector_connections SET state='reconnect_required',updated_epoch=?
                    WHERE account_id=? AND id=? AND state='connected' ''',
                            (int(self.clock()), principal.account_id, connection_id))
                self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id,
                                        'connector.reconnect_required', 'completed')
        return action

    def disconnect(self, principal: Principal, connection_id: str) -> int:
        """Revoke access, delete custody and cancel queued operations. Returns operations cancelled."""
        with self.coordinator.transaction() as con:
            row = self._connection(con, principal, connection_id)
            if row['state'] == 'revoked':
                return 0
            return self._revoke(con, principal, connection_id, row['secret_ref'])

    def revoke(self, principal: Principal, connection_id: str, source: str = 'customer') -> dict:
        """End a connection (roadmap #17): one audited operation, with a receipt of what was stopped. From this moment no call uses its token (every call reads the connection's
        state first), its tokens leave custody, what it had been allowed to reach is forgotten, anything waiting on it is ended and anything scheduled on it is paused."""
        from .security import require
        if source not in REVOKE_SOURCES:
            raise ValueError('invalid source')
        with self.coordinator.transaction() as con:
            row = self._connection(con, principal, connection_id)
            require(principal, 'connection.remove', con=con)
            if row['state'] == 'revoked':
                return self._receipt(con, principal.account_id, connection_id) or {'connection_id': connection_id, 'already': True}
            self._revoke(con, principal, connection_id, row['secret_ref'], source=source)
            return self._receipt(con, principal.account_id, connection_id)

    def revoke_by_system(self, account_id: str, connection_id: str, source: str) -> dict | None:
        """The same, started by Lumina: the provider revoked the access (seen at a call or a refresh), an organization policy no longer allows the service, or the account is
        being offboarded. Needs no signed-in person; it is audited under the system actor."""
        if source not in REVOKE_SOURCES:
            raise ValueError('invalid source')
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT * FROM connector_connections WHERE account_id=? AND id=?', (account_id, identifier(connection_id))).fetchone()
            if not row or row['state'] == 'revoked':
                return None
            self._revoke(con, Principal(account_id, SYSTEM_ACTOR, 'system'), connection_id, row['secret_ref'], source=source)
            return self._receipt(con, account_id, connection_id)

    def revocations(self, principal: Principal, limit: int = 20) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return [{'id': r['id'], 'connection_id': r['connection_id'], 'source': r['source'], 'stopped': json.loads(r['stopped_json']), 'created_epoch': r['created_epoch']}
                    for r in con.execute('SELECT * FROM connector_revocations WHERE account_id=? ORDER BY created_epoch DESC,id LIMIT ?', (principal.account_id, max(1, min(int(limit), 100))))]

    @staticmethod
    def _receipt(con, account_id, connection_id):
        r = con.execute('SELECT * FROM connector_revocations WHERE account_id=? AND connection_id=? ORDER BY created_epoch DESC LIMIT 1', (account_id, connection_id)).fetchone()
        return {'id': r['id'], 'connection_id': r['connection_id'], 'source': r['source'], 'stopped': json.loads(r['stopped_json']), 'created_epoch': r['created_epoch']} if r else None

    def _revoke(self, con, principal, connection_id, secret_ref, source='customer') -> int:
        """Access is revoked first and unconditionally; credential deletion is best effort.
        If custody deletion fails the reference is kept for ``purge_revoked`` and audited uncertain."""
        now = int(self.clock())
        cur = con.execute('''UPDATE connector_operations SET state='cancelled' WHERE account_id=?
            AND connection_id=? AND state IN ('pending','running')''', (principal.account_id, connection_id))
        stopped = {'operations_cancelled': cur.rowcount}

        def also(name, sql, args):
            # Tables of later migrations: an older database simply has nothing there to stop.
            try:
                stopped[name] = con.execute(sql, args).rowcount
            except Exception as error:
                if 'no such table' not in str(error) and 'no such column' not in str(error):
                    raise
        account = principal.account_id
        also('grants_removed', 'DELETE FROM connector_grants WHERE account_id=? AND connection_id=?', (account, connection_id))
        also('freshness_removed', 'DELETE FROM connector_freshness WHERE account_id=? AND connection_id=?', (account, connection_id))
        also('automatic_approvals_removed', 'DELETE FROM action_auto_approvals WHERE account_id=? AND connection_id=?', (account, connection_id))
        also('actions_ended', "UPDATE actions SET state='expired',ended_reason='connection_removed',updated_epoch=? WHERE account_id=? AND connection_id=? AND state IN ('proposed','approved')",
             (now, account, connection_id))
        also('handoffs_ended', "UPDATE handoffs SET state='expired',answered_epoch=? WHERE account_id=? AND state='waiting' AND action_id IN (SELECT id FROM actions WHERE account_id=? AND connection_id=?)",
             (now, account, account, connection_id))
        also('schedules_paused', "UPDATE schedules SET state='paused',pause_reason='Its connection was removed.' WHERE account_id=? AND needs_connection_id=? AND state='active'", (account, connection_id))
        # The dashboard's copy of this connection's mail and calendars goes with it (#D2): headers, opened bodies, events, calendars and the sync state.
        for name, table in (('mail_messages_removed', 'hub_messages'), ('mail_threads_removed', 'hub_threads'), ('events_removed', 'hub_events'),
                            ('calendars_removed', 'hub_calendars'), ('sync_removed', 'hub_sync')):
            also(name, f'DELETE FROM {table} WHERE account_id=? AND connection_id=?', (account, connection_id))
        try:
            con.execute('INSERT INTO connector_revocations(account_id,id,connection_id,source,stopped_json,created_epoch) VALUES (?,?,?,?,?,?)',
                        (account, uuid.uuid4().hex, connection_id, source, json.dumps(stopped, sort_keys=True), now))
        except Exception as error:
            if 'no such table' not in str(error):
                raise
        deleted = True
        if secret_ref:
            try:
                custody_delete(self.custody, con, principal.account_id, secret_ref)
            except Exception:
                deleted = False
        con.execute('''UPDATE connector_connections SET state='revoked',secret_ref=?,revoked_epoch=?,
            updated_epoch=? WHERE account_id=? AND id=?''',
                    (None if deleted else secret_ref, now, now, principal.account_id, connection_id))
        self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id,
                                'connector.disconnect', 'completed' if deleted else 'uncertain')
        return cur.rowcount

    def purge_revoked(self) -> int:
        """Operator/host job: retry custody deletion for revoked connections that kept a reference."""
        purged = 0
        with self.coordinator.transaction() as con:
            for row in con.execute("SELECT account_id,id,secret_ref FROM connector_connections "
                                   "WHERE state='revoked' AND secret_ref IS NOT NULL").fetchall():
                try:
                    custody_delete(self.custody, con, row['account_id'], row['secret_ref'])
                except Exception:
                    continue
                con.execute('UPDATE connector_connections SET secret_ref=NULL WHERE account_id=? AND id=?',
                            (row['account_id'], row['id']))
                purged += 1
        return purged

    def _connection(self, con, principal, connection_id):
        self.store._authorize(con, principal)
        row = con.execute('SELECT * FROM connector_connections WHERE account_id=? AND id=?',
                          (principal.account_id, identifier(connection_id))).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    # ---------- operations and receipts ----------

    def begin_operation(self, principal: Principal, connection_id: str, kind: str, key: str,
                        payload: dict, *, target: str = '', authorization: dict | None = None) -> str:
        identifier(key)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.coordinator.transaction() as con:
            conn = self._connection(con, principal, connection_id)
            if conn['state'] != 'connected':
                raise ConnectorError('reconnect required')
            declared = self.catalog.get(conn['service'])
            if kind in WRITE_KINDS or (declared is not None and kind in declared.writable_kinds):
                self._authorize_write(conn['service'], kind, digest, target, authorization)
            elif kind not in READ_KINDS:
                raise ConnectorError('unsupported operation')
            existing = con.execute('''SELECT id,state,request_hash FROM connector_operations
                WHERE account_id=? AND idempotency_key=?''', (principal.account_id, key)).fetchone()
            if existing:
                if existing['request_hash'] != digest:
                    raise Conflict('idempotency key reused with a different request')
                if existing['state'] == 'uncertain':
                    raise Conflict('reconcile the uncertain operation with the provider receipt first')
                return existing['id']
            operation_id = uuid.uuid4().hex
            con.execute('''INSERT INTO connector_operations(account_id,id,connection_id,kind,state,
                idempotency_key,request_hash,target,created_epoch) VALUES (?,?,?,?,'running',?,?,?,?)''',
                        (principal.account_id, operation_id, connection_id, kind, key, digest, target[:300],
                         int(self.clock())))
            return operation_id

    def _authorize_write(self, service, kind, digest, target, authorization):
        svc = self.catalog.get(service)
        if not svc or kind not in svc.writable_kinds:
            raise WriteDisabled('provider writes are not enabled for this connector')
        if (not authorization or authorization.get('payload_hash') != digest
                or authorization.get('target') != target
                or int(authorization.get('expires_epoch', 0)) < int(self.clock())):
            raise WriteDisabled('exact payload/target/expiry authorization required')

    def finish_operation(self, principal: Principal, operation_id: str, outcome: str,
                         provider_receipt: str | None = None) -> None:
        if outcome not in {'completed', 'failed', 'uncertain'}:
            raise ValueError('invalid outcome')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            cur = con.execute('''UPDATE connector_operations SET state=?,provider_receipt=? WHERE account_id=?
                AND id=? AND state='running' ''', (outcome, provider_receipt, principal.account_id, operation_id))
            if cur.rowcount != 1:
                raise Conflict('operation is not running (it may have been cancelled by disconnect)')

    def reconcile(self, principal: Principal, operation_id: str, provider_receipt: str | None) -> str:
        """Resolve an uncertain operation from the provider's receipt, never by resending."""
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            state = 'completed' if provider_receipt else 'failed'
            cur = con.execute('''UPDATE connector_operations SET state=?,provider_receipt=? WHERE account_id=?
                AND id=? AND state='uncertain' ''', (state, provider_receipt, principal.account_id, operation_id))
            if cur.rowcount != 1:
                raise NotFound('unavailable')
            return state

    # ---------- local draft proposals (no provider write path) ----------

    def propose_draft(self, principal: Principal, service: str, kind: str, title: str, body: str) -> str:
        if service not in self.catalog or kind not in {'email', 'event', 'repository_change'}:
            raise ValueError('invalid draft')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if con.execute("SELECT count(*) FROM connector_drafts WHERE account_id=? AND state='proposed'",
                           (principal.account_id,)).fetchone()[0] >= MAX_DRAFTS:
                raise Conflict('draft limit reached')
            draft_id = uuid.uuid4().hex
            con.execute('INSERT INTO connector_drafts VALUES (?,?,?,?,?,?,?,?)',
                        (principal.account_id, draft_id, service, kind, title, body, 'proposed', int(self.clock())))
            return draft_id

    def drafts(self, principal: Principal) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return [dict(r) for r in con.execute('''SELECT id,service,kind,title,body,state FROM connector_drafts
                WHERE account_id=? AND state='proposed' ORDER BY created_epoch''', (principal.account_id,))]


class BrowserProfiles:
    """Account-bound credentialed browser profiles (INT-05). Credentials and cookie
    jars are custody references; no method returns a secret to a model-facing caller."""

    def __init__(self, store, *, custody: Custody | None = None, resolver=ssrf.system_resolver,
                 clock=time.time):
        self.store, self.clock, self.resolver = store, clock, resolver
        self.custody = custody or DisabledCustody()
        self.coordinator = Coordinator(store, clock=clock)

    def create(self, principal: Principal, label: str, allowed_hosts) -> str:
        hosts = sorted({str(h).lower() for h in allowed_hosts})
        if not 1 <= len(hosts) <= 10 or any(not h or '/' in h or ':' in h or ' ' in h for h in hosts):
            raise ValueError('invalid host allowlist')
        if not isinstance(label, str) or not 1 <= len(label) <= 80:
            raise ValueError('invalid label')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if con.execute("SELECT count(*) FROM browser_profiles WHERE account_id=? AND state='active'",
                           (principal.account_id,)).fetchone()[0] >= MAX_PROFILES:
                raise Conflict('profile limit reached')
            profile_id = uuid.uuid4().hex
            con.execute('''INSERT INTO browser_profiles(account_id,id,label,allowed_hosts,state,created_epoch)
                VALUES (?,?,?,?,'active',?)''', (principal.account_id, profile_id, label, json.dumps(hosts),
                                                 int(self.clock())))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, profile_id,
                                    'browser_profile.create', 'completed')
            return profile_id

    def _profile(self, con, principal, profile_id):
        self.store._authorize(con, principal)
        row = con.execute("SELECT * FROM browser_profiles WHERE account_id=? AND id=? AND state='active'",
                          (principal.account_id, identifier(profile_id))).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    def set_credential(self, principal: Principal, profile_id: str, secret: bytes) -> None:
        """Called by the protected login flow only; stores a reference, returns nothing."""
        with self.coordinator.transaction() as con:
            row = self._profile(con, principal, profile_id)
            ref = custody_put(self.custody, con, principal.account_id, 'browser-credential', secret)
            if row['credential_ref']:
                custody_delete(self.custody, con, principal.account_id, row['credential_ref'])
            con.execute('UPDATE browser_profiles SET credential_ref=? WHERE account_id=? AND id=?',
                        (ref, principal.account_id, profile_id))

    def save_session(self, principal: Principal, profile_id: str, cookie_jar: bytes) -> None:
        with self.coordinator.transaction() as con:
            row = self._profile(con, principal, profile_id)
            ref = custody_put(self.custody, con, principal.account_id, 'browser-session', cookie_jar)
            if row['session_ref']:
                custody_delete(self.custody, con, principal.account_id, row['session_ref'])
            con.execute('UPDATE browser_profiles SET session_ref=? WHERE account_id=? AND id=?',
                        (ref, principal.account_id, profile_id))

    def check_navigation(self, principal: Principal, profile_id: str, url: str, fetch=None) -> str:
        """Validate a destination (and, with ``fetch``, every redirect hop) against the profile allowlist."""
        with self.store.connect() as con:
            hosts = json.loads(self._profile(con, principal, profile_id)['allowed_hosts'])
        try:
            if fetch is None:
                return ssrf.check_url(url, hosts, resolver=self.resolver)
            return ssrf.follow(url, hosts, fetch, resolver=self.resolver)
        except ssrf.Blocked:
            raise ConnectorError('destination not allowed') from None

    def session_for(self, principal: Principal, profile_id: str) -> bytes | None:
        """Host-side browser launcher only: returns the cookie jar bytes for this account's profile."""
        with self.store.connect() as con:
            row = self._profile(con, principal, profile_id)
        return self.custody.get(principal.account_id, row['session_ref']) if row['session_ref'] else None

    def revoke(self, principal: Principal, profile_id: str) -> None:
        with self.coordinator.transaction() as con:
            row = self._profile(con, principal, profile_id)
            for ref in (row['credential_ref'], row['session_ref']):
                if ref:
                    custody_delete(self.custody, con, principal.account_id, ref)
            con.execute('''UPDATE browser_profiles SET state='revoked',credential_ref=NULL,session_ref=NULL
                WHERE account_id=? AND id=?''', (principal.account_id, profile_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, profile_id,
                                    'browser_profile.revoke', 'completed')
