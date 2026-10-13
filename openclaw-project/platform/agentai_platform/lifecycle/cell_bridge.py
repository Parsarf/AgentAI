"""Host-side bridge between the app and a customer cell's Gateway (root service).

The app never holds a cell token or a docker handle. It sends
``{account_id, method, params}`` over a private unix socket; the bridge maps the
account to its enrolled cell, validates an allowlisted method, and relays one
frame through ``docker exec`` into a Node process inside the cell that talks to
the Gateway on the cell's own loopback (the only path that grants operator
scopes; a Docker-published port yields none). Usage comes from the cell's
LiteLLM virtual key, never from the cell's own (zeroed) counters.
"""
import json
import os
import re
import select
import socket
import socketserver
import struct
import subprocess
import threading
import time

PROTOCOL = 4
SESSION_KEY = re.compile(r'^agent:main:[A-Za-z0-9_.:-]{1,120}$')
TOKEN_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
ALLOWED = ('hello', 'sessions.create', 'chat.send', 'chat.history', 'chat.abort', 'usage.snapshot', 'cell.status')
MAX_MESSAGE = 20000

RELAY_JS = r"""
const rl = require('readline').createInterface({ input: process.stdin });
const out = o => process.stdout.write(JSON.stringify(o) + '\n');
let cfg = null, ws = null, ready = false, attempts = 0; const queue = [], pending = new Map();
function connect() {
  ws = new WebSocket('ws://127.0.0.1:18789/');
  ws.addEventListener('message', e => {
    let d; try { d = JSON.parse(String(e.data)); } catch { return; }
    if (d.type === 'event' && d.event === 'connect.challenge') {
      ws.send(JSON.stringify({ type: 'req', id: 'connect', method: 'connect', params: { minProtocol: 3, maxProtocol: 4,
        client: { id: 'gateway-client', version: '1.0.0', platform: 'linux', mode: 'backend' }, role: 'operator',
        scopes: ['operator.read', 'operator.write'], auth: { token: cfg.token } } }));
    } else if (d.type === 'res' && d.id === 'connect') {
      if (d.ok) { ready = true; const p = d.payload || {}; out({ ready: true, protocol: p.protocol, server: p.server, methods: ((p.features || {}).methods || []) });
        while (queue.length) send(queue.shift()); }
      else { ws.close(); }
    } else if (d.type === 'res' && pending.has(d.id)) {
      const id = pending.get(d.id); pending.delete(d.id);
      out({ id, ok: !!d.ok, payload: d.payload, error: d.error ? { code: d.error.code } : undefined });
    }
  });
  ws.addEventListener('close', () => { if (ready) process.exit(3); if (++attempts > 60) process.exit(4); setTimeout(connect, 2000); });
  ws.addEventListener('error', () => {});
}
function send(r) { const gid = 'r' + r.id; pending.set(gid, r.id); ws.send(JSON.stringify({ type: 'req', id: gid, method: r.method, params: r.params })); }
rl.on('line', line => {
  if (!cfg) { cfg = JSON.parse(line); connect(); return; }
  const r = JSON.parse(line); if (ready) send(r); else queue.push(r);
});
rl.on('close', () => process.exit(0));
"""


class BridgeError(Exception):
    pass


class DockerRelay:
    """One docker-exec Node relay inside a cell."""

    def __init__(self, tenant, token, *, docker_host, popen=subprocess.Popen):
        env = {**os.environ, 'DOCKER_HOST': docker_host}
        self.proc = popen(['docker', 'exec', '-i', f'openclaw-cell-{tenant}', 'node', '-e', RELAY_JS],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, bufsize=0)
        self._buf = b''
        self.write({'token': token})        # the token travels on stdin only, never argv

    def write(self, obj):
        self.proc.stdin.write((json.dumps(obj) + '\n').encode())
        self.proc.stdin.flush()

    def read(self, timeout):
        """Next JSON line, or None on timeout; raises BridgeError when the relay exited."""
        deadline = time.monotonic() + timeout
        while b'\n' not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            ready, _, _ = select.select([self.proc.stdout], [], [], min(left, 1.0))
            if ready:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    raise BridgeError('relay closed')
                self._buf += chunk
            elif self.proc.poll() is not None:
                raise BridgeError('relay exited')
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line)

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


class CellBridge:
    def __init__(self, lookup, spawn, spend, *, binding=None, probe=None, ready_timeout=120, call_timeout=60, idle_seconds=300, clock=time.monotonic):
        """lookup(account)->(tenant, token) or None; spawn(tenant, token)->relay; spend(tenant)->microusd."""
        self.lookup, self.spawn, self.spend = lookup, spawn, spend
        self.binding, self.probe = binding, probe   # binding(account)->tenant regardless of state; probe(tenant)->container running
        self.ready_timeout, self.call_timeout, self.idle_seconds, self.clock = ready_timeout, call_timeout, idle_seconds, clock
        self._conns = {}
        self._locks = {}
        self._guard = threading.Lock()

    @staticmethod
    def validate(method, params):
        if method not in ALLOWED or not isinstance(params, dict):
            raise BridgeError('method not allowed')
        if method in ('hello', 'usage.snapshot', 'cell.status'):
            return {}
        if method == 'sessions.create':
            label = params.get('label')
            if not isinstance(label, str) or not TOKEN_ID.fullmatch(label):
                raise BridgeError('invalid label')
            return {'agentId': 'main', 'label': label}
        key = params.get('sessionKey')
        if not isinstance(key, str) or not SESSION_KEY.fullmatch(key):
            raise BridgeError('invalid session key')
        if method == 'chat.abort':
            return {'sessionKey': key}
        if method == 'chat.history':
            out = {'sessionKey': key}
            cursor = params.get('cursor')
            if cursor is not None:
                if not isinstance(cursor, str) or len(cursor) > 512:
                    raise BridgeError('invalid cursor')
                out['cursor'] = cursor
            return out
        message, idem = params.get('message'), params.get('idempotencyKey')
        if not isinstance(message, str) or not 1 <= len(message) <= MAX_MESSAGE or not isinstance(idem, str) or not TOKEN_ID.fullmatch(idem):
            raise BridgeError('invalid message')
        return {'sessionKey': key, 'message': message, 'idempotencyKey': idem}

    def _lock(self, account):
        with self._guard:
            return self._locks.setdefault(account, threading.Lock())

    def _connection(self, account):
        found = self.lookup(account)
        if not found:
            raise BridgeError('no cell')
        tenant, token = found
        conn = self._conns.get(account)
        if conn and conn['tenant'] == tenant and conn['relay'].alive():
            return conn
        if conn:
            conn['relay'].close()
            self._conns.pop(account, None)
        relay = self.spawn(tenant, token)
        try:
            deadline = self.clock() + self.ready_timeout
            hello = None
            while hello is None:
                left = deadline - self.clock()
                if left <= 0:
                    raise BridgeError('gateway not ready')
                frame = relay.read(min(left, 5))
                if frame and frame.get('ready'):
                    hello = frame
        except Exception:
            relay.close()
            raise
        conn = {'tenant': tenant, 'relay': relay, 'hello': hello, 'next': 1, 'used': self.clock()}
        self._conns[account] = conn
        return conn

    def call(self, account, method, params):
        clean = self.validate(method, params)
        if method == 'cell.status':
            tenant = self.binding(account) if self.binding else None
            if tenant is None or self.probe is None:
                raise BridgeError('no cell')
            return {'running': bool(self.probe(tenant))}
        if method == 'usage.snapshot':
            tenant = self.binding(account) if self.binding else None
            if tenant is None:
                found = self.lookup(account)
                tenant = found[0] if found else None
            if tenant is None:
                raise BridgeError('no cell')
            return {'spend_microusd': self.spend(tenant)}
        with self._lock(account):
            conn = self._connection(account)
            conn['used'] = self.clock()
            if method == 'hello':
                allowed = [m for m in ALLOWED if m in (conn['hello'].get('methods') or [])]
                return {'protocol': conn['hello'].get('protocol'), 'runtimeVersion': (conn['hello'].get('server') or {}).get('version', 'unverified')
                        if isinstance(conn['hello'].get('server'), dict) else 'unverified', 'methods': allowed}
            rid = str(conn['next'])
            conn['next'] += 1
            try:
                conn['relay'].write({'id': rid, 'method': method, 'params': clean})
                deadline = self.clock() + self.call_timeout
                while True:
                    left = deadline - self.clock()
                    if left <= 0:
                        raise BridgeError('gateway timeout')
                    frame = conn['relay'].read(min(left, 5))
                    if frame and frame.get('id') == rid:
                        break
            except (BridgeError, OSError):
                conn['relay'].close()
                self._conns.pop(account, None)
                raise
            if not frame.get('ok'):
                return {'error': (frame.get('error') or {}).get('code', 'ERROR')}
            return frame.get('payload') or {}

    def sweep(self):
        """Close relays idle past the limit (called by the server's timer)."""
        with self._guard:
            accounts = list(self._conns)
        for account in accounts:
            if not self._lock(account).acquire(blocking=False):
                continue
            try:
                conn = self._conns.get(account)
                if conn and self.clock() - conn['used'] > self.idle_seconds:
                    conn['relay'].close()
                    self._conns.pop(account, None)
            finally:
                self._lock(account).release()

    def close_all(self):
        for conn in list(self._conns.values()):
            conn['relay'].close()
        self._conns.clear()


def linux_peer_uid(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]


def serve(bridge, path, *, allowed_uids, group_gid=None, peer_uid=linux_peer_uid):
    """Blocking unix-socket server; one JSON request line per connection."""
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            if peer_uid(self.request) not in allowed_uids:
                return
            try:
                req = json.loads(self.rfile.readline(MAX_MESSAGE * 4 + 4096))
                if not isinstance(req, dict) or not isinstance(req.get('account_id'), str):
                    raise BridgeError('invalid request')
                reply = {'ok': True, 'result': bridge.call(req['account_id'], req.get('method'), req.get('params') or {})}
            except BridgeError as exc:
                reply = {'ok': False, 'error': str(exc)}
            except Exception:
                reply = {'ok': False, 'error': 'bridge error'}
            self.wfile.write((json.dumps(reply) + '\n').encode())

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    if os.path.exists(path):
        os.unlink(path)
    server = Server(path, Handler)
    os.chmod(path, 0o660)
    if group_gid is not None:
        os.chown(path, 0, group_gid)

    def timer():
        while True:
            time.sleep(30)
            bridge.sweep()
    threading.Thread(target=timer, daemon=True).start()
    return server
