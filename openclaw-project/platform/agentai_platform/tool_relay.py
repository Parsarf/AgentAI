"""The door from a customer cell to the tools Lumina serves natively (sandboxed browser and task progress). Runs as the app user, bound to the cells' bridge address.

The cell's OpenClaw connects to this as an MCP server (streamable HTTP, JSON replies) and lists and calls its tools like any native tool. Three rules keep it a door and
not a hole:

* The caller proves which cell it is with the credential the cell was provisioned with (its own model key). The root bridge checks it (``cell.identify``); this process
  never holds a secret of its own, and a credential that matches no running cell gets nothing.
* Only the registered browser and progress tools exist, and a call is only served for the calling account's own running request (browse/adapter.py): nothing a cell sends can name another account.
* One tool call at a time per account, bounded request size, and a call whose connection drops is stopped: Stop and a stopped run reach the browser job.

Every call that did not do what was asked leaves its reason here (reliability plan, Part 3): the tool says why with a registered fault (faults.py), and this relay records
it with the account, the request and the call, because every call passes here whatever way it reached the runtime. The assistant is told `isError` only for a fault that is
an error; an expected stop (approval needed, a limit, stopped with the task) is a normal reply that says what happens next.

Nothing about content is logged; counts and states only.
"""
from __future__ import annotations
import hmac
import json
import logging
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import faults, request_states
from .adapters import CapabilityUnavailable
from .browse.adapter import STEP, STEP_NAME, TOOL, TOOL_NAME, BrowserTool
from .model_keys import RELAY_PREFIX, SELECTION_PREFIX, SELECTION_MODEL
from .task_progress import TOOL as PROGRESS_TOOL, TOOL_NAME as PROGRESS_NAME

PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
MAX_BODY = 64 * 1024
IDENTIFY_TTL = 60
FAIL_LIMIT = 20                     # refused credentials per source address per minute before it is told to slow down
TOOLS = {TOOL_NAME: TOOL, STEP_NAME: STEP}
log = logging.getLogger('agentai.tools')
ORIGIN_DOWN = frozenset({'origin_service_unavailable', 'proof_unavailable'})       # Lumina could not check the proof at all: ours to fix, not a call out of place
ORIGIN_STATUSES = frozenset({'verified', 'invalid_arguments', 'proof_missing', 'proof_invalid', 'proof_expired', 'argument_mismatch', 'proof_missing_or_consumed', 'proof_unavailable'})


class Identity:
    """credential -> account, asked of the root bridge and remembered briefly. A credential that stops matching (key rotated, cell removed) stops working within the TTL."""

    def __init__(self, identify, clock=time.monotonic):
        self.identify, self.clock = identify, clock
        self._seen, self._fails, self._lock = {}, {}, threading.Lock()

    def account(self, credential, source=''):
        now = self.clock()
        with self._lock:
            hit = self._seen.get(credential)
            if hit and now - hit[1] < IDENTIFY_TTL:
                return hit[0]
            fails = [t for t in self._fails.get(source, []) if now - t < 60]
            if len(fails) >= FAIL_LIMIT:
                raise PermissionError('slow down')
        try:
            account = self.identify(credential)
        except CapabilityUnavailable:
            account = None
        with self._lock:
            if account:
                self._seen[credential] = (account, now)
            else:
                self._fails[source] = [t for t in self._fails.get(source, []) if now - t < 60] + [now]
        return account


NO_ACTION = 'This tool is not available.'


class ToolPermit:
    """May this tool run for this task? Two questions, both read from the database at the moment of the call: does the person the task belongs to hold a role that includes
    the tool's action (permissions.TOOL_ACTIONS), and does their organization allow this kind of tool (organizations.tool_allowed). A tool no row names is refused: a new tool
    must name its action (a test checks every registered tool does)."""

    def __init__(self, store):
        self.store = store

    def listed(self, account, name):
        from . import organizations
        try:
            with self.store.connect() as con:
                return organizations.tool_allowed(con, account, name)
        except Exception:
            return True                                             # listing is a convenience; the call itself is checked below

    def refusal(self, account, request_id, name):
        from . import organizations, permissions
        action = permissions.tool_action(name)
        if action is None:
            return NO_ACTION                                # a tool nobody gave an action: a mistake in Lumina, which the relay records as one
        with self.store.connect() as con:
            if not organizations.tool_allowed(con, account, name):
                return 'Your organization does not allow this tool. Nothing was done. Tell the customer, and carry on without it if you can.'
            if request_id is not None:
                row = con.execute('SELECT actor_id FROM customer_requests WHERE account_id=? AND id=?', (account, request_id)).fetchone()
                if not row or not permissions.may(con, account, row['actor_id'], action):
                    return 'The person this task belongs to is not allowed to do this. Nothing was done. Tell them, and carry on without it if you can.'
        return None


class Relay:
    """The MCP protocol and the tools; no sockets (the handler below owns those)."""

    def __init__(self, tool: BrowserTool, progress=None, *, origin=None, remote=None, memory=None, location=None, files=None, show=None, connectors=None, permit=None, hub=None,
                 knowledge=None):
        self.tool, self.progress, self.origin, self.remote = tool, progress, origin, remote
        self.location = location
        self.memory = memory                                        # longterm_memory.MemoryTools or None; its two tools exist for an account only while the owner's switch is on
        self.files = files                                          # file_tools.FileTools or None; hands the customer a file the assistant wrote, converted on request
        self.show = show                                            # show_tool.ShowTools or None; shows a table, chart, cards or a form under the reply
        self.connectors = connectors                                # connector_tools.ConnectorTools or None; reads through connected services and proposes changes for approval
        self.hub = hub                                              # hub_tools.HubTools or None; reads the customer's connected mail and calendars (read only)
        self.knowledge = knowledge                                  # knowledge_tools.KnowledgeTools or None; the customer's documents, commitments, drafts and meeting briefs
        self.permit = permit                                        # ToolPermit or None: the role and organization-policy check asked before a tool runs (roadmap #12, #15)
        self.tools = {**TOOLS, **({PROGRESS_NAME: PROGRESS_TOOL} if progress is not None else {})}
        if location is not None:
            from .location import NAME, TOOL as LOCATION_TOOL
            self.tools[NAME] = LOCATION_TOOL
        if remote is not None:
            from .mcp_connections.relay import GENERIC
            self.tools.update({spec['name']: spec for spec in GENERIC})
        # The runtime hook overwrites this optional transport field. It is
        # stripped before the browser/progress handler sees user arguments.
        import copy
        self.tools = copy.deepcopy(self.tools)
        for spec in self.tools.values():
            spec['inputSchema']['properties']['_lumina_origin'] = {'type': 'string', 'description': 'Runtime-generated ownership proof. Leave unset; the runtime supplies it.'}
        if self.progress is not None:
            self.tools[PROGRESS_NAME]['inputSchema']['anyOf'].insert(0, {'maxProperties': 1, 'required': ['_lumina_origin']})
        self._busy, self._guard = set(), threading.Lock()

    def handle(self, account, message, closed=lambda: False):
        """One JSON-RPC message -> (response dict or None for a notification)."""
        method, rid = message.get('method'), message.get('id')
        if rid is None:
            return None                                             # notifications/initialized and friends need no reply
        if method == 'initialize':
            asked = (message.get('params') or {}).get('protocolVersion')
            return self._ok(rid, {'protocolVersion': asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0], 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'lumina', 'version': '1'}})
        if method == 'ping':
            return self._ok(rid, {})
        if method == 'tools/list':
            specs = [t for n, t in self.tools.items() if not (self.remote is not None and self.remote.is_generic(n) and not self.remote.enabled(account))]
            if self.remote is not None and self.remote.enabled(account):
                import copy
                for spec in self.remote.specs(account):
                    spec = copy.deepcopy(spec)
                    spec['inputSchema'].setdefault('properties', {})['_lumina_origin'] = {'type': 'string', 'description': 'Runtime ownership proof. Leave unset.'}
                    specs.append(spec)
            for extra in (self.memory, self.files, self.show, self.connectors, self.hub, self.knowledge):
                if extra is not None and extra.enabled(account):
                    for spec in (extra.specs_for(account) if hasattr(extra, 'specs_for') else extra.specs()):
                        spec['inputSchema']['properties']['_lumina_origin'] = {'type': 'string', 'description': 'Runtime-generated ownership proof. Leave unset; the runtime supplies it.'}
                        specs.append(spec)
            if self.permit is not None:
                specs = [s for s in specs if self.permit.listed(account, s['name'])]      # a tool the organization does not allow is not offered at all
            return self._ok(rid, {'tools': specs})
        if method == 'tools/call':
            params = message.get('params') or {}
            name = params.get('name')
            remote_on = self.remote is not None and self.remote.enabled(account)
            remote_call = remote_on and self.remote.accepts(name)
            memory_call = self.memory is not None and name in self.memory.names and self.memory.enabled(account)
            files_call = self.files is not None and name in self.files.names and self.files.enabled(account)
            show_call = self.show is not None and name in self.show.names and self.show.enabled(account)
            connector_call = self.connectors is not None and name in self.connectors.names and self.connectors.enabled(account)
            hub_call = self.hub is not None and name in self.hub.names and self.hub.enabled(account)
            knowledge_call = self.knowledge is not None and name in self.knowledge.names and self.knowledge.enabled(account)
            if not isinstance(params.get('arguments') or {}, dict):
                return self._error(rid, -32602, 'invalid arguments')
            if (self.remote is not None and self.remote.is_generic(name) and not remote_on) or (name not in self.tools and not remote_call and not memory_call and not files_call and not show_call and not connector_call and not hub_call and not knowledge_call):
                return self._error(rid, -32602, 'unknown tool')
            location_call = self.location is not None and name == 'lumina_request_location'
            busy_key = (account, 'location' if location_call else 'remote' if remote_call else 'memory' if memory_call else 'files' if files_call else 'show' if show_call else 'connectors' if connector_call else 'hub' if hub_call else 'knowledge' if knowledge_call else 'progress' if name == PROGRESS_NAME else 'browser')
            with self._guard:
                taken = busy_key in self._busy
                if not taken:
                    self._busy.add(busy_key)
            if taken:                                               # answered outside the guard: recording it must not hold up the other calls
                return self._ok(rid, self._answer(account, None, name, None, 'Another tool call is still running for this task. Wait for it to finish, then send this call again.',
                                                  faults.Fault('tool.busy')))
            try:
                handler = self.location if location_call else self.remote if remote_call else self.memory if memory_call else self.files if files_call else self.show if show_call else self.connectors if connector_call else self.hub if hub_call else self.knowledge if knowledge_call else self.progress if name == PROGRESS_NAME else self.tool
                arguments = params.get('arguments') or {}
                bound, call_id, origin = {}, None, None
                if self.origin is not None:
                    try:
                        origin = self.origin(account, name, arguments)
                        status = 'unverified_origin'
                        if isinstance(origin, dict) and 'origin' in origin:
                            status = origin.get('status') if origin.get('status') in ORIGIN_STATUSES else status
                            origin = origin['origin']
                        request_id = self._owner(account, origin)
                        if origin and not request_id:
                            status = 'admission_mismatch'
                    except (CapabilityUnavailable, ValueError, TypeError):
                        request_id, status = None, 'origin_service_unavailable'
                    call_id = origin.get('call_id') if isinstance(origin, dict) else None
                    if not request_id:
                        log.warning('tool_ownership_refused tool=%s reason=%s', name, status)
                        return self._ok(rid, self._answer(account, None, name, call_id, 'This tool call does not belong to an admitted live task. Nothing was started or changed. Do not retry this call in another task.',
                                                          faults.Fault('tool.origin_unavailable' if status in ORIGIN_DOWN else 'tool.not_admitted', {'code': status})))
                    bound['request_id'] = request_id
                arguments = {k: v for k, v in arguments.items() if k != '_lumina_origin'}
                if self.permit is not None:
                    refusal = self.permit.refusal(account, bound.get('request_id'), name)
                    if refusal:
                        log.warning('tool_not_permitted tool=%s', name)
                        return self._ok(rid, self._answer(account, bound.get('request_id'), name, call_id, refusal,
                                                          faults.Fault('tool.failed' if refusal == NO_ACTION else 'tool.not_permitted')))
                if remote_call and self.origin is not None:
                    # Continue checking admission while a remote operation is in flight.
                    def remote_closed():
                        return closed() or self._owner(account, origin) != request_id
                    caller_closed = remote_closed
                else:
                    caller_closed = closed
                result = handler.call(account, arguments, caller_closed, name=name, **bound)
            finally:
                with self._guard:
                    self._busy.discard(busy_key)
            if remote_call:                                         # a connected service's tool answers in the protocol's own shape; why it did not work travels beside it
                problem = result.pop('_fault', None) or (faults.Fault('tool.remote_error') if result.get('isError') else None)
                return self._ok(rid, self._noted(account, bound.get('request_id'), name, call_id, result, problem))
            text, problem, *image = result
            return self._ok(rid, self._answer(account, bound.get('request_id'), name, call_id, text, problem, image[0] if image else None))
        return self._error(rid, -32601, 'method not found')

    def _answer(self, account, request_id, name, call_id, text, problem, image=None):
        return self._noted(account, request_id, name, call_id, self._result(text, False, image), problem)

    def _noted(self, account, request_id, name, call_id, result, problem):
        """The result as the assistant gets it, with the reason recorded when the call did not do what was asked. `problem` is what the tool put in the second place of its
        answer: False, a faults.Fault, or a bare True from a tool that does not say why yet (counted as `tool.failed`)."""
        fault = faults.of_tool_reply(problem, name, call_id)
        result['isError'] = faults.is_error(fault)
        if fault is not None:
            (log.info if fault.expected else log.error)('tool_fault tool=%s reason=%s request=%s', fault.detail.get('tool'), fault.reason, request_id or '-')
            store = getattr(self.tool, 'store', None)                   # the relay's one handle on the application database is the browser tool's
            if store is not None:
                faults.record(store, account, fault, request_id=request_id)
            # The same facts for a caller that is a program, not a reader (section 4b): what kind of failure, whether it may be tried again, what was changed.
            result['_meta'] = {**(result.get('_meta') or {}), 'lumina/fault': {'reason': fault.reason, 'kind': fault.kind, 'retry': fault.retry, 'effect': fault.what_changed}}
        return result

    def _owner(self, account, origin):
        if not isinstance(origin, dict) or not all(isinstance(origin.get(k), str) and origin[k] for k in ('session_key', 'run_id', 'call_id')):
            return None
        with self.tool.store.connect() as con:
            rows = con.execute(f"""SELECT DISTINCT r.id FROM customer_requests r
                JOIN conversations c ON c.account_id=r.account_id AND c.id=r.conversation_id
                JOIN chat_deliveries d ON d.account_id=r.account_id AND d.request_id=r.id
                JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND {request_states.live_run()}
                AND v.state='active' AND c.native_session_ref=? AND (d.native_run_id=? OR (d.native_run_id IS NULL AND d.idempotency_key=?))
                LIMIT 2""", (account, origin['session_key'], origin['run_id'], origin['run_id'])).fetchall()
        return rows[0]['id'] if len(rows) == 1 else None

    @staticmethod
    def _result(text, is_error, image=None):
        """The assistant's tool result: text, and the picture of the browser window when the browser handed it a page (a base64 JPEG, as an MCP image block)."""
        content = [{'type': 'text', 'text': text}]
        if isinstance(image, str) and image and len(image) <= 3_000_000:
            content.append({'type': 'image', 'data': image, 'mimeType': 'image/jpeg'})
        return {'content': content, 'isError': bool(is_error)}

    @staticmethod
    def _ok(rid, result):
        return {'jsonrpc': '2.0', 'id': rid, 'result': result}

    @staticmethod
    def _error(rid, code, message):
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}}


def make_handler(relay: Relay, identity: Identity, byok=None):
    """`byok` (model_keys.ModelRelay) adds /byok/v1: the assistant's model calls for a customer who uses their own key. Same caller check as the tools."""
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _send(self, status, body=None):
            data = json.dumps(body).encode() if body is not None else b''
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _closed(self):
            """Has the caller hung up? A readable socket that yields no bytes is a closed one."""
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b''
            except OSError:
                return True

        def _caller(self):
            """The account behind this request's bearer credential, or None after the refusal has been sent."""
            header = self.headers.get('Authorization', '')
            credential = header[7:].strip() if header.lower().startswith('bearer ') else ''
            try:
                account = identity.account(credential, self.client_address[0]) if len(credential) >= 8 else None
            except PermissionError:
                self._send(429, {'error': 'slow down'})
                return None
            if not account:
                self._send(401, {'error': 'unauthorized'})
            return account or None

        def _model_error(self, exc):
            from .model_keys import error_body
            self._send(exc.status, error_body(exc.message, exc.code))

        def do_GET(self):
            if byok is not None and self.path.split('?', 1)[0] in (RELAY_PREFIX + '/models', SELECTION_PREFIX + '/models'):
                account = self._caller()
                if account:
                    from .model_keys import RelayError
                    try:
                        self._send(200, {'object': 'list', 'data': [{'id': SELECTION_MODEL, 'object': 'model', 'owned_by': 'lumina'}]} if self.path.split('?', 1)[0] == SELECTION_PREFIX + '/models' else byok.models(account))
                    except RelayError as exc:
                        self._model_error(exc)
                return
            self._send(405, {'error': 'method not allowed'})          # no server-sent events: replies are plain JSON

        def do_DELETE(self):
            self._send(200, {})

        def _byok_chat(self):
            from .model_keys import MAX_REQUEST_BYTES, RelayError
            account = self._caller()
            if not account:
                return
            length = self.headers.get('Content-Length', '')
            if not length.isdecimal() or not 0 < int(length) <= MAX_REQUEST_BYTES:
                return self._send(413, {'error': 'bad length'})
            raw = self.rfile.read(int(length))
            try:
                # Both paths use the same admitted route. Old warm cells still call
                # /byok/v1 with a stale model name; that must not select an old key.
                up = byok.selected_chat(account, self.headers.get('Authorization', '')[7:].strip(), raw)
            except RelayError as exc:
                return self._model_error(exc)
            ctype = up.content_type if up.content_type.split(';')[0].strip().lower() in ('application/json', 'text/event-stream') else 'application/json'
            self.send_response(up.status)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')                                  # the reply may stream; its end is the end of the connection
            self.end_headers()
            self.close_connection = True
            try:
                for chunk in up.chunks():
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except OSError:
                pass                                                                  # the assistant hung up: stop reading from the customer's endpoint
            finally:
                up.close()

        def do_POST(self):
            path = self.path.split('?', 1)[0]
            if byok is not None and path in (RELAY_PREFIX + '/chat/completions', SELECTION_PREFIX + '/chat/completions'):
                return self._byok_chat()
            if path != '/mcp':
                return self._send(404, {'error': 'not found'})
            account = self._caller()
            if not account:
                return
            length = self.headers.get('Content-Length', '')
            if not length.isdecimal() or not 0 < int(length) <= MAX_BODY:
                return self._send(413, {'error': 'bad length'})
            try:
                message = json.loads(self.rfile.read(int(length)))
            except ValueError:
                return self._send(400, {'error': 'bad json'})
            if not isinstance(message, dict):
                return self._send(400, {'error': 'bad json'})
            reply = relay.handle(account, message, self._closed)
            if reply is None:
                return self._send(202)
            self._send(200, reply)
    return Handler


def serve(relay: Relay, identity: Identity, host: str, port: int, byok=None):
    server = ThreadingHTTPServer((host, port), make_handler(relay, identity, byok))
    server.daemon_threads = True
    return server
