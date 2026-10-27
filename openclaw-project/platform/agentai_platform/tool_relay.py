"""The door from a customer cell to the tools Lumina serves natively (today: the sandboxed browser). Runs as the app user, bound to the cells' bridge address.

The cell's OpenClaw connects to this as an MCP server (streamable HTTP, JSON replies) and lists and calls its tools like any native tool. Three rules keep it a door and
not a hole:

* The caller proves which cell it is with the credential the cell was provisioned with (its own model key). The root bridge checks it (``cell.identify``); this process
  never holds a secret of its own, and a credential that matches no running cell gets nothing.
* Only the tools in TOOLS exist, and a call is only served for the calling account's own running request (browse/adapter.py): nothing a cell sends can name another account.
* One tool call at a time per account, bounded request size, and a call whose connection drops is stopped: Stop and a stopped run reach the browser job.

Nothing about content is logged; counts and states only.
"""
from __future__ import annotations
import hmac
import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .adapters import CapabilityUnavailable
from .browse.adapter import STEP, STEP_NAME, TOOL, TOOL_NAME, BrowserTool

PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
MAX_BODY = 64 * 1024
IDENTIFY_TTL = 60
FAIL_LIMIT = 20                     # refused credentials per source address per minute before it is told to slow down
TOOLS = {TOOL_NAME: TOOL, STEP_NAME: STEP}


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

    def __init__(self, tool: BrowserTool):
        self.tool = tool
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
            return self._ok(rid, {'tools': list(TOOLS.values())})
        if method == 'tools/call':
            params = message.get('params') or {}
            name = params.get('name')
            if name not in TOOLS:
                return self._error(rid, -32602, 'unknown tool')
            with self._guard:
                if account in self._busy:
                    return self._ok(rid, self._result('Another browser call is still running for this task. Wait for it to finish.', True))
                self._busy.add(account)
            try:
                result = self.tool.call(account, params.get('arguments') or {}, closed, name=name)
            finally:
                with self._guard:
                    self._busy.discard(account)
            text, is_error, *image = result
            return self._ok(rid, self._result(text, is_error, image[0] if image else None))
        return self._error(rid, -32601, 'method not found')

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


def make_handler(relay: Relay, identity: Identity):
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

        def do_GET(self):
            self._send(405, {'error': 'method not allowed'})          # no server-sent events: replies are plain JSON

        def do_DELETE(self):
            self._send(200, {})

        def do_POST(self):
            if self.path.split('?', 1)[0] != '/mcp':
                return self._send(404, {'error': 'not found'})
            header = self.headers.get('Authorization', '')
            credential = header[7:].strip() if header.lower().startswith('bearer ') else ''
            try:
                account = identity.account(credential, self.client_address[0]) if len(credential) >= 8 else None
            except PermissionError:
                return self._send(429, {'error': 'slow down'})
            if not account:
                return self._send(401, {'error': 'unauthorized'})
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


def serve(relay: Relay, identity: Identity, host: str, port: int):
    server = ThreadingHTTPServer((host, port), make_handler(relay, identity))
    server.daemon_threads = True
    return server
