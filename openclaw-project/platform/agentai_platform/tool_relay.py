"""The door from a customer cell to the tools Lumina serves natively (sandboxed browser and task progress). Runs as the app user, bound to the cells' bridge address.

The cell's OpenClaw connects to this as an MCP server (streamable HTTP, JSON replies) and lists and calls its tools like any native tool. Three rules keep it a door and
not a hole:

* The caller proves which cell it is with the credential the cell was provisioned with (its own model key). The root bridge checks it (``cell.identify``); this process
  never holds a secret of its own, and a credential that matches no running cell gets nothing.
* Only the registered browser and progress tools exist, and a call is only served for the calling account's own running request (browse/adapter.py): nothing a cell sends can name another account.
* One tool call at a time per account, bounded request size, and a call whose connection drops is stopped: Stop and a stopped run reach the browser job.

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

from .adapters import CapabilityUnavailable
from .browse.adapter import STEP, STEP_NAME, TOOL, TOOL_NAME, BrowserTool
from .model_keys import RELAY_PREFIX
from .task_progress import TOOL as PROGRESS_TOOL, TOOL_NAME as PROGRESS_NAME

PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
MAX_BODY = 64 * 1024
IDENTIFY_TTL = 60
FAIL_LIMIT = 20                     # refused credentials per source address per minute before it is told to slow down
TOOLS = {TOOL_NAME: TOOL, STEP_NAME: STEP}
log = logging.getLogger('agentai.tools')
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


class Relay:
    """The MCP protocol and the tools; no sockets (the handler below owns those)."""

    def __init__(self, tool: BrowserTool, progress=None, *, origin=None, remote=None):
        self.tool, self.progress, self.origin, self.remote = tool, progress, origin, remote
        self.tools = {**TOOLS, **({PROGRESS_NAME: PROGRESS_TOOL} if progress is not None else {})}
        if remote is not None:
            from .mcp_connections.relay import DISCOVER, CALL
            self.tools.update({DISCOVER['name']: DISCOVER, CALL['name']: CALL})
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
            specs = list(self.tools.values())
            if self.remote is not None:
                import copy
                for spec in self.remote.specs(account):
                    spec = copy.deepcopy(spec)
                    spec['inputSchema'].setdefault('properties', {})['_lumina_origin'] = {'type': 'string', 'description': 'Runtime ownership proof. Leave unset.'}
                    specs.append(spec)
            return self._ok(rid, {'tools': specs})
        if method == 'tools/call':
            params = message.get('params') or {}
            name = params.get('name')
            remote_call = self.remote is not None and self.remote.accepts(name)
            if name not in self.tools and not remote_call:
                return self._error(rid, -32602, 'unknown tool')
            busy_key = (account, 'remote' if remote_call else 'progress' if name == PROGRESS_NAME else 'browser')
            with self._guard:
                if busy_key in self._busy:
                    return self._ok(rid, self._result('Another tool call is still running for this task. Wait for it to finish.', True))
                self._busy.add(busy_key)
            try:
                handler = self.remote if remote_call else self.progress if name == PROGRESS_NAME else self.tool
                arguments = params.get('arguments') or {}
                bound = {}
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
                    if not request_id:
                        log.warning('tool_ownership_refused tool=%s reason=%s', name, status)
                        return self._ok(rid, self._result('This tool call does not belong to an admitted live task. Nothing was started or changed. Do not retry this call in another task.', True))
                    bound['request_id'] = request_id
                arguments = {k: v for k, v in arguments.items() if k != '_lumina_origin'}
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
            if remote_call:
                return self._ok(rid, result)
            text, is_error, *image = result
            return self._ok(rid, self._result(text, is_error, image[0] if image else None))
        return self._error(rid, -32601, 'method not found')

    def _owner(self, account, origin):
        if not isinstance(origin, dict) or not all(isinstance(origin.get(k), str) and origin[k] for k in ('session_key', 'run_id', 'call_id')):
            return None
        with self.tool.store.connect() as con:
            rows = con.execute("""SELECT DISTINCT r.id FROM customer_requests r
                JOIN conversations c ON c.account_id=r.account_id AND c.id=r.conversation_id
                JOIN chat_deliveries d ON d.account_id=r.account_id AND d.request_id=r.id
                JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND r.state IN ('starting','running') AND r.closing=0 AND r.cancel_requested=0
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
            if byok is not None and self.path.split('?', 1)[0] == RELAY_PREFIX + '/models':
                account = self._caller()
                if account:
                    from .model_keys import RelayError
                    try:
                        self._send(200, byok.models(account))
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
                up = byok.chat(account, raw)
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
            if byok is not None and path == RELAY_PREFIX + '/chat/completions':
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
