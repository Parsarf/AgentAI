"""Worker broker: fixed, host-owned execution envelopes for coding/review/browser stages.

Neither the app nor a customer Gateway gets a Docker socket. The host broker
creates one short-lived worker container per stage on the *cell* engine
(default runtime gVisor), from a host-authored catalog. Customer input never
reaches argv, image names, mounts, networks or environment: job parameters are
written to a read-only JSON file the stage reads itself. Each stage gets only
its own tenant's project/job/out directories, no secrets (except an explicit
model key file for stages that need one), dropped capabilities, a read-only
root, resource ceilings and a hard timeout; at most one stage runs on the host
at a time (flock), and every stage is drained and proven absent before the
result is recorded. This is the envelope, not the agent loop: the command run
inside a stage is chosen by name from the catalog.
"""
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

TENANT = re.compile(r'aa-[a-f0-9]{32}')
RUN_ID = re.compile(r'[a-f0-9]{32}')
IMAGE = re.compile(r'(?:[a-z0-9][a-z0-9./_-]*@)?sha256:[a-f0-9]{64}')
OUTPUT_LIMIT = 262144


class BrokerBusy(Exception): pass
class BrokerRefused(Exception): pass
class StageUncertain(Exception): pass


@dataclass(frozen=True)
class StageProfile:
    name: str
    image: str                 # digest/ID pinned, preloaded into the cell engine
    command: tuple             # fixed argv inside the image; never customer-supplied
    memory_bytes: int
    cpus: float
    pids: int
    timeout_seconds: int
    network: str               # 'none' or 'egress' (default bridge, host firewall applies)
    project: str               # 'rw' | 'ro' | 'none'
    needs_model_key: bool = False
    tmpfs_bytes: int = 64 * 1024**2

    def __post_init__(self):
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,23}', self.name): raise ValueError('invalid stage name')
        if not IMAGE.fullmatch(self.image): raise ValueError('stage image must be pinned')
        if type(self.command) is not tuple or not self.command or not all(type(a) is str and a for a in self.command):
            raise ValueError('invalid stage command')
        if self.network not in {'none', 'egress'} or self.project not in {'rw', 'ro', 'none'}:
            raise ValueError('invalid stage access')
        for v, lo, hi in [(self.memory_bytes, 64 * 1024**2, 8 * 1024**3), (self.pids, 16, 4096),
                          (self.timeout_seconds, 5, 3600), (self.tmpfs_bytes, 1024**2, 2 * 1024**3)]:
            if type(v) is not int or isinstance(v, bool) or not lo <= v <= hi: raise ValueError('invalid stage bound')
        if not 0.1 <= self.cpus <= 2: raise ValueError('invalid stage CPU')


@dataclass(frozen=True)
class WorkerBinding:
    tenant: str
    worker_uid: int            # unique per tenant, host-assigned
    shared_gid: int            # the cell's gid so the cell can read/write the shared dirs
    state_root: Path           # that tenant's capped volume mountpoint

    def __post_init__(self):
        if not TENANT.fullmatch(self.tenant): raise ValueError('invalid tenant')
        if type(self.worker_uid) is not int or not 20000 <= self.worker_uid <= 65000: raise ValueError('invalid worker uid')
        if type(self.shared_gid) is not int or not 1 <= self.shared_gid <= 65000: raise ValueError('invalid gid')
        if not Path(self.state_root).is_absolute(): raise ValueError('absolute state root required')

    def dir(self, kind):
        return Path(self.state_root) / 'workers' / kind


def build_argv(profile, binding, run_id, *, model_key_file=None):
    """The complete, deterministic docker argv for one stage. Contains no customer text."""
    if not RUN_ID.fullmatch(run_id): raise BrokerRefused('invalid run id')
    if profile.needs_model_key != (model_key_file is not None): raise BrokerRefused('model key mismatch')
    name = f'aa-wk-{binding.tenant[3:11]}-{profile.name}-{run_id[:8]}'
    argv = ['docker', 'run', '--name', name, '--runtime', 'runsc',
            '--network', 'none' if profile.network == 'none' else 'bridge',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--memory', str(profile.memory_bytes), '--memory-swap', str(profile.memory_bytes),
            '--cpus', format(profile.cpus, '.2f'), '--pids-limit', str(profile.pids),
            '--user', f'{binding.worker_uid}:{binding.shared_gid}',
            '--tmpfs', f'/tmp:rw,nosuid,nodev,size={profile.tmpfs_bytes}',
            '--workdir', '/work', '--label', f'agentai.tenant={binding.tenant}',
            '--label', f'agentai.run={run_id}', '--stop-timeout', '5']
    if profile.project != 'none':
        argv += ['--mount', f'type=bind,src={binding.dir("project")},dst=/work/project,'
                 + ('readonly' if profile.project == 'ro' else 'readonly=false')]
    argv += ['--mount', f'type=bind,src={binding.dir("job")},dst=/work/job,readonly',
             '--mount', f'type=bind,src={binding.dir("out")},dst=/work/out']
    if model_key_file is not None:
        argv += ['--mount', f'type=bind,src={model_key_file},dst=/run/secrets/model-key,readonly']
    return argv + [profile.image, *profile.command]


class WorkerBroker:
    """Serialized runner. `run` is injectable so the envelope is testable without Docker."""

    def __init__(self, state_dir, catalog, *, run=None, admission=None, owner_uid=None):
        self.state = Path(state_dir)
        self.catalog = dict(catalog)
        self.run = run or self._subprocess
        self.admission = admission
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state.lstat().st_uid != self.owner_uid or self.state.lstat().st_mode & 0o077:
            raise PermissionError('broker state must be private and host-owned')
        self.lock = self.state / 'stage.lock'
        fd = os.open(self.lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600); os.close(fd)
        with self._db() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS stages(run TEXT PRIMARY KEY, tenant TEXT NOT NULL,
                stage TEXT NOT NULL, digest TEXT NOT NULL, status TEXT NOT NULL, exit_code INTEGER, output TEXT)''')

    def _db(self):
        con = sqlite3.connect(self.state / 'stages.sqlite3', timeout=2)
        con.execute('PRAGMA synchronous=FULL')
        return con

    @staticmethod
    def _subprocess(argv, timeout):
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
            return done.returncode, (done.stdout + done.stderr)[:OUTPUT_LIMIT].decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            return None, ''

    def prepare(self, binding, job):
        """Write the validated job spec read-only and make the three directories."""
        if type(job) is not dict: raise BrokerRefused('job must be an object')
        body = json.dumps(job, sort_keys=True, separators=(',', ':'))
        if len(body) > 65536: raise BrokerRefused('job too large')
        for kind in ('project', 'job', 'out'):
            path = binding.dir(kind); path.mkdir(mode=0o2770, parents=True, exist_ok=True)
            if os.geteuid() == 0:
                # Group-shared with the cell (gid), writable by the stage user via that group.
                os.chown(path, 0, binding.shared_gid); os.chmod(path, 0o2770)
        target = binding.dir('job') / 'job.json'
        target.write_text(body)

    def execute(self, binding, stage, run_id, *, model_key_file=None):
        profile = self.catalog.get(stage)
        if profile is None: raise BrokerRefused('unknown stage')
        argv = build_argv(profile, binding, run_id, model_key_file=model_key_file)
        digest = hashlib.sha256(json.dumps([binding.tenant, stage], sort_keys=True).encode()).hexdigest()
        fd = os.open(self.lock, os.O_RDWR | os.O_NOFOLLOW)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise BrokerBusy('another stage is running') from None
            with self._db() as con:
                old = con.execute('SELECT tenant,stage,digest,status,exit_code,output FROM stages WHERE run=?', (run_id,)).fetchone()
                if old:
                    if old[2] != digest: raise BrokerRefused('run payload changed')
                    if old[3] != 'completed': raise StageUncertain('stage needs reconciliation')
                    return {'exit_code': old[4], 'output': old[5], 'replayed': True}
                if con.execute("SELECT 1 FROM stages WHERE status!='completed'").fetchone():
                    raise StageUncertain('unresolved stage on host')
                if self.admission is not None: self.admission(profile)
                con.execute("INSERT INTO stages VALUES (?,?,?,?,'running',NULL,NULL)", (run_id, binding.tenant, stage, digest))
            name = argv[argv.index('--name') + 1]
            code, output = self.run(argv, profile.timeout_seconds)
            timed_out = code is None
            self._drain(name)
            if timed_out:
                with self._db() as con:
                    con.execute("UPDATE stages SET status='completed',exit_code=-9,output='timeout' WHERE run=?", (run_id,))
                return {'exit_code': -9, 'output': 'timeout', 'replayed': False}
            with self._db() as con:
                con.execute("UPDATE stages SET status='completed',exit_code=?,output=? WHERE run=?", (code, output, run_id))
            return {'exit_code': code, 'output': output, 'replayed': False}
        except BaseException:
            with self._db() as con:
                con.execute("UPDATE stages SET status='uncertain' WHERE run=? AND status='running'", (run_id,))
            raise
        finally:
            os.close(fd)

    def _drain(self, name):
        """Kill and remove the stage container, then prove it is gone."""
        self.run(['docker', 'rm', '-f', name], 30)
        code, out = self.run(['docker', 'ps', '-a', '-q', '--filter', f'name=^{name}$'], 30)
        if code != 0 or out.strip():
            raise StageUncertain('stage container could not be proven absent')

    def reconcile(self, run_id):
        """After a crash: kill any leftover container for the run and mark it settled."""
        with self._db() as con:
            row = con.execute('SELECT tenant,stage,status FROM stages WHERE run=?', (run_id,)).fetchone()
            if not row or row[2] == 'completed': return False
            self._drain(f'aa-wk-{row[0][3:11]}-{row[1]}-{run_id[:8]}')
            con.execute("UPDATE stages SET status='completed',exit_code=-1,output='reconciled after interruption' WHERE run=?", (run_id,))
            return True
