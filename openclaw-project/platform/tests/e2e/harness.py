"""The whole native path, for real, on one machine: OpenClaw 2026.9.6 gateways (one per customer cell), the host cell bridge on its unix socket, the tool relay, and Lumina's
own queue, worker, driver and ledger. Only two things are scripted: the model (stub_model.py) and the host browse service (states it reports for a job).

The cells are configured by lifecycle/cell_config.patch, the same function that provisions production cells, so the deny list, the MCP tool server, the run backstop and the
model route are the ones a real cell gets. Needs node and the OpenClaw package that matches the pin (2026.9.6); without them the end-to-end tests are skipped.
"""
from __future__ import annotations
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.browse.adapter import BrowserTool
from agentai_platform.budget import BudgetLedger
from agentai_platform.capacity import CapacityResult
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.chat_driver import ChatDriver
from agentai_platform.events import EventService
from agentai_platform.gateway import NativeGateway
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.goals import GoalChain
from agentai_platform.lifecycle import cell_config
from agentai_platform.lifecycle.cell_bridge import RELAY_JS, CellBridge, DockerRelay, serve as serve_bridge
from agentai_platform.request_queue import RequestQueue
from agentai_platform.request_worker import RequestWorker
from agentai_platform.security import Principal
from agentai_platform.store import Store
from agentai_platform.tool_relay import Identity, Relay, serve as serve_relay
from .stub_model import StubModel

PIN = '2026.9.6'
CAPACITY = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': int(time.time()) - 100000, 'period_microusd': 10 ** 9, 'daily_microusd': 10 ** 9, 'task_microusd': 5 * 10 ** 6, 'max_queued_tasks': 6}


def openclaw_package():
    candidates = [os.environ.get('OPENCLAW_PACKAGE', '')] + glob.glob(os.path.expanduser('~/.npm-global/lib/node_modules/openclaw')) + glob.glob('/usr/local/lib/node_modules/openclaw') \
        + glob.glob('/opt/homebrew/lib/node_modules/openclaw')
    for path in candidates:
        manifest = Path(path) / 'package.json' if path else None
        if manifest and manifest.is_file() and json.loads(manifest.read_text()).get('version') == PIN and (Path(path) / 'openclaw.mjs').is_file():
            return Path(path)
    return None


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LocalRelay(DockerRelay):
    """The bridge's relay process, run on this machine against a local gateway instead of `docker exec` into a cell: the same Node program, the same frames."""

    def __init__(self, port, token, scopes=None, media_root=None):
        self.proc = subprocess.Popen(['node', '-e', RELAY_JS.replace('127.0.0.1:18789', f'127.0.0.1:{port}')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0)
        self._buf = b''
        self.write({'token': token, **({'scopes': list(scopes)} if scopes else {}), **({'mediaRoot': str(media_root)} if media_root else {})})


class FakeBrowse:
    """The host browse service as the app sees it: start/poll/cancel for a job, with the states a test scripts."""

    def __init__(self):
        self.script, self.calls, self.lock = [], [], threading.Lock()

    def __call__(self, op, **params):
        with self.lock:
            self.calls.append((op, params))
            if op == 'poll':
                nxt = self.script.pop(0) if len(self.script) > 1 else (self.script[0] if self.script else {'state': 'error', 'reason': 'no script', 'events': []})
                if isinstance(nxt, Exception):
                    raise nxt
                return nxt
        return {'ok': True}


class Cell:
    def __init__(self, stack, account, tenant):
        self.stack, self.account, self.tenant = stack, account, tenant
        self.port, self.token, self.key = free_port(), 'gw-token-' + account, 'sk-cell-key-' + account
        self.root = stack.root / 'cells' / tenant
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir(parents=True)
        base = {'gateway': {'mode': 'local', 'port': self.port, 'bind': 'loopback', 'auth': {'mode': 'token', 'token': self.token}}}
        config = cell_config.patch(base, relay=f'http://127.0.0.1:{stack.model.port}', tools=(f'http://127.0.0.1:{stack.relay_port}/mcp', self.key))
        config['agents']['defaults']['workspace'] = str(self.workspace)
        (self.root / 'state').mkdir()
        self.config = config
        (self.root / 'state' / 'openclaw.json').write_text(json.dumps(config, indent=2))
        self.log = open(self.root / 'gateway.log', 'wb')
        self.start()

    def kill(self):
        """The cell goes away without warning (host reboot, OOM, crash): no drain, no goodbye."""
        self.proc.kill()
        self.proc.wait(15)

    def start(self):
        env = {**os.environ, 'HOME': str(self.root / 'home'), 'OPENCLAW_STATE_DIR': str(self.root / 'state'), 'OPENCLAW_CONFIG_PATH': str(self.root / 'state' / 'openclaw.json'),
               'LITELLM_API_KEY': self.key}
        self.proc = subprocess.Popen(['node', str(self.stack.package / 'openclaw.mjs'), 'gateway', 'run', '--port', str(self.port), '--auth', 'token', '--token', self.token, '--allow-unconfigured'],
                                     env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def wait_ready(self, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError('gateway exited: ' + (self.root / 'gateway.log').read_text()[-800:])
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/', timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError('gateway not ready')

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


class Stack:
    def __init__(self, package):
        self.package = package
        self.root = Path(tempfile.mkdtemp(prefix='lumina-e2e-'))
        self.model = StubModel()
        self.browse = FakeBrowse()
        self.relay_port = free_port()
        self.cells, self.errors = {}, []
        self.sockets_dir = Path(tempfile.mkdtemp(prefix='lumina-e2e-sock-'))      # unix socket paths are short-limited: keep them out of the deep temp tree
        self.socket = str(self.sockets_dir / 'bridge.sock')
        self._servers = []

    # -- bring everything up -------------------------------------------------------------------------------------------------------------------
    def start(self, accounts=('a', 'b')):
        self.relay_server = None
        # the tool relay's port is needed by the cells' config, so the relay server is created first (its identity check calls the bridge, which starts a moment later)
        self.bridge_ready = threading.Event()
        for account in accounts:
            self.cells[account] = Cell(self, account, 'tnt-' + account)
        by_account = {a: c for a, c in self.cells.items()}
        by_key = {c.key: a for a, c in by_account.items()}
        bridge = CellBridge(lambda account: (by_account[account].tenant, by_account[account].token) if account in by_account else None,
                            lambda tenant, token, scopes=None: LocalRelay(next(c.port for c in by_account.values() if c.tenant == tenant), token, scopes),
                            lambda tenant: self.model.calls(next(c.key for c in by_account.values() if c.tenant == tenant)) * 1000,
                            binding=lambda account: by_account[account].tenant if account in by_account else None, workspace_root=str(self.root / 'cells'),
                            identify=lambda credential: by_key.get(credential), ready_timeout=60, native_state_subdir='state')
        self.bridge = bridge
        server = serve_bridge(bridge, self.socket, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        self.store = Store(self.root / 'app' / 'db.sqlite3')
        self.store.initialize()
        self.events = EventService(self.store)
        self.principals = {}
        with self.store.connect() as con:
            for a in accounts:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (a, 'd-' + a))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (a, 'p-' + a))
                con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'e2e','trial',?,datetime(?,'unixepoch'))", (a, 'e-' + a, json.dumps(LIMITS), int(time.time()) + 10 ** 6))
                self.principals[a] = Principal(a, 'actor-' + a, 'customer')
        gateway = lambda account: NativeGateway(BridgeRpc(account, self.socket))
        self.queue = RequestQueue(self.store, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10 ** 12)
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1_000_000), execution=True, browse=True, events=self.events, gateway_factory=gateway)
        from agentai_platform.artifacts import ArtifactService
        from agentai_platform.storage import RootStore
        self.artifacts = ArtifactService(self.store, storage=RootStore(self.root / 'storage'), signing_key=b'k' * 32)
        self.driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=lambda claim: gateway(claim.account_id), events=self.events, artifacts=self.artifacts, sleep=time.sleep,
                                 heartbeat=self.queue.heartbeat, genui=GenUiRuntime(self.store, self.chat.blocks), browse_factory=lambda account: self.browse, queue=self.queue,
                                 wait_ms=1500, pause=0.1, run_timeout=90, usage_wait=3, spend_check_seconds=3600)
        self.worker = RequestWorker(self.queue, self.driver, lambda: CAPACITY, goals=GoalChain(self.chat), runner=lambda: self.chat.runner)
        tool = BrowserTool(self.store, browse_factory=lambda account: self.browse, events=self.events, sleep=time.sleep, poll_interval=0.3, run_timeout=120)
        identify = lambda credential: BridgeRpc('-', self.socket)('cell.identify', {'credential': credential}).get('account')
        from agentai_platform.lifecycle.tool_origin import resolve
        origin = lambda account, name, arguments: resolve(self.cells[account].root / 'state', name, arguments)
        self.tool_server = serve_relay(Relay(tool, origin=origin), Identity(identify), '127.0.0.1', self.relay_port)
        threading.Thread(target=self.tool_server.serve_forever, daemon=True).start()
        for cell in self.cells.values():
            cell.wait_ready()

    def stop(self):
        for cell in self.cells.values():
            cell.stop()
        for server in self._servers + [getattr(self, 'tool_server', None)]:
            if server is not None:
                server.shutdown(); server.server_close()
        self.bridge.close_all()
        self.model.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.sockets_dir, ignore_errors=True)

    # -- helpers for scenarios -----------------------------------------------------------------------------------------------------------------
    def hold_cell(self, account):
        with self.store.connect() as con:
            con.execute('DELETE FROM lifecycle_slot')
            op = f'op-{account}-{time.time_ns()}'
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES (?,?,?,'start','completed',?,'h',1)", (account, op, 'd-' + account, op))
            con.execute("INSERT INTO lifecycle_slot VALUES (1,?,?,?,'active')", (account, 'd-' + account, op))

    def new_conversation(self, account):
        """A conversation of its own = a native session of its own (scenarios that count turns need one)."""
        return self.chat.create_conversation(self.principals[account], 'p-' + account)['id']

    def say(self, account, message, key, conversation=None, **kw):
        return self.chat.send(self.principals[account], conversation_id=conversation or 'c-' + account, message=message, key=key, **kw)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]

    def request(self, request_id):
        return self.rows('SELECT * FROM customer_requests WHERE id=?', (request_id,))[0]

    def work(self, until=None, timeout=90, survive=False):
        """Tick the worker until `until()` is true (or nothing is left to do): the same loop the production command runs. With `survive`, a tick that raises is recorded and the
        loop goes on, exactly as the production command does (the queue has marked the request uncertain, and the next tick recovers it)."""
        deadline = time.time() + timeout
        reports = []
        while time.time() < deadline:
            try:
                report = self.worker.tick()
            except Exception as error:
                if not survive:
                    raise
                report = {'error': type(error).__name__, 'detail': str(error)[:100]}
                self.errors.append(report)
            reports.append(report)
            if until is not None:
                if until():
                    return reports
            elif report == {'ran': 0} and not self.rows("SELECT 1 FROM customer_requests WHERE state IN ('waiting','starting','running','uncertain')"):
                return reports
            time.sleep(0.05)
        raise AssertionError('timed out; last reports: %s' % reports[-3:])

    def in_background(self, until, timeout=90, survive=False):
        """Run the worker in a thread (so the test can steer, stop or inspect while a request runs)."""
        out = {}
        thread = threading.Thread(target=lambda: out.setdefault('reports', self.work(until, timeout, survive)), daemon=True)
        thread.start()
        return thread, out

    def wait_for(self, condition, timeout=60, message='condition'):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = condition()
            if value:
                return value
            time.sleep(0.1)
        raise AssertionError('timed out waiting for ' + message)
