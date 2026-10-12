"""Server-side Gateway session-control adapter for customer chat (Phase 6).

Recorded native contract (reconfirm against the installed runtime at
activation; an unprobed adapter is never a live capability):

- Chat execution uses ``chat.send``, ``chat.history`` and ``chat.abort``
  (plus ``chat.inject``, unused here) against one exact session key.
- ``chat.send`` acknowledgement reports admission separately from transcript
  persistence: ``status:"started"``/``runStarted:true`` alone does not
  establish a transcript row, and ``messageSeq`` is absent while the input is
  only in pending custody. Reconcile by submission identity against the
  canonical transcript, never by a predicted position.
- ``chat.history`` is display-normalized and cursor-paginated. An opaque
  ``deltaCursor`` passed back as ``cursor`` returns ``{kind:"delta"}`` catch-up
  (replay through the same reducer as live events) or ``{kind:"reset"}`` when
  the cursor is stale/crossed a reset; a reset requires a normal tail fetch.
- ``chat.abort`` takes the session key plus an optional ``runId``; supplying
  ``runId`` scopes cancellation to that run. Abort stops generation and does
  not undo external effects; a confirmed terminal/absent run is required
  before reporting cancellation to the customer.
- Sessions are created with ``sessions.create``; when the initial turn is
  rejected the result reports ``runStarted:false`` plus ``runError``.

Compatibility negotiation: the client probes before any customer effect and
fails closed on an unsupported protocol version or missing method support.
The binding (origin, credential reference, agent id) is resolved server-side
from host-owned configuration per deployment; no browser-supplied URL, token,
RPC name or session key is ever accepted.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import re
import uuid
from .adapters import CapabilityUnavailable, GatewayCapabilities

SUPPORTED_PROTOCOL_VERSION = 4   # installed 2026.9.6 negotiated protocol 4 in the 2026-10-12 live probe
CHAT_METHODS = ("chat.send", "chat.history", "chat.abort")

IDENTIFIER = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')


def session_ref(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('invalid session reference')
    return value


@dataclass(frozen=True)
class GatewayBinding:
    """Host-resolved connection facts. Never built from request data."""
    deployment_id: str
    agent_id: str
    origin: str
    credential_ref: str

    def __post_init__(self):
        from .lifecycle.coordinator import identifier
        identifier(self.deployment_id)
        identifier(self.agent_id)
        if not self.origin.startswith('https://') or not isinstance(self.credential_ref, str) or not self.credential_ref:
            raise ValueError('invalid gateway binding')


def negotiate(caps: GatewayCapabilities) -> GatewayCapabilities:
    """Fail closed: keep only probed capabilities on the supported protocol."""
    if caps.protocol_version != SUPPORTED_PROTOCOL_VERSION or not caps.live_probed:
        return replace(caps, send=False, history=False, events=False, abort=False)
    return caps


class HttpGateway:
    """Transport-backed client; inert until a live probe succeeds.

    ``transport`` receives one already-bound request object and returns the
    response object; concrete framing (WebSocket/RPC envelope) is supplied by
    the host activation path and must be reconfirmed against the installed
    Gateway before use.
    """

    def __init__(self, binding: GatewayBinding, transport, clock=None):
        self._binding = binding
        self._transport = transport
        self._caps: GatewayCapabilities | None = None

    def _call(self, method: str, params: dict):
        if method not in CHAT_METHODS and method != 'sessions.create':
            raise ValueError('unsupported rpc method')
        response = self._transport({'method': method, 'params': params, 'binding': self._binding})
        if not isinstance(response, dict) or 'error' in response:
            raise CapabilityUnavailable('gateway call unavailable')
        return response

    def capabilities(self) -> GatewayCapabilities:
        if self._caps is None:
            try:
                probe = self._call('chat.history', {'probe': True})
            except CapabilityUnavailable:
                self._caps = GatewayCapabilities('unverified', 0, False, False, False, False, False)
                return self._caps
            version = probe.get('protocolVersion')
            methods = probe.get('methods') or {}
            self._caps = negotiate(GatewayCapabilities(
                str(probe.get('runtimeVersion', 'unverified')),
                version if type(version) is int else 0,
                bool(methods.get('chat.send')), bool(methods.get('chat.history')),
                bool(methods.get('events')), bool(methods.get('chat.abort')), True))
        return self._caps

    def require(self, operation: str):
        caps = self.capabilities()
        if operation not in {'send', 'history', 'abort'}:
            raise ValueError('unsupported operation')
        if not getattr(caps, operation):
            raise CapabilityUnavailable('installed gateway does not support ' + operation)
        return caps

    def open_session(self, operation_id: str, label: str):
        self.require('send')
        result = self._call('sessions.create', {'operationId': operation_id, 'label': label})
        key = result.get('sessionKey')
        session_ref(key)
        return key, bool(result.get('runStarted')), result.get('runError')

    def send(self, session: str, operation_id: str, message: str):
        self.require('send')
        result = self._call('chat.send', {'sessionKey': session, 'operationId': operation_id, 'message': message})
        if result.get('status') not in ('started', 'in_flight') or result.get('runStarted') is False:
            raise CapabilityUnavailable('send admission not confirmed')
        seq = result.get('messageSeq')
        return {'run_id': result.get('runId'), 'message_seq': seq if type(seq) is int and seq > 0 else None,
                'native_message_id': result.get('messageId') if isinstance(result.get('messageId'), str) else None}

    def history(self, session: str, cursor: str | None):
        self.require('history')
        params = {'sessionKey': session}
        if cursor is not None:
            session_ref(cursor)
            params['cursor'] = cursor
        result = self._call('chat.history', params)
        kind = result.get('kind', 'tail')
        if kind not in {'tail', 'delta', 'reset'}:
            raise CapabilityUnavailable('unsupported history response')
        messages = result.get('messages') or []
        if not isinstance(messages, list):
            raise CapabilityUnavailable('unsupported history response')
        return {'kind': kind, 'messages': messages,
                'cursor': result.get('deltaCursor') if kind == 'delta' else None,
                'active_run': bool((result.get('sessionInfo') or {}).get('hasActiveRun'))}

    def abort(self, session: str, run_id: str | None):
        self.require('abort')
        params = {'sessionKey': session}
        if run_id is not None:
            session_ref(run_id)
            params['runId'] = run_id
        result = self._call('chat.abort', params)
        if result.get('aborted') is not True:
            raise CapabilityUnavailable('abort not confirmed')
        return {'run_id': result.get('runId')}


class SyntheticGateway:
    """Deterministic in-memory fixture for local contract flows only.

    Never installed in the worker entry point or any request path.
    """

    def __init__(self, *, protocol_version=SUPPORTED_PROTOCOL_VERSION, abort_supported=True,
                 fail_after_ack=False, timeout_after_write=False, history_reset=False, active_pages=0):
        self.protocol_version = protocol_version
        self.abort_supported = abort_supported
        self.fail_after_ack = fail_after_ack
        self.timeout_after_write = timeout_after_write
        self.history_reset = history_reset
        self.active_pages = active_pages
        self.sessions: dict[str, list[dict]] = {}
        self.open_pages: dict[str, int] = {}
        self.abort_requests: list[tuple[str, str | None]] = []
        self.calls: list[tuple] = []
        self.on_history = None

    def capabilities(self):
        methods = {'chat.send': True, 'chat.history': True, 'events': True, 'chat.abort': self.abort_supported}
        return negotiate(GatewayCapabilities('synthetic-2026.9.6', self.protocol_version,
                                             methods['chat.send'], methods['chat.history'],
                                             methods['events'], methods['chat.abort'], True))

    def require(self, operation: str):
        caps = self.capabilities()
        if operation not in {'send', 'history', 'abort'} or not getattr(caps, operation):
            raise CapabilityUnavailable('installed gateway does not support ' + operation)
        return caps

    def open_session(self, operation_id: str, label: str):
        self.require('send')
        key = 'synthetic-' + uuid.uuid4().hex[:16]
        self.sessions[key] = []
        return key, False, None

    def send(self, session: str, operation_id: str, message: str):
        self.require('send')
        self.calls.append(('send', session, operation_id))
        if session not in self.sessions:
            raise CapabilityUnavailable('unknown session')
        seq = len(self.sessions[session]) + 1
        customer_row = {'id': f'm{seq}', 'role': 'customer', 'content': message, 'seq': seq}
        self.sessions[session].append(customer_row)
        if self.timeout_after_write:
            # Write may have landed; the caller must reconcile, never resend.
            raise TimeoutError('native outcome unknown after write')
        run_id = 'run-' + uuid.uuid4().hex[:12]
        seq += 1
        self.sessions[session].append({'id': f'm{seq}', 'role': 'agent', 'content': f'ack {operation_id}', 'seq': seq})
        self.open_pages[session] = self.active_pages
        if self.fail_after_ack:
            # Acknowledged natively; the caller never saw the acknowledgement.
            raise RuntimeError('gateway lost after acknowledgement')
        return {'run_id': run_id, 'message_seq': seq - 1, 'native_message_id': customer_row['id']}

    def history(self, session: str, cursor: str | None):
        self.require('history')
        self.calls.append(('history', session, cursor))
        if self.on_history:
            self.on_history()
        rows = self.sessions.get(session)
        if rows is None:
            raise CapabilityUnavailable('unknown session')
        if self.history_reset and cursor is not None:
            return {'kind': 'reset', 'messages': [], 'cursor': None, 'active_run': False}
        after = int(cursor) if cursor else 0
        window = [row for row in rows if row['seq'] > after]
        active = self.open_pages.get(session, 0) > 0
        if cursor is None:
            self.open_pages[session] = max(0, self.open_pages.get(session, 0) - 1)
        return {'kind': 'tail', 'messages': window, 'cursor': None, 'active_run': active}

    def abort(self, session: str, run_id: str | None):
        self.require('abort')
        self.calls.append(('abort', session, run_id))
        self.abort_requests.append((session, run_id))
        return {'run_id': run_id}


class NativeGateway:
    """Gateway client over an injected ``rpc(method, params) -> dict`` callable.

    The callable is the bridge client (the app never holds a cell token or a
    docker handle). Shapes follow the live protocol-4 probe of 2026-10-12.
    Raises CapabilityUnavailable for any refusal or malformed reply.
    """
    METHODS = ('hello', 'sessions.create', 'chat.send', 'chat.history', 'chat.abort', 'usage.snapshot')

    def __init__(self, rpc):
        self._rpc = rpc
        self._caps = None

    def _call(self, method, params=None):
        if method not in self.METHODS:
            raise ValueError('unsupported rpc method')
        result = self._rpc(method, params or {})
        if not isinstance(result, dict) or 'error' in result:
            raise CapabilityUnavailable('gateway call unavailable')
        return result

    def capabilities(self):
        if self._caps is None:
            try:
                hello = self._call('hello')
            except (CapabilityUnavailable, OSError, TimeoutError):
                self._caps = GatewayCapabilities('unverified', 0, False, False, False, False, False)
                return self._caps
            version = hello.get('protocol')
            methods = set(hello.get('methods') or ())
            self._caps = negotiate(GatewayCapabilities(
                str(hello.get('runtimeVersion', 'unverified')), version if type(version) is int else 0,
                'chat.send' in methods, 'chat.history' in methods, True, 'chat.abort' in methods, True))
        return self._caps

    def require(self, operation):
        caps = self.capabilities()
        if operation not in {'send', 'history', 'abort'} or not getattr(caps, operation):
            raise CapabilityUnavailable('installed gateway does not support ' + operation)
        return caps

    def open_session(self, operation_id, label):
        self.require('send')
        result = self._call('sessions.create', {'label': label[:64]})
        return session_ref(result.get('key')), False, None

    def send(self, session, operation_id, message):
        self.require('send')
        result = self._call('chat.send', {'sessionKey': session_ref(session), 'message': message,
                                          'idempotencyKey': session_ref(operation_id)})
        if result.get('status') not in ('started', 'in_flight') or not isinstance(result.get('runId'), str):
            raise CapabilityUnavailable('send admission not confirmed')
        return {'run_id': result['runId'], 'message_seq': None, 'native_message_id': None}

    @staticmethod
    def _text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
        return ''

    def history(self, session, cursor):
        self.require('history')
        params = {'sessionKey': session_ref(session)}
        if cursor is not None:
            params['cursor'] = cursor
        result = self._call('chat.history', params)
        kind = result.get('kind', 'tail')
        if kind not in {'tail', 'delta', 'reset'}:
            raise CapabilityUnavailable('unsupported history response')
        rows = []
        for m in result.get('messages') or []:
            if not isinstance(m, dict):
                continue
            meta = m.get('__openclaw') or {}
            role = {'assistant': 'agent'}.get(m.get('role'))   # user rows are skipped: tail pages repeat every turn, so ids cannot be matched to one request
            native_id = meta.get('id')
            text = self._text(m.get('content'))
            if role and isinstance(native_id, str) and text:
                rows.append({'id': native_id, 'role': role, 'content': text, 'seq': meta.get('seq')})
        info = result.get('sessionInfo') or {}
        active = bool(info.get('hasActiveRun')) or bool(result.get('pendingInputs'))
        return {'kind': kind, 'messages': rows, 'cursor': None, 'active_run': active}

    def usage_snapshot(self):
        return int(self._call('usage.snapshot')['spend_microusd'])

    def abort(self, session, run_id):
        self.require('abort')
        result = self._call('chat.abort', {'sessionKey': session_ref(session)})
        if result.get('aborted') is not True and result.get('ok') is not True:
            raise CapabilityUnavailable('abort not confirmed')
        return {'run_id': run_id}
