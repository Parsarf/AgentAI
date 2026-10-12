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
                 catalog: dict | None = None, clock=time.time):
        self.store, self.clock = store, clock
        self.custody = custody or DisabledCustody()
        self.providers = providers or {}
        self.catalog = catalog or CATALOG
        self.coordinator = Coordinator(store, clock=clock)

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
            verifier_ref = self.custody.put(principal.account_id, 'pkce', verifier.encode())
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
            secret_ref = self.custody.put(principal.account_id, row['service'], json.dumps(result.tokens).encode())
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

    # ---------- read gating ----------

    def authorize_read(self, principal: Principal, service: str, resource: str | None = None) -> ReadGrant:
        svc = self.catalog.get(service)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT id,state,secret_ref,selected_resources FROM connector_connections
                WHERE account_id=? AND service=? AND state!='revoked' ORDER BY created_epoch DESC LIMIT 1''',
                              (principal.account_id, service)).fetchone()
        if not svc or not row:
            raise NotFound('unavailable')
        if row['state'] != 'connected':
            raise ConnectorError('reconnect required')
        if svc.needs_selection and resource not in json.loads(row['selected_resources']):
            raise NotFound('unavailable')
        return ReadGrant(row['id'], service, row['secret_ref'])

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

    def _revoke(self, con, principal, connection_id, secret_ref) -> int:
        """Access is revoked first and unconditionally; credential deletion is best effort.
        If custody deletion fails the reference is kept for ``purge_revoked`` and audited uncertain."""
        now = int(self.clock())
        cur = con.execute('''UPDATE connector_operations SET state='cancelled' WHERE account_id=?
            AND connection_id=? AND state IN ('pending','running')''', (principal.account_id, connection_id))
        deleted = True
        if secret_ref:
            try:
                self.custody.delete(principal.account_id, secret_ref)
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
                    self.custody.delete(row['account_id'], row['secret_ref'])
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
            if kind in WRITE_KINDS:
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
            ref = self.custody.put(principal.account_id, 'browser-credential', secret)
            if row['credential_ref']:
                self.custody.delete(principal.account_id, row['credential_ref'])
            con.execute('UPDATE browser_profiles SET credential_ref=? WHERE account_id=? AND id=?',
                        (ref, principal.account_id, profile_id))

    def save_session(self, principal: Principal, profile_id: str, cookie_jar: bytes) -> None:
        with self.coordinator.transaction() as con:
            row = self._profile(con, principal, profile_id)
            ref = self.custody.put(principal.account_id, 'browser-session', cookie_jar)
            if row['session_ref']:
                self.custody.delete(principal.account_id, row['session_ref'])
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
                    self.custody.delete(principal.account_id, ref)
            con.execute('''UPDATE browser_profiles SET state='revoked',credential_ref=NULL,session_ref=NULL
                WHERE account_id=? AND id=?''', (principal.account_id, profile_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, profile_id,
                                    'browser_profile.revoke', 'completed')
