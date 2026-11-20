"""The connector contract (roadmap #22 to #25): the one way to read from, and the one way to write to, any outside system.

A connector is a DECLARATION plus an ADAPTER.

* The declaration says what the provider is: how it authenticates, which kinds of resource it has, which read operations and which write kinds, whether records carry a
  version token, how it pages, and how its errors map. It is data; nothing in it is executed.
* The adapter does the provider's calls. Two ways to write one, behind the same contract: a first-party adapter (HTTP calls with the token from custody) or an MCP wrapper
  (an official remote MCP server reached through mcp_connections, its tools mapped onto the contract's operations: `McpAdapter`). The declaration records which and why.

Everything outbound goes through `ConnectorClient`, which applies, in this order: is the connection still usable RIGHT NOW (read from the database at call time, never from
a cache, so a removed or revoked connection stops at its next call); does the person's role and their organization's policy allow it; do the connection's grants cover the
resource; the provider's rate limit (one limiter per account and provider, shared by concurrent calls); the paging caps; then the call. Results are filtered by the grants
again before they return, every provider error becomes exactly one of six kinds, and what was read is recorded for freshness. Nothing else reaches callers.

Stdlib only. Provider text never leaves this module in an error: a fault carries a kind and, at most, a time.
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from . import organizations, permissions
from .model_keys import RouteLimiter

# -- errors: exactly six kinds ------------------------------------------------------------------------------------------------------------------------------
FAULT_KINDS = ('retry_later', 'needs_customer', 'refused', 'not_found', 'conflict', 'invalid')
FAULT_WORDS = {
    'retry_later': 'The service is busy or limiting requests right now. Nothing was changed. It can be tried again later.',
    'needs_customer': 'This connection needs the customer: it must be reconnected or given a permission it does not have.',
    'refused': 'This is not allowed: the connection, the customer\'s choices or their organization do not permit it.',
    'not_found': 'That item does not exist in the connected service, or this connection may not reach it.',
    'conflict': 'The record changed in the connected service since it was read. Nothing was overwritten.',
    'invalid': 'The request was not valid for the connected service. Nothing was changed.',
}
DEFAULT_ERROR_MAP = {400: 'invalid', 401: 'needs_customer', 403: 'refused', 404: 'not_found', 409: 'conflict', 412: 'conflict', 422: 'invalid', 429: 'retry_later'}


class ConnectorFault(Exception):
    """The only error a caller of the connector layer ever sees. `kind` is one of FAULT_KINDS; `retry_at` is an epoch second when the provider said when."""
    def __init__(self, kind, retry_at=None):
        if kind not in FAULT_KINDS:
            raise ValueError('unknown fault kind')
        super().__init__(kind)
        self.kind, self.retry_at = kind, retry_at

    @property
    def words(self):
        return FAULT_WORDS[self.kind]


log = logging.getLogger(__name__)


class ProviderError(Exception):
    """What an adapter raises: the provider's HTTP status (or 0), its error code when it has one, and Retry-After seconds. Never the provider's text."""
    def __init__(self, status=0, code='', retry_after=None):
        super().__init__(f'provider error {status}')
        self.status, self.code, self.retry_after = int(status or 0), str(code or '')[:60], retry_after


class Signal(Exception):
    """Not a failure: something an adapter tells its caller (for example "this cursor is no longer valid, start again"). It passes through the client untouched."""


class Unanswered(Exception):
    """A write was sent and no answer came back (timeout, dropped connection). Its outcome is unknown: it must be read back, never sent again blindly."""


# -- the declaration --------------------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class WriteKind:
    name: str                          # 'note.update', 'message.send' ... stable: it is what approvals, policy and automatic approval are keyed by
    label: str                         # what the customer reads: "Change a note"
    policy_kind: str = 'write'         # the organization policy word it falls under (send | share | write | delete | invite ...)
    undo: str | None = None            # the write kind that reverses it (its inverse), or None
    irreversible_reason: str = ''      # required when there is no inverse: why it cannot be taken back, in a sentence the customer reads
    compensations: tuple = ()          # follow-up write kinds defined in code that make up for it when it cannot be undone (#28)
    undo_seconds: int = 3600           # how long undo is offered
    needs_version: bool = False        # the write changes an existing record: it carries the version it was based on (#25)
    capability: str = ''               # mail and calendar providers: the dashboard capability it belongs to (hub_model.WRITE_CAPABILITIES), i.e. the permission it needs


@dataclass(frozen=True)
class Caps:
    pages: int = 20
    items: int = 500
    bytes: int = 2_000_000
    seconds: float = 20.0


@dataclass(frozen=True)
class Declaration:
    provider: str
    label: str
    auth: str = 'oauth'                # oauth | token | none | mcp
    scopes: tuple = ()
    resource_kinds: tuple = ()         # what a grant can name: ('calendar',), ('folder', 'label') ...
    record_kinds: tuple = ()
    read_operations: tuple = ('list', 'read', 'search')
    write_kinds: tuple = ()            # WriteKind rows
    change_tokens: bool = False        # the provider can say "what changed since"
    version_token: str | None = None   # etag | revision | sequence | updated_time (a last resort) | None
    preconditions: bool = False        # a write can carry the version as a precondition; otherwise the client re-reads and compares just before writing
    idempotency_keys: bool = False     # the provider accepts an idempotency key on writes
    paging: str = 'cursor'             # cursor | page_token | offset
    rate_limit_headers: tuple = ('Retry-After',)
    error_map: dict = field(default_factory=dict)      # status or provider code -> one of FAULT_KINDS; DEFAULT_ERROR_MAP fills the rest
    implementation: str = 'first_party'                # first_party | mcp
    reason: str = ''                   # why this implementation was chosen
    hosts: tuple = ()                  # the only hosts a first-party adapter may call (the destination guard)
    freshness_seconds: dict = field(default_factory=dict)   # resource kind -> how old its data may be before an answer flags it; '*' is the default
    caps: Caps = Caps()
    disclosure: str = ''
    hub: object = None                 # hub_model.HubCaps when this provider has mail or calendars for the dashboard (#D1); None otherwise
    several_accounts: bool = False     # a person may connect more than one account of this provider (each its own connection, told apart by its identity)

    def write_kind(self, name):
        return next((w for w in self.write_kinds if w.name == name), None)

    def fault(self, error) -> ConnectorFault:
        """Exactly one kind for any provider error. A 5xx or an error with no status is `retry_later`; anything unmapped is `invalid` (our request was wrong)."""
        if isinstance(error, ConnectorFault):
            return error
        status, code = getattr(error, 'status', 0), getattr(error, 'code', '')
        kind = self.error_map.get(code) or self.error_map.get(status) or DEFAULT_ERROR_MAP.get(status)
        if kind is None:
            kind = 'retry_later' if status == 0 or 500 <= status < 600 else 'invalid'
        retry = getattr(error, 'retry_after', None)
        try:
            retry_at = int(time.time() + min(3600.0, max(1.0, float(retry)))) if kind == 'retry_later' and retry is not None else None
        except (TypeError, ValueError):
            retry_at = None
        return ConnectorFault(kind, retry_at)


class Registry:
    """The connectors this host knows: provider -> (declaration, adapter factory). A declaration is checked when it is registered: a write kind must have an inverse or say why
    it cannot be undone, an inverse and every compensation must be write kinds of the same connector, and nothing may be declared twice."""
    def __init__(self):
        self._items = {}

    def register(self, declaration: Declaration, adapter_factory):
        if not isinstance(declaration, Declaration) or not declaration.provider or declaration.provider in self._items:
            raise ValueError('invalid or duplicate connector')
        if declaration.implementation not in ('first_party', 'mcp') or not declaration.reason:
            raise ValueError('a connector records how it is implemented and why')
        if declaration.paging not in ('cursor', 'page_token', 'offset'):
            raise ValueError('unknown paging style')
        if set(declaration.error_map.values()) - set(FAULT_KINDS):
            raise ValueError('an error maps to an unknown kind')
        names = [w.name for w in declaration.write_kinds]
        if len(set(names)) != len(names):
            raise ValueError('a write kind is declared twice')
        for kind in declaration.write_kinds:
            if not kind.undo and not kind.irreversible_reason.strip():
                raise ValueError(f'{kind.name}: a write kind registers its inverse or says why it cannot be undone')
            if kind.undo and kind.undo not in names:
                raise ValueError(f'{kind.name}: its inverse is not a write kind of this connector')
            if set(kind.compensations) - set(names):
                raise ValueError(f'{kind.name}: a compensation is not a write kind of this connector')
        self._items[declaration.provider] = (declaration, adapter_factory)

    def declaration(self, provider):
        found = self._items.get(provider)
        return found[0] if found else None

    def adapter(self, provider):
        found = self._items.get(provider)
        return found[1]() if found else None

    def providers(self):
        return list(self._items)


# -- paging (#23) ---------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Page:
    """What an adapter returns for one page: the items, where to go on (None = the end), and the provider's estimate of the total when it gives one."""
    items: list
    next: object = None
    total: int | None = None


@dataclass
class PageResult:
    items: list
    complete: bool                     # True only when the provider said there is nothing more
    count: int
    total_estimate: int | None
    continuation: str | None           # an opaque handle to carry on from (None when complete)
    stopped_by: str | None             # pages | items | bytes | seconds | None

    def words(self) -> str:
        """The sentence every tool result carries, so a partial set is never presented as complete."""
        if self.complete:
            return f'All {self.count} item{"s" if self.count != 1 else ""} are shown: this is complete.'
        about = f' of about {self.total_estimate}' if self.total_estimate and self.total_estimate > self.count else ''
        return f'PARTIAL RESULT: the first {self.count}{about} are shown, and there are more. Do not present this as everything. Ask to continue to get the rest.'

    def public(self) -> dict:
        return {'count': self.count, 'complete': self.complete, 'total_estimate': self.total_estimate, 'continuation': self.continuation, 'stopped_by': self.stopped_by}


def _handle(style, token) -> str:
    return json.dumps({'s': style, 't': token}, separators=(',', ':'))


def _unhandle(style, handle):
    if handle is None:
        return 0 if style == 'offset' else None
    try:
        data = json.loads(handle)
        if not isinstance(data, dict) or data.get('s') != style:
            raise ValueError
        token = data.get('t')
    except (ValueError, TypeError):
        raise ConnectorFault('invalid') from None
    if style == 'offset' and (type(token) is not int or token < 0):
        raise ConnectorFault('invalid')
    return token


def paginate(fetch, *, style='cursor', caps: Caps = Caps(), continuation=None, clock=time.monotonic, size=None) -> PageResult:
    """One helper for cursor, page-token and offset paging, with hard caps on pages, items, bytes and time.

    `fetch(position, limit) -> Page`: `position` is the cursor or page token (None at the start) or, for the offset style, the number of items to skip. Stops at the first cap
    that is reached and says which; the result then carries a continuation handle and `complete=False`. `size(item)` measures an item (default: its JSON length)."""
    if style not in ('cursor', 'page_token', 'offset'):
        raise ValueError('unknown paging style')
    size = size or (lambda item: len(json.dumps(item, default=str)))
    position, items, total, used, started, pages, stopped = _unhandle(style, continuation), [], None, 0, clock(), 0, None
    while True:
        if pages >= caps.pages:
            stopped = 'pages'; break
        if clock() - started >= caps.seconds:
            stopped = 'seconds'; break
        room = caps.items - len(items)
        if room <= 0:
            stopped = 'items'; break
        page = fetch(position, room)
        pages += 1
        if page.total is not None:
            total = page.total
        taken, over = 0, False
        for item in page.items:
            if len(items) >= caps.items:
                over, stopped = True, 'items'; break
            cost = size(item)
            if used + cost > caps.bytes and items:
                over, stopped = True, 'bytes'; break
            items.append(item); used += cost; taken += 1
        if over:
            # Some of this page was left out. Offset paging can resume exactly; cursor paging resumes at this page again (the caller is told the result is partial either way).
            position = position + taken if style == 'offset' else position
            return PageResult(items, False, len(items), total, _handle(style, position), stopped)
        if style == 'offset':
            position = position + len(page.items)
            more = page.next is not None and bool(page.items) and (total is None or position < total)
        else:
            position = page.next
            more = page.next is not None
        if not more:
            return PageResult(items, True, len(items), total if total is not None else len(items), None, None)
    return PageResult(items, False, len(items), total, _handle(style, position), stopped)


# -- records and version tokens (#25) -----------------------------------------------------------------------------------------------------------------------
def record(kind, rid, *, container=None, version=None, title='', data=None, updated_epoch=None) -> dict:
    """The one shape of a record read through a connector. `container` is (resource kind, resource id): what a grant is checked against. `version` is the provider's version
    token (ETag, revision, sequence number, or its updated time as a last resort), kept so a later write can say what it was based on."""
    return {'kind': str(kind), 'id': str(rid), 'container': list(container) if container else None, 'version': None if version is None else str(version),
            'title': str(title)[:300], 'data': data if isinstance(data, dict) else {}, 'updated_epoch': updated_epoch}


def payload_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


# -- freshness (#24) ----------------------------------------------------------------------------------------------------------------------------------------
class Freshness:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def read(self, account, connection, kind, rid, *, count=None, complete=False, coverage=None):
        now = int(self.clock())
        with self.store.connect() as con:
            con.execute('''INSERT INTO connector_freshness(account_id,connection_id,resource_kind,resource_id,last_read_epoch,last_full_sync_epoch,item_count,coverage_json)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(account_id,connection_id,resource_kind,resource_id) DO UPDATE SET last_read_epoch=excluded.last_read_epoch,
                last_full_sync_epoch=coalesce(excluded.last_full_sync_epoch,last_full_sync_epoch),item_count=coalesce(excluded.item_count,item_count),
                coverage_json=coalesce(excluded.coverage_json,coverage_json)''',
                        (account, connection, kind, rid, now, now if complete else None, count, json.dumps(coverage) if coverage else None))
            con.execute('UPDATE connector_connections SET last_used_epoch=? WHERE account_id=? AND id=?', (now, account, connection))

    def error(self, account, connection, kind, rid, fault_kind):
        now = int(self.clock())
        with self.store.connect() as con:
            con.execute('''INSERT INTO connector_freshness(account_id,connection_id,resource_kind,resource_id,last_error,last_error_epoch) VALUES (?,?,?,?,?,?)
                ON CONFLICT(account_id,connection_id,resource_kind,resource_id) DO UPDATE SET last_error=excluded.last_error,last_error_epoch=excluded.last_error_epoch''',
                        (account, connection, kind, rid, fault_kind, now))

    def listing(self, con, account, connection, declaration: Declaration | None = None) -> list[dict]:
        """Per resource: when it was last read and read completely, how much, the last error, and whether it is older than its kind's freshness limit ("stale": still used, but flagged)."""
        now, out = int(self.clock()), []
        limits = declaration.freshness_seconds if declaration else {}
        for r in con.execute('SELECT * FROM connector_freshness WHERE account_id=? AND connection_id=? ORDER BY resource_kind,resource_id', (account, connection)):
            limit = limits.get(r['resource_kind'], limits.get('*'))
            out.append({'resource_kind': r['resource_kind'], 'resource_id': r['resource_id'], 'last_read_epoch': r['last_read_epoch'], 'last_full_sync_epoch': r['last_full_sync_epoch'],
                        'item_count': r['item_count'], 'coverage': json.loads(r['coverage_json']) if r['coverage_json'] else None, 'last_error': r['last_error'],
                        'last_error_epoch': r['last_error_epoch'], 'freshness_limit_seconds': limit,
                        'stale': bool(limit and r['last_read_epoch'] and now - r['last_read_epoch'] > limit)})
        return out

    def as_of(self, account, connection, kind, rid) -> dict | None:
        with self.store.connect() as con:
            r = con.execute('SELECT last_read_epoch,last_full_sync_epoch FROM connector_freshness WHERE account_id=? AND connection_id=? AND resource_kind=? AND resource_id=?',
                            (account, connection, kind, rid)).fetchone()
        return {'as_of_epoch': r['last_read_epoch'], 'complete_as_of_epoch': r['last_full_sync_epoch']} if r else None


# -- the one client -----------------------------------------------------------------------------------------------------------------------------------------
class ConnectorClient:
    """Every read and write to an outside system goes through here. `connectors` is connectors.ConnectorService (connections, grants, custody); `registry` is the Registry."""

    def __init__(self, store, connectors, registry: Registry, *, clock=time.time, limiter: RouteLimiter | None = None, sleep=time.sleep, max_wait=20.0):
        self.store, self.connectors, self.registry, self.clock = store, connectors, registry, clock
        self.limiter = limiter or RouteLimiter(cap=max_wait)
        self.sleep, self.max_wait = sleep, max_wait
        self.freshness = Freshness(store, clock)

    # -- the gate every call passes ---------------------------------------------------------------------------------------------------------
    def _open(self, principal, connection_id, action):
        """-> (connection row, declaration, adapter, credential). Read from the database NOW: a connection removed a second ago is refused here."""
        return self._gate(principal.account_id, connection_id, principal.actor_id, action)

    def open(self, principal, connection_id, action):
        """The gate, for a caller in this package that makes its own provider call through `call` (the dashboard fetching a message's body)."""
        return self._open(principal, connection_id, action)

    def open_for_sync(self, account_id, connection_id):
        """The background sync's gate (#D2). No person is asking, so there is no role to check; everything else applies as for any call: the connection's state right now,
        the organization's policy, the registry and custody. -> (connection row, declaration, adapter, credential)."""
        return self._gate(str(account_id), connection_id, None, None)

    def call(self, account_id, declaration, fn, *, where=None):
        """One provider call for a caller that already passed a gate: the same rate limit and the same six fault kinds as every other call."""
        return self._call(account_id, declaration, fn, where=where)

    def _gate(self, account_id, connection_id, actor_id, action):
        with self.store.connect() as con:
            if actor_id is not None:
                if permissions.member_role(con, account_id, actor_id) is None:
                    raise ConnectorFault('not_found')
                if not permissions.may(con, account_id, actor_id, action):
                    raise ConnectorFault('refused')
            row = con.execute('SELECT * FROM connector_connections WHERE account_id=? AND id=?', (account_id, str(connection_id))).fetchone()
            if row is None:
                raise ConnectorFault('not_found')
            if row['state'] == 'revoked':
                raise ConnectorFault('refused')
            if row['state'] != 'connected':
                raise ConnectorFault('needs_customer')
            if not organizations.connector_allowed(con, account_id, row['service']):
                raise ConnectorFault('refused')
        declaration = self.registry.declaration(row['service'])
        adapter = self.registry.adapter(row['service'])
        if declaration is None or adapter is None:
            raise ConnectorFault('refused')
        credential = None
        if row['secret_ref']:
            try:
                credential = json.loads(self.connectors.custody.get(account_id, row['secret_ref']))
            except Exception:
                raise ConnectorFault('needs_customer') from None
        elif row['mcp_connection_id']:
            credential = {'mcp_connection_id': row['mcp_connection_id'], 'account_id': account_id}
        return row, declaration, adapter, credential

    def _may_write(self, account, row, declaration, kind, container) -> bool:
        """May this change reach `container`? A mail or calendar provider of the dashboard (roadmap Phase 6) derives it: the customer chose to let Lumina see it (the read
        grant), the connection holds the provider permission behind this kind of change (asked for on first use), and, for a calendar, the provider lets this account change
        it (a subscribed or shared calendar it may only read gets no write). Every other connector needs a write grant on the resource."""
        caps = getattr(declaration, 'hub', None)
        if caps is None or not (getattr(caps, 'mail', False) or getattr(caps, 'calendar', False)):
            return self._granted(account, row['id'], container, 'write')
        try:
            scopes = json.loads(row['granted_scopes'] or '[]')
        except ValueError:
            scopes = []
        if not kind.capability or not caps.effective(scopes).get(kind.capability):
            return False
        if kind.policy_kind != 'send' and not self._granted(account, row['id'], container, 'read'):   # sending needs the send permission, not the reading grant
            return False
        if container[0] == 'calendar':
            with self.store.connect() as con:
                found = con.execute('SELECT access FROM hub_calendars WHERE account_id=? AND connection_id=? AND id=?', (account, row['id'], str(container[1]))).fetchone()
            return found is not None and found['access'] in ('owner', 'write')
        return True

    def _send_limits(self, account, payload, *, including_this):
        """No bulk sending (#66): a message goes to at most so many people, an account sends at most so many messages an hour (mail_limits). -> raises 'refused'."""
        from . import mail_limits
        people = len(list(payload.get('to') or []) + list(payload.get('cc') or []) + list(payload.get('bcc') or []))
        with self.store.connect() as con:
            reason = mail_limits.refusal(con, account, people, including_this=including_this, clock=self.clock)
        if reason:
            raise ConnectorFault('refused')

    def _granted(self, account, connection_id, container, access='read') -> bool:
        if not container:
            return False
        if list(container) == ['mail', 'all']:
            # Mail as a whole (organizing conversations, a sent message): the customer let Lumina read some of this account's mail. Which conversations is checked by
            # the dashboard against its copy, which holds only what they chose.
            with self.store.connect() as con:
                return con.execute("SELECT 1 FROM connector_grants WHERE account_id=? AND connection_id=? AND resource_kind IN ('mailbox','label') LIMIT 1",
                                   (account, connection_id)).fetchone() is not None
        with self.store.connect() as con:
            return self.connectors.granted(con, account, connection_id, container[0], container[1], access)

    def _call(self, account, declaration, fn, *, where=None):
        """Run one provider call under the provider's rate limit, turning whatever goes wrong into one fault kind. A busy provider is waited for once, briefly; a longer wait is
        the caller's (`retry_later` with the time)."""
        route = 'connector:' + declaration.provider
        wait = self.limiter.wait_time(account, route)
        if wait > self.max_wait:
            raise ConnectorFault('retry_later', int(self.clock() + wait))
        if wait > 0:
            self.sleep(wait)
        try:
            return fn()
        except (Unanswered, Signal):
            raise
        except ConnectorFault as fault:
            self._note_error(account, where, fault)
            raise
        except ProviderError as error:
            fault = declaration.fault(error)
            # Why a call failed, for whoever runs the server: the provider's status and its own short error code (never its text, never what was asked).
            log.warning('connector_fault provider=%s kind=%s status=%s code=%s', declaration.provider, fault.kind, error.status, error.code)
            if fault.kind == 'retry_later':
                self.limiter.note(account, route, 429, {'Retry-After': error.retry_after} if error.retry_after is not None else None)
            if fault.kind == 'needs_customer' and where:
                self.connectors.needs_customer(account, where[0], 'reconnect')
            self._note_error(account, where, fault)
            raise fault from None
        except Exception as error:
            # An adapter that broke (not the provider saying no): its type, so it can be found; its text could carry what was read.
            log.warning('connector_error provider=%s type=%s', declaration.provider, type(error).__name__)
            fault = ConnectorFault('retry_later')
            self._note_error(account, where, fault)
            raise fault from None

    def _note_error(self, account, where, fault):
        if where and len(where) == 3:
            try:
                self.freshness.error(account, where[0], where[1], where[2], fault.kind)
            except Exception:
                pass

    # -- reading ----------------------------------------------------------------------------------------------------------------------------
    def describe(self, principal, connection_id) -> dict:
        row, declaration, _adapter, _credential = self._open(principal, connection_id, 'connection.read')
        return {'provider': declaration.provider, 'label': declaration.label, 'resource_kinds': list(declaration.resource_kinds), 'record_kinds': list(declaration.record_kinds),
                'read_operations': list(declaration.read_operations), 'write_kinds': [{'name': w.name, 'label': w.label, 'can_undo': bool(w.undo), 'irreversible_reason': w.irreversible_reason}
                                                                                    for w in declaration.write_kinds]}

    def resources(self, principal, connection_id) -> list[dict]:
        """What the provider offers to choose from (calendars, folders, labels, repositories, projects): the picker's list. Needs no grant: choosing comes before granting."""
        row, declaration, adapter, credential = self._open(principal, connection_id, 'connection.create')
        found = self._call(principal.account_id, declaration, lambda: adapter.resources(credential))
        return [{'kind': str(r['kind']), 'id': str(r['id']), 'name': str(r.get('name') or r['id'])[:200]} for r in found if r.get('kind') in declaration.resource_kinds][:500]

    def list(self, principal, connection_id, resource_kind, resource_id, *, continuation=None, record_kind=None) -> tuple[list, PageResult]:
        row, declaration, adapter, credential = self._open(principal, connection_id, 'connection.use')
        container = (str(resource_kind), str(resource_id))
        if 'list' not in declaration.read_operations or container[0] not in declaration.resource_kinds or not self._granted(principal.account_id, row['id'], container):
            raise ConnectorFault('not_found')                # one answer for "does not exist" and "not granted": a connection cannot learn what it may not reach
        where = (row['id'], *container)
        result = paginate(lambda position, limit: self._call(principal.account_id, declaration, lambda: adapter.list(credential, container, position, limit, record_kind), where=where),
                          style=declaration.paging, caps=declaration.caps, continuation=continuation)
        result.items = [r for r in result.items if r.get('container') and tuple(r['container']) == container]       # filtered again on the way back
        result.count = len(result.items)
        self.freshness.read(principal.account_id, row['id'], *container, count=result.count if result.complete and continuation is None else None, complete=result.complete and continuation is None)
        return result.items, result

    def read(self, principal, connection_id, record_kind, record_id) -> dict:
        row, declaration, adapter, credential = self._open(principal, connection_id, 'connection.use')
        if 'read' not in declaration.read_operations:
            raise ConnectorFault('not_found')
        found = self._call(principal.account_id, declaration, lambda: adapter.read(credential, str(record_kind), str(record_id)))
        if not found or not self._granted(principal.account_id, row['id'], found.get('container')):
            raise ConnectorFault('not_found')
        self.freshness.read(principal.account_id, row['id'], *found['container'])
        return found

    def search(self, principal, connection_id, query, *, continuation=None) -> tuple[list, PageResult]:
        row, declaration, adapter, credential = self._open(principal, connection_id, 'connection.use')
        if 'search' not in declaration.read_operations or not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ConnectorFault('invalid')
        with self.store.connect() as con:
            scope = self.connectors.scope(con, principal.account_id, row['id'])
        if not scope:
            return [], PageResult([], True, 0, 0, None, None)        # nothing was chosen, so there is nothing it may search
        everything = {kind for kind, rid, _access in scope if rid == '*'}
        containers = None if set(declaration.resource_kinds) <= everything else [[kind, rid] for kind, rid, _access in scope]
        result = paginate(lambda position, limit: self._call(principal.account_id, declaration, lambda: adapter.search(credential, query.strip(), containers, position, limit)),
                          style=declaration.paging, caps=declaration.caps, continuation=continuation)
        result.items = [r for r in result.items if self._granted(principal.account_id, row['id'], r.get('container'))]   # the request was narrowed before it left; this is the check on the way back
        result.count = len(result.items)
        for container in {tuple(r['container']) for r in result.items}:
            self.freshness.read(principal.account_id, row['id'], *container)
        return result.items, result

    def as_of(self, principal, connection_id, items) -> list[dict]:
        """"As of" for each source an answer used: one line per (connection, resource) among `items`."""
        row, declaration, _adapter, _credential = self._open(principal, connection_id, 'connection.read')
        with self.store.connect() as con:
            every = {(f['resource_kind'], f['resource_id']): f for f in self.freshness.listing(con, principal.account_id, row['id'], declaration)}
        return [every[c] for c in sorted({tuple(i['container']) for i in items if i.get('container')}) if c in every]

    def prepare(self, principal, connection_id, kind_name, payload) -> dict:
        """Everything a proposed change needs, checked before anything is stored: the write kind exists, the payload is well formed for it, the resource it touches is granted
        for writing, and (when it changes an existing record) the record as it is now, with its version. Nothing is sent."""
        row, declaration, adapter, credential = self._open(principal, connection_id, 'action.propose')
        kind = declaration.write_kind(kind_name)
        if kind is None or not isinstance(payload, dict):
            raise ConnectorFault('invalid')
        try:
            adapter.check(kind_name, payload)
        except ValueError:
            raise ConnectorFault('invalid') from None
        container = adapter.container_of(credential, kind_name, payload)
        if not container:
            raise ConnectorFault('not_found')
        if not self._may_write(principal.account_id, row, declaration, kind, container):
            raise ConnectorFault('refused')
        if kind.policy_kind == 'send':
            self._send_limits(principal.account_id, payload, including_this=False)
        target, before = adapter.target_of(kind_name, payload), None
        if target:
            before = self._call(principal.account_id, declaration, lambda: adapter.read(credential, *target))
        return {'declaration': declaration, 'adapter': adapter, 'kind': kind, 'container': container, 'target': target, 'before': before, 'provider': row['service']}

    # -- writing (only the action executor calls these: an approved action, never a model's request) -----------------------------------------------
    def write(self, principal, connection_id, kind_name, payload, *, idempotency_key, base_version=None) -> dict:
        """Send one write. Raises ConnectorFault, or Unanswered when it was sent and no answer came back. -> {'receipt', 'record'}.

        Concurrent edit detection (#25): a write that changes an existing record carries the version it was based on. Where the provider takes a precondition it is sent with
        the write; where it does not, the record is re-read immediately before writing and compared. A mismatch is `conflict`: nothing is written."""
        row, declaration, adapter, credential = self._open(principal, connection_id, 'action.execute')
        kind = declaration.write_kind(kind_name)
        if kind is None:
            raise ConnectorFault('invalid')
        container = adapter.container_of(credential, kind_name, payload)
        if not container or not self._may_write(principal.account_id, row, declaration, kind, container):
            raise ConnectorFault('refused')
        if kind.needs_version:
            if base_version is None:
                raise ConnectorFault('conflict')            # it changes a record nobody read first: there is nothing to compare with
            if not declaration.preconditions:
                target = adapter.target_of(kind_name, payload)
                current = self._call(principal.account_id, declaration, lambda: adapter.read(credential, *target)) if target else None
                if current is None or str(current.get('version')) != str(base_version):
                    raise ConnectorFault('conflict')
        if kind.policy_kind == 'send':
            self._send_limits(principal.account_id, payload, including_this=True)
        result = self._call(principal.account_id, declaration, lambda: adapter.write(credential, kind_name, payload, idempotency_key=idempotency_key if declaration.idempotency_keys else None,
                                                                                     precondition=base_version if declaration.preconditions and kind.needs_version else None), where=(row['id'], *container))
        with self.store.connect() as con:
            con.execute('UPDATE connector_connections SET last_used_epoch=? WHERE account_id=? AND id=?', (int(self.clock()), principal.account_id, row['id']))
        return result

    def find_effect(self, principal, connection_id, kind_name, payload, *, idempotency_key):
        """Did a write whose answer never came happen? Read back, by its idempotency key where the provider keeps one, else by looking for its effect. -> the record, or None."""
        row, declaration, adapter, credential = self._open(principal, connection_id, 'action.execute')
        return self._call(principal.account_id, declaration, lambda: adapter.find_effect(credential, kind_name, payload, idempotency_key))

    def current(self, principal, connection_id, record_kind, record_id):
        """The record as it is now, for a preview's "before", a conflict's "current version" and verification after a write. None when it does not exist."""
        row, declaration, adapter, credential = self._open(principal, connection_id, 'action.propose')
        try:
            found = self._call(principal.account_id, declaration, lambda: adapter.read(credential, str(record_kind), str(record_id)))
        except ConnectorFault as fault:
            if fault.kind == 'not_found':
                return None
            raise
        return found if found and self._granted(principal.account_id, row['id'], found.get('container')) else None

    def declaration_for(self, principal, connection_id) -> Declaration:
        return self._open(principal, connection_id, 'connection.read')[1]


class McpAdapter:
    """An MCP wrapper: a connector whose provider is reached through its official remote MCP server (mcp_connections), with that server's tools mapped onto the contract's
    operations. `tools` maps an operation to a tool name and a function that turns the tool's result into records:

        {'resources': (tool, to_resources), 'list': (tool, to_page), 'read': (tool, to_record), 'search': (tool, to_page),
         'write': {write kind: (tool, to_result)}, 'container_of': fn(kind, payload), 'target_of': fn(kind, payload)}

    `call(account, connection, tool, arguments) -> dict` is the MCP service's own call (it owns the server's credentials, its network guards and its timeouts). An operation
    the server has no tool for is simply not offered: the declaration's read_operations and write_kinds say what exists."""

    def __init__(self, call, tools: dict):
        self.call, self.tools = call, tools

    def _run(self, credential, operation, arguments, kind=None):
        entry = self.tools.get('write', {}).get(kind) if operation == 'write' else self.tools.get(operation)
        if not entry:
            raise ProviderError(404, 'unsupported')
        tool, convert = entry
        try:
            return convert(self.call(credential['account_id'], credential['mcp_connection_id'], tool, arguments))
        except (ProviderError, Unanswered, ConnectorFault):
            raise
        except TimeoutError:
            raise Unanswered() from None
        except Exception:
            raise ProviderError(0) from None

    def resources(self, credential):
        return self._run(credential, 'resources', {})

    def list(self, credential, container, position, limit, record_kind=None):
        return self._run(credential, 'list', {'container': list(container), 'cursor': position, 'limit': limit, 'kind': record_kind})

    def read(self, credential, record_kind, record_id):
        return self._run(credential, 'read', {'kind': record_kind, 'id': record_id})

    def search(self, credential, query, containers, position, limit):
        return self._run(credential, 'search', {'query': query, 'containers': containers, 'cursor': position, 'limit': limit})

    def write(self, credential, kind, payload, *, idempotency_key=None, precondition=None):
        return self._run(credential, 'write', {**payload, **({'idempotency_key': idempotency_key} if idempotency_key else {}), **({'if_version': precondition} if precondition else {})}, kind)

    def find_effect(self, credential, kind, payload, idempotency_key):
        entry = self.tools.get('find_effect')
        return entry(self, credential, kind, payload, idempotency_key) if entry else None

    def container_of(self, credential, kind, payload):
        return self.tools['container_of'](kind, payload)

    def target_of(self, kind, payload):
        return self.tools['target_of'](kind, payload)
