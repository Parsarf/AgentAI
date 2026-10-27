"""Host-side bridge between the app and a customer cell's Gateway (root service).

The app never holds a cell token or a docker handle. It sends
``{account_id, method, params}`` over a private unix socket; the bridge maps the
account to its enrolled cell, validates an allowlisted method, and relays one
frame through ``docker exec`` into a Node process inside the cell that talks to
the Gateway on the cell's own loopback (the only path that grants operator
scopes; a Docker-published port yields none). Usage comes from the cell's
LiteLLM virtual key, never from the cell's own (zeroed) counters.
"""
import hmac
import json
import os
import queue
import re
import select
import socket
import socketserver
import struct
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL = 4
SESSION_KEY = re.compile(r'^agent:main:[A-Za-z0-9_.:-]{1,120}$')
TOKEN_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
ALLOWED = ('hello', 'sessions.create', 'sessions.describe', 'chat.send', 'chat.history', 'chat.abort', 'agent.wait', 'sessions.goal.update', 'sessions.goal.clear',
           'usage.snapshot', 'cell.status', 'cell.identify', 'workspace.collect', 'browser.request', 'browser.shot', 'browser.live', 'browser.frame')
# The cell's native browser. Its gateway method needs operator.admin, which the main connection never has: these calls travel on a second connection of their own, and only a
# caller the socket server names (the browse service, root) may use them. The app itself cannot.
BROWSER_METHODS = ('browser.request', 'browser.shot', 'browser.live', 'browser.frame')
BROWSER_SCOPES = ['operator.read', 'operator.write', 'operator.admin']
BROWSER_PROFILE = 'openclaw'
MAX_BROWSER_URL = 2048
# (method, path) pairs the host may ask of the browser, and nothing else: no cookies, storage, headers, downloads, file chooser, or arbitrary script.
BROWSER_ROUTES = {('GET', '/'), ('POST', '/start'), ('POST', '/stop'), ('GET', '/tabs'), ('POST', '/tabs/open'), ('POST', '/tabs/focus'), ('POST', '/tabs/close'), ('POST', '/navigate'), ('POST', '/act')}
BROWSER_KEYS = ('Enter', 'Tab', 'Escape', 'Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp')
MAX_ARGS_BYTES = 8000
QUEUE_MODES = ('steer', 'followup', 'collect', 'interrupt')
GOAL_ACTIONS = ('pause', 'resume', 'block', 'complete', 'edit')
BRIDGE_ERROR = '__error__'           # the key a refused call comes back under; payload fields of the runtime's own (like a run's `error`) never use it
MAX_MESSAGE = 20000
MAX_WAIT_MS = 30000          # one agent.wait is a slice; the caller loops, so Stop and steering are never queued behind a long wait

RELAY_JS = r"""
const rl = require('readline').createInterface({ input: process.stdin });
const fs = require('fs');
const out = o => process.stdout.write(JSON.stringify(o) + '\n');
let cfg = null, ws = null, ready = false, attempts = 0, seq = 0; const queue = [], pending = new Map();
const MAX_SHOT = 6 * 1024 * 1024;
function connect() {
  ws = new WebSocket('ws://127.0.0.1:18789/');
  ws.addEventListener('message', e => {
    let d; try { d = JSON.parse(String(e.data)); } catch { return; }
    if (d.type === 'event' && d.event === 'connect.challenge') {
      ws.send(JSON.stringify({ type: 'req', id: 'connect', method: 'connect', params: { minProtocol: 3, maxProtocol: 4,
        client: { id: 'gateway-client', version: '1.0.0', platform: 'linux', mode: 'backend' }, role: 'operator',
        scopes: cfg.scopes || ['operator.read', 'operator.write'], auth: { token: cfg.token } } }));
    } else if (d.type === 'res' && d.id === 'connect') {
      if (d.ok) { ready = true; const p = d.payload || {}; out({ ready: true, protocol: p.protocol, server: p.server, methods: ((p.features || {}).methods || []) });
        while (queue.length) dispatch(queue.shift()); }
      else { ws.close(); }
    } else if (d.type === 'res' && pending.has(d.id)) {
      const done = pending.get(d.id); pending.delete(d.id); done(d);
    }
  });
  ws.addEventListener('close', () => { if (ready) process.exit(3); if (++attempts > 60) process.exit(4); setTimeout(connect, 2000); });
  ws.addEventListener('error', () => {});
}
function gateway(method, params) {
  return new Promise(resolve => { const gid = 'g' + (++seq); pending.set(gid, resolve); ws.send(JSON.stringify({ type: 'req', id: gid, method, params })); });
}
function send(r) {
  const gid = 'r' + r.id; pending.set(gid, d => out({ id: r.id, ok: !!d.ok, payload: d.payload, error: d.error ? { code: d.error.code } : undefined }));
  ws.send(JSON.stringify({ type: 'req', id: gid, method: r.method, params: r.params }));
}
// The browser's picture is a file the browser plugin wrote inside the cell. Only the relay (which runs inside the cell) can read it: it hands the bytes back and deletes the file.
async function shot(r) {
  const d = await gateway('browser.request', { method: 'POST', path: '/screenshot', body: r.params.body, query: r.params.query });
  if (!d.ok) return out({ id: r.id, ok: false, error: { code: (d.error || {}).code || 'ERROR' } });
  const p = d.payload || {};
  try {
    const root = fs.realpathSync(cfg.mediaRoot || '/home/node/.openclaw/media/browser');
    const file = fs.realpathSync(p.path);
    if (!file.startsWith(root + '/') || !fs.statSync(file).isFile() || fs.statSync(file).size > MAX_SHOT) throw new Error('outside');
    const data = fs.readFileSync(file); try { fs.unlinkSync(file); } catch {}
    out({ id: r.id, ok: true, payload: { data_b64: data.toString('base64'), url: p.url, targetId: p.targetId } });
  } catch { out({ id: r.id, ok: false, error: { code: 'NO_PICTURE' } }); }
}
// Live view: the newest screencast frame of the current tab. The relay mints the stream's single-use ticket on its own gateway connection (a ticket is bound to it), reads
// the frames, and keeps only the newest. Nobody asking for 10 s turns it off (no cost when nobody watches).
const live = { on: false, ws: null, frame: null, seq: 0, last: 0, waiters: [], timer: null, meta: null };
function liveStop() { live.on = false; if (live.ws) { try { live.ws.close(); } catch {} live.ws = null; } clearInterval(live.timer); live.timer = null; }
async function liveOpen(profile) {
  if (!live.on) return;
  const d = await gateway('browser.request', { method: 'POST', path: '/screencast', body: { maxWidth: 1280, maxHeight: 800, quality: 60 }, query: { profile } });
  if (!live.on) return;
  if (!d.ok || !d.payload || !d.payload.wsPath) { setTimeout(() => liveOpen(profile), 2000); return; }
  const w = new WebSocket('ws://127.0.0.1:18789' + d.payload.wsPath); w.binaryType = 'arraybuffer'; live.ws = w;
  w.addEventListener('message', e => {
    if (typeof e.data === 'string') return;
    const b = Buffer.from(e.data); if (b.length < 5) return;
    const n = b.readUInt32BE(0); if (4 + n > b.length) return;
    live.frame = b.subarray(4 + n); live.seq += 1; live.last = Date.now();
    let m = null; try { m = JSON.parse(b.subarray(4, 4 + n).toString('utf8')); } catch {}
    live.meta = m; const ws2 = live.waiters; live.waiters = []; ws2.forEach(f => f());
  });
  w.addEventListener('close', () => { if (live.ws === w) { live.ws = null; if (live.on) setTimeout(() => liveOpen(profile), 500); } });
  w.addEventListener('error', () => {});
}
async function liveCmd(r) {
  const p = r.params || {};
  if (r.method === 'browser.live') {
    if (p.on && !live.on) { live.on = true; live.last = Date.now(); live.timer = setInterval(() => { if (Date.now() - live.last > 10000) liveStop(); }, 2000); liveOpen(p.profile || 'openclaw'); }
    if (!p.on) liveStop();
    return out({ id: r.id, ok: true, payload: { on: live.on } });
  }
  if (!live.on) return out({ id: r.id, ok: true, payload: { on: false, seq: live.seq } });
  live.last = Date.now();                                    // a viewer is asking: keep the stream up
  const after = Number.isInteger(p.after) ? p.after : 0;
  const reply = () => out({ id: r.id, ok: true, payload: live.seq > after && live.frame ? { on: true, seq: live.seq, data_b64: live.frame.toString('base64'), meta: live.meta } : { on: true, seq: live.seq } });
  if (live.seq > after || !p.waitMs) return reply();
  let done = false; const fin = () => { if (!done) { done = true; reply(); } };
  live.waiters.push(fin); setTimeout(fin, Math.min(p.waitMs, 5000));
}
function dispatch(r) {
  if (r.method === 'browser.shot') return void shot(r);
  if (r.method === 'browser.live' || r.method === 'browser.frame') return void liveCmd(r);
  send(r);
}
rl.on('line', line => {
  if (!cfg) { cfg = JSON.parse(line); connect(); return; }
  const r = JSON.parse(line); if (ready) dispatch(r); else queue.push(r);
});
rl.on('close', () => process.exit(0));
"""


class BridgeError(Exception):
    pass


class DockerRelay:
    """One docker-exec Node relay inside a cell."""

    def __init__(self, tenant, token, *, docker_host, popen=subprocess.Popen, scopes=None):
        env = {**os.environ, 'DOCKER_HOST': docker_host}
        self.proc = popen(['docker', 'exec', '-i', f'openclaw-cell-{tenant}', 'node', '-e', RELAY_JS],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, bufsize=0)
        self._buf = b''
        self.write({'token': token, **({'scopes': list(scopes)} if scopes else {})})        # the token travels on stdin only, never argv

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


class _Connection:
    """One relay to one cell. A reader thread hands every reply to whoever waits for it, so calls overlap: a long agent.wait never holds up Stop or a steer."""

    def __init__(self, tenant, relay, hello, clock):
        self.tenant, self.relay, self.hello, self.clock = tenant, relay, hello, clock
        self.write_lock, self.guard = threading.Lock(), threading.Lock()
        self.waiters, self.next, self.dead = {}, 1, False
        self.used = self.last_frame = clock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while not self.dead:
            try:
                frame = self.relay.read(1.0)
            except Exception:
                break
            if frame is None:
                if not self.relay.alive():
                    break
                continue
            self.last_frame = self.clock()
            with self.guard:
                box = self.waiters.get(frame.get('id'))
            if box is not None:
                box.put(frame)
        self.close()

    def alive(self):
        return not self.dead and self.relay.alive()

    def busy(self):
        with self.guard:
            return bool(self.waiters)

    def close(self):
        with self.guard:
            self.dead = True
            boxes = list(self.waiters.values())
        for box in boxes:
            box.put(None)           # None: the relay went away under the caller
        self.relay.close()

    def request(self, method, params, timeout):
        with self.guard:
            if self.dead:
                raise BridgeError('relay closed')
            rid = str(self.next)
            self.next += 1
            box = queue.Queue(1)
            self.waiters[rid] = box
            self.used = self.clock()
        try:
            try:
                with self.write_lock:
                    self.relay.write({'id': rid, 'method': method, 'params': params})
            except OSError as exc:
                self.close()
                raise BridgeError('relay closed') from exc
            try:
                frame = box.get(timeout=timeout)
            except queue.Empty:
                raise BridgeError('gateway timeout') from None
            if frame is None:
                raise BridgeError('relay closed')
            return frame
        finally:
            with self.guard:
                self.waiters.pop(rid, None)
                self.used = self.clock()


class CellBridge:
    def __init__(self, lookup, spawn, spend, *, binding=None, probe=None, workspace_root=None, identify=None, ready_timeout=120, call_timeout=60, idle_seconds=300, clock=time.monotonic,
                 browser_callers=()):
        """lookup(account)->(tenant, token) or None; spawn(tenant, token[, scopes=...])->relay; spend(tenant)->microusd; identify(credential)->account or None;
        browser_callers: the socket peers (uids) that may use the browser methods."""
        self.lookup, self.spawn, self.spend = lookup, spawn, spend
        self.browser_callers = frozenset(browser_callers)
        self._bconns = {}                    # the second, admin-scoped connection per account: only the browser methods ever use it
        self.workspace_root = workspace_root
        self.identify = identify
        self.binding, self.probe = binding, probe   # binding(account)->tenant regardless of state; probe(tenant)->container running
        self.ready_timeout, self.call_timeout, self.idle_seconds, self.clock = ready_timeout, call_timeout, idle_seconds, clock
        self._conns = {}
        self._locks = {}
        self._guard = threading.Lock()

    @staticmethod
    def validate(method, params):
        if method not in ALLOWED or not isinstance(params, dict):
            raise BridgeError('method not allowed')
        if method in BROWSER_METHODS:
            return CellBridge._browser(method, params)
        if method in ('hello', 'usage.snapshot', 'cell.status'):
            return {}
        if method == 'cell.identify':
            credential = params.get('credential')
            if not isinstance(credential, str) or not 8 <= len(credential) <= 512:
                raise BridgeError('invalid credential')
            return {'credential': credential}
        if method == 'workspace.collect':
            since = params.get('since')
            if type(since) is not int or since < 0:
                raise BridgeError('invalid since')
            return {'since': since}
        if method == 'sessions.create':
            label = params.get('label')
            if not isinstance(label, str) or not TOKEN_ID.fullmatch(label):
                raise BridgeError('invalid label')
            return {'agentId': 'main', 'label': label}
        if method == 'agent.wait':
            run, wait = params.get('runId'), params.get('timeoutMs', 0)
            if not isinstance(run, str) or not TOKEN_ID.fullmatch(run) or type(wait) is not int or not 0 <= wait <= MAX_WAIT_MS:
                raise BridgeError('invalid wait')
            return {'runId': run, 'timeoutMs': wait}
        key = params.get('sessionKey', params.get('key') if method == 'sessions.describe' else None)
        if not isinstance(key, str) or not SESSION_KEY.fullmatch(key):
            raise BridgeError('invalid session key')
        if method == 'sessions.describe':
            return {'key': key}
        if method == 'chat.abort':
            run = params.get('runId')
            if run is not None and (not isinstance(run, str) or not TOKEN_ID.fullmatch(run)):
                raise BridgeError('invalid run')
            return {'sessionKey': key, **({'runId': run} if run else {})}
        if method == 'chat.history':
            out = {'sessionKey': key}
            cursor = params.get('cursor')
            if cursor is not None:
                if not isinstance(cursor, str) or len(cursor) > 512:
                    raise BridgeError('invalid cursor')
                out['cursor'] = cursor
            return out
        if method in ('sessions.goal.update', 'sessions.goal.clear'):
            goal, op, issued = params.get('goalId'), params.get('operationId'), params.get('issuedAtMs')
            if not all(isinstance(v, str) and TOKEN_ID.fullmatch(v) for v in (goal, op)) or type(issued) is not int or issued <= 0:
                raise BridgeError('invalid goal request')
            out = {'sessionKey': key, 'goalId': goal, 'operationId': op, 'issuedAtMs': issued}
            if method == 'sessions.goal.clear':
                return out
            action, note, objective = params.get('action'), params.get('note'), params.get('objective')
            if action not in GOAL_ACTIONS or (note is not None and (not isinstance(note, str) or len(note) > 2000)):
                raise BridgeError('invalid goal action')
            out['action'] = action
            if note:
                out['note'] = note
            if action == 'edit':
                if not isinstance(objective, str) or not objective.strip() or len(objective) > 16000:
                    raise BridgeError('invalid objective')
                out['objective'] = objective
            return out
        message, idem = params.get('message'), params.get('idempotencyKey')
        if not isinstance(message, str) or not 1 <= len(message) <= MAX_MESSAGE or not isinstance(idem, str) or not TOKEN_ID.fullmatch(idem):
            raise BridgeError('invalid message')
        out = {'sessionKey': key, 'message': message, 'idempotencyKey': idem}
        mode, intent = params.get('queueMode'), params.get('intent')
        if mode is not None:
            if mode not in QUEUE_MODES:
                raise BridgeError('invalid queue mode')
            out['queueMode'] = mode
        if intent is not None:
            issued = intent.get('issuedAtMs') if isinstance(intent, dict) else None
            if not isinstance(intent, dict) or intent.get('kind') != 'session-goal-start' or intent.get('version') != 1 or type(issued) is not int or issued <= 0:
                raise BridgeError('invalid intent')
            out['intent'] = {'kind': 'session-goal-start', 'version': 1, 'issuedAtMs': issued}
        return out

    @staticmethod
    def _browser(method, params):
        """Exact shapes for the native browser. The profile is always the cell's own (never the caller's choice), a script is only ever one of ours by name, coordinates and keys are
        bounded, and an address must be plain http(s). Anything else is refused before it reaches the cell."""
        from ..browse.native_scripts import SCRIPTS, expression
        query = {'profile': BROWSER_PROFILE}
        if method == 'browser.shot':
            return {'body': {'type': 'jpeg'}, 'query': query}
        if method == 'browser.live':
            if type(params.get('on')) is not bool:
                raise BridgeError('invalid live request')
            return {'on': params['on'], 'profile': BROWSER_PROFILE}
        if method == 'browser.frame':
            after, wait = params.get('after', 0), params.get('waitMs', 0)
            if type(after) is not int or type(wait) is not int or after < 0 or not 0 <= wait <= 5000:
                raise BridgeError('invalid frame request')
            return {'after': after, 'waitMs': wait}
        verb, path, body = params.get('method'), params.get('path'), params.get('body')
        if (verb, path) not in BROWSER_ROUTES or (body is not None and not isinstance(body, dict)):
            raise BridgeError('browser route not allowed')
        body = body or {}

        def url(value):
            if not isinstance(value, str) or not 1 <= len(value) <= MAX_BROWSER_URL or not re.match(r'^https?://', value, re.I) or any(ord(c) < 33 for c in value):
                raise BridgeError('invalid address')
            return value

        if path in ('/navigate', '/tabs/open'):
            return {'method': verb, 'path': path, 'body': {'url': url(body.get('url'))}, 'query': query}
        if path in ('/tabs/focus', '/tabs/close'):
            target = body.get('targetId')
            if not isinstance(target, str) or not TOKEN_ID.fullmatch(target):
                raise BridgeError('invalid tab')
            return {'method': verb, 'path': path, 'body': {'targetId': target}, 'query': query}
        if path != '/act':
            return {'method': verb, 'path': path, 'query': query}
        kind = body.get('kind')
        if kind == 'evaluate':
            name, args = body.get('script'), body.get('args') or {}
            if name not in SCRIPTS or not isinstance(args, dict) or len(json.dumps(args)) > MAX_ARGS_BYTES:
                raise BridgeError('invalid script')
            return {'method': verb, 'path': path, 'body': {'kind': 'evaluate', 'fn': expression(name, args)}, 'query': query}
        if kind == 'clickCoords':
            x, y = body.get('x'), body.get('y')
            if not all(type(v) in (int, float) and 0 <= v <= 4000 for v in (x, y)):
                raise BridgeError('invalid coordinates')
            return {'method': verb, 'path': path, 'body': {'kind': 'clickCoords', 'x': x, 'y': y}, 'query': query}
        if kind == 'press':
            if body.get('key') not in BROWSER_KEYS:
                raise BridgeError('key not allowed')
            return {'method': verb, 'path': path, 'body': {'kind': 'press', 'key': body['key']}, 'query': query}
        if kind == 'resize':
            width, height = body.get('width'), body.get('height')
            if type(width) is not int or type(height) is not int or not 320 <= width <= 2000 or not 240 <= height <= 2000:
                raise BridgeError('invalid size')
            return {'method': verb, 'path': path, 'body': {'kind': 'resize', 'width': width, 'height': height}, 'query': query}
        raise BridgeError('browser action not allowed')

    def _lock(self, account):
        with self._guard:
            return self._locks.setdefault(account, threading.Lock())

    def _connection(self, account, scopes=None):
        found = self.lookup(account)
        if not found:
            raise BridgeError('no cell')
        tenant, token = found
        conns = self._bconns if scopes else self._conns
        with self._lock(account):                   # only connecting is serialised; calls on a live connection overlap
            conn = conns.get(account)
            if conn and conn.tenant == tenant and conn.alive():
                return conn
            if conn:
                conn.close()
                conns.pop(account, None)
            relay = self.spawn(tenant, token, scopes=scopes) if scopes else self.spawn(tenant, token)
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
            conn = _Connection(tenant, relay, hello, self.clock)
            conns[account] = conn
            return conn

    def call(self, account, method, params, caller=None):
        if method in BROWSER_METHODS and caller not in self.browser_callers:
            raise BridgeError('method not allowed')
        clean = self.validate(method, params)
        if method in BROWSER_METHODS:
            conn = self._connection(account, BROWSER_SCOPES)
            timeout = clean.get('waitMs', 0) / 1000 + 15 if method == 'browser.frame' else self.call_timeout
            frame = conn.request(method, clean, timeout)
            if not frame.get('ok'):
                return {BRIDGE_ERROR: (frame.get('error') or {}).get('code', 'ERROR')}
            return frame.get('payload') or {}
        if method == 'cell.identify':
            found = self.identify(clean['credential']) if self.identify else None
            if not found:
                raise BridgeError('unknown credential')
            return {'account': found}
        if method == 'cell.status':
            tenant = self.binding(account) if self.binding else None
            if tenant is None or self.probe is None:
                raise BridgeError('no cell')
            return {'running': bool(self.probe(tenant))}
        if method == 'workspace.collect':
            tenant = self.binding(account) if self.binding else None
            if tenant is None or self.workspace_root is None or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', tenant):
                raise BridgeError('no cell')
            import base64
            from .workspace import collect
            files = collect(Path(self.workspace_root) / tenant / 'workspace', clean['since'])
            return {'files': [{'path': name, 'data_b64': base64.b64encode(data).decode()} for name, data in files]}
        if method == 'usage.snapshot':
            tenant = self.binding(account) if self.binding else None
            if tenant is None:
                found = self.lookup(account)
                tenant = found[0] if found else None
            if tenant is None:
                raise BridgeError('no cell')
            return {'spend_microusd': self.spend(tenant)}
        conn = self._connection(account)
        if method == 'hello':
            allowed = [m for m in ALLOWED if m not in BROWSER_METHODS and m in (conn.hello.get('methods') or [])]
            return {'protocol': conn.hello.get('protocol'), 'runtimeVersion': (conn.hello.get('server') or {}).get('version', 'unverified')
                    if isinstance(conn.hello.get('server'), dict) else 'unverified', 'methods': allowed}
        timeout = clean['timeoutMs'] / 1000 + 15 if method == 'agent.wait' else self.call_timeout
        try:
            frame = conn.request(method, clean, timeout)
        except BridgeError as exc:
            if str(exc) == 'gateway timeout' and self.clock() - conn.last_frame > self.call_timeout * 2:
                conn.close()                         # nothing at all has come back for a long while: drop the relay, the next call reconnects
            raise
        if not frame.get('ok'):
            return {BRIDGE_ERROR: (frame.get('error') or {}).get('code', 'ERROR')}      # not 'error': a run's own result (agent.wait of an aborted run) carries that key
        return frame.get('payload') or {}

    def sweep(self):
        """Close relays idle past the limit (called by the server's timer). A relay with a call in flight is never idle."""
        with self._guard:
            accounts = list(self._conns) + [a for a in self._bconns if a not in self._conns]
        for account in accounts:
            lock = self._lock(account)
            if not lock.acquire(blocking=False):      # a connect is in progress for this account
                continue
            try:
                for conns in (self._conns, self._bconns):
                    conn = conns.get(account)
                    if conn and not conn.busy() and self.clock() - conn.used > self.idle_seconds:
                        conn.close()
                        conns.pop(account, None)
            finally:
                lock.release()

    def close_all(self):
        for conns in (self._conns, self._bconns):
            for conn in list(conns.values()):
                conn.close()
            conns.clear()


def linux_peer_uid(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]


def serve(bridge, path, *, allowed_uids, group_gid=None, peer_uid=linux_peer_uid):
    """Blocking unix-socket server; one JSON request line per connection."""
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            peer = peer_uid(self.request)
            if peer not in allowed_uids:
                return
            try:
                req = json.loads(self.rfile.readline(MAX_MESSAGE * 4 + 4096))
                if not isinstance(req, dict) or not isinstance(req.get('account_id'), str):
                    raise BridgeError('invalid request')
                reply = {'ok': True, 'result': bridge.call(req['account_id'], req.get('method'), req.get('params') or {}, caller=peer)}
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
