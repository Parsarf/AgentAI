"""Verified native Fleet CLI backend; refuses until custody records the installed CLI's behavior.

Observed installed-candidate reality (2026-10-04 probe): `fleet create` and
`fleet backup` emit JSON, `fleet start`/`stop`/`rm` emit plain text with an
exit code, and `fleet list --json` is the registry state source with
`cells[].state` in {created, running, exited}; a deleted tenant is absent.
This driver therefore proves every receipt through a bounded list follow-up
plus, for backup, the archive artifact itself, and for delete, registry
absence — never the command's own text. The create output carries the cell
Gateway token in plaintext on stdout: captured stdout stays in a private temp
file deleted with the process and nothing from it is parsed or persisted.
Missing or unverified custody refuses exactly like DisabledDriver, which is
why supervisor_main still ships DisabledDriver. These boundaries are not OS
isolation acceptance; Phase 15 stays NOT_RUN.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time

from agentai_platform.adapters import CapabilityUnavailable
from .fleet_plan import FleetPlanner
from .supervisor import OutcomeUncertain, SupervisorBusy
from .types import KINDS, RUNNABLE, Claim, Conflict, Receipt

# The registry read form was executed successfully against the installed
# candidate; cells[].state values and command behaviors were observed directly.
LIST_PROBE=('fleet','list','--json')
LIST_ENTRY={'tenant','state','port','image','created'}
ENV_KEY=re.compile(r'[A-Z_][A-Z0-9_]{0,63}')
SHA256=re.compile(r'[a-f0-9]{64}')
DESIRED={'create':'stopped','start':'running','stop':'stopped','backup':'stopped','delete':'absent'}


class FleetCustody:
    """Host-authored manifest: pinned binaries, exact env and the verified registry vocabulary."""

    def __init__(self,manifest):
        if type(manifest) is not dict or manifest.get('schema_version')!=2 or set(manifest)!={
                'schema_version','cli','env','cwd','timeout_seconds','output_limit_bytes',
                'headroom_reserve_bytes','list_states','verified'}:
            raise ValueError('unsupported custody manifest')
        cli=manifest['cli']
        if type(cli) is not dict or set(cli)!={'node','entry','node_sha256','entry_sha256'}:
            raise ValueError('invalid cli custody')
        self.node=self._binary(cli['node'],cli['node_sha256'])
        self.entry=self._binary(cli['entry'],cli['entry_sha256'])
        self.env=self._env(manifest['env'])
        self.cwd=self._cwd(manifest['cwd'])
        for name,bounds in (('timeout_seconds',(5,600)),('output_limit_bytes',(1024,1048576)),
                            ('headroom_reserve_bytes',(0,2**31))):
            value=manifest[name]
            if type(value) is not int or type(value) is bool or not bounds[0]<=value<=bounds[1]:
                raise ValueError(f'invalid custody bound: {name}')
        self.timeout,self.output_limit,self.reserve=(manifest[n] for n in
            ('timeout_seconds','output_limit_bytes','headroom_reserve_bytes'))
        states=manifest['list_states']
        if type(states) is not dict or set(states)!={'running','stopped'}:
            raise ValueError('invalid registry vocabulary')
        for names in states.values():
            if type(names) is not list or not names or len(names)>32:
                raise ValueError('invalid registry vocabulary')
            for name in names:
                if type(name) is not str or not 1<=len(name)<=64:
                    raise ValueError('invalid registry vocabulary')
        if set(states['running'])&set(states['stopped']):
            raise ValueError('ambiguous registry vocabulary')
        self.list_states=states
        verified=manifest['verified']
        if type(verified) is not list or not set(verified)<=set(KINDS) or 'upgrade' in verified or 'restore' in verified:
            raise ValueError('unsupported verified kind')
        self.verified=frozenset(verified)

    def _binary(self,path,digest):
        if type(path) is not str or type(digest) is not str or not SHA256.fullmatch(digest):
            raise ValueError('invalid binary custody')
        try:
            info=Path(path).lstat()
        except OSError:
            raise ValueError('custody binary missing') from None
        # lstat through a symlink reports the link; regular/nlink checks reject it.
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise ValueError('unsafe custody binary')
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:
            raise ValueError('custody binary digest mismatch')
        return Path(path)

    def _env(self,env):
        if type(env) is not dict or not 1<=len(env)<=16 or 'PATH' not in env:
            raise ValueError('invalid custody environment')
        clean={}
        for key,value in env.items():
            if type(key) is not str or not ENV_KEY.fullmatch(key):
                raise ValueError('invalid custody environment')
            if type(value) is not str or not value or len(value)>4096 or '\x00' in value or '\n' in value:
                raise ValueError('invalid custody environment')
            clean[key]=value
        return clean

    def _cwd(self,path):
        if type(path) is not str:
            raise ValueError('invalid custody working directory')
        try:
            info=Path(path).lstat()
        except OSError:
            raise ValueError('custody working directory missing') from None
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('unsafe custody working directory')
        return Path(path)

    def state_of(self,raw):
        """Map an observed registry state string to the canonical receipt state."""
        if raw in self.list_states['running']: return 'running'
        if raw in self.list_states['stopped']: return 'stopped'
        return None

    def verified_kind(self,kind):
        if type(kind) is not str or kind not in KINDS: raise Conflict('unsupported operation')
        if kind not in self.verified:
            raise CapabilityUnavailable(f'installed behavior for {kind} is not custody-verified')


class FleetCliDriver:
    """Executes fixed Fleet plans under the pinned candidate CLI. Never receives secrets."""

    def __init__(self,custody):
        self.custody=custody

    def check(self,kind):
        self.custody.verified_kind(kind)

    def _argv(self,binding,claim):
        # The planner owns every argument; the argv[0] bin name becomes the pinned pair.
        return [str(self.custody.node),str(self.custody.entry),
                *FleetPlanner({binding.account_id:binding}).command(claim)[1:]]

    def execute(self,binding,claim):
        if type(claim) is not Claim: raise Conflict('invalid claim')
        code,stdout=self._run(self._argv(binding,claim))
        if code!=0: raise OutcomeUncertain('native executor rejected')
        state=self._observed_state(binding)
        backup_ref=None
        if claim.kind=='delete':
            if state is not None:
                raise OutcomeUncertain('tenant still present after delete')
            return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                           'absent',True,True,fence=claim.fence)
        if state is None or state!=DESIRED[claim.kind]:
            raise OutcomeUncertain('registry state does not prove the operation')
        if claim.kind=='backup':
            self._verify_archive(binding,claim.operation_id)
            backup_ref=claim.operation_id
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       state,True,state!='running',backup_ref,fence=claim.fence)

    def reconcile(self,binding,claim):
        # Registry absence proves a non-effect only where absence is the claimed
        # terminal state; presence and other kinds stay uncertain instead of guessed.
        if claim.kind not in {'create','delete'}: return None
        try:
            state=self._observed_state(binding)
        except OutcomeUncertain:
            return None
        if state is not None: return None
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       'absent',claim.kind=='delete',True,fence=claim.fence)

    def _observed_state(self,binding):
        """Registry state for the binding tenant, or None once it is absent."""
        code,stdout=self._run([str(self.custody.node),str(self.custody.entry),*LIST_PROBE])
        if code!=0: raise OutcomeUncertain('native registry probe rejected')
        payload=self._decode(stdout)
        uncertain=OutcomeUncertain('native registry output does not match the verified schema')
        if type(payload) is not dict or set(payload)!={'cells'} or type(payload['cells']) is not list:
            raise uncertain
        for entry in payload['cells']:
            if type(entry) is not dict or set(entry)!=LIST_ENTRY:
                raise uncertain
            if type(entry['tenant']) is not str or type(entry['state']) is not str \
                    or len(entry['tenant'])>96 or len(entry['state'])>64 \
                    or type(entry['port']) is not int or type(entry['port']) is bool \
                    or type(entry['image']) is not str or len(entry['image'])>256 \
                    or type(entry['created']) is not str or len(entry['created'])>64:
                raise uncertain
            if entry['tenant']==binding.tenant_ref:
                state=self.custody.state_of(entry['state'])
                if state is None: raise uncertain
                return state
        return None

    def _run(self,argv):
        with tempfile.TemporaryDirectory(prefix='aa-fleet-') as scratch:
            out=Path(scratch)/'stdout.bin';err=Path(scratch)/'stderr.txt'
            with out.open('wb') as stdout,err.open('wb') as stderr:
                process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                    env=dict(self.custody.env),cwd=str(self.custody.cwd),start_new_session=True)
            try:
                process.wait(timeout=self.custody.timeout)
            except subprocess.TimeoutExpired:
                self._drain(process)
                raise OutcomeUncertain('native executor exceeded the custody time bound') from None
            if out.stat().st_size>self.custody.output_limit:
                raise OutcomeUncertain('native output exceeds the custody bound')
            return process.returncode,out.read_bytes()

    def _drain(self,process):
        # Whole-group kill plus a proven reaped group is the executor drain receipt.
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise OutcomeUncertain('native executor could not be reaped') from None
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try:
                os.killpg(process.pid,0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        raise OutcomeUncertain('native executor group survived the drain kill')

    def _decode(self,raw):
        def unique(items):
            value={}
            for key,item in items:
                if key in value: raise OutcomeUncertain('duplicate native output field')
                value[key]=item
            return value
        try:
            return json.loads(raw.decode('utf-8'),object_pairs_hook=unique)
        except (ValueError,UnicodeDecodeError):
            raise OutcomeUncertain('native output is not one JSON value') from None

    def _verify_archive(self,binding,operation_id):
        uncertain=OutcomeUncertain('native backup archive is not a bounded direct custody file')
        root=Path(binding.backup_root)
        try:
            if not stat.S_ISDIR(root.lstat().st_mode): raise uncertain
            info=(root/f'{operation_id}.tgz').lstat()
        except OSError:
            raise uncertain from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1: raise uncertain
        if not 1<=info.st_size<=binding.archive_limit_bytes: raise uncertain
        try:
            with (root/f'{operation_id}.tgz').open('rb') as handle: magic=handle.read(2)
        except OSError:
            raise uncertain from None
        if magic!=b'\x1f\x8b': raise uncertain


class HeadroomAdmission:
    """Independent host-side dispatch bound: runnable kinds need real RAM headroom.

    App-side capacity data never substitutes for this check; a stale or wrong
    app assessment cannot make the supervisor overcommit the host.
    """

    def __init__(self,reader,reserve_bytes):
        if type(reserve_bytes) is not int or type(reserve_bytes) is bool or reserve_bytes<0:
            raise ValueError('invalid headroom reserve')
        self.reader,self.reserve=reader,reserve_bytes

    def __call__(self,binding,kind):
        if kind not in RUNNABLE: return
        available=self.reader()
        if type(available) is not int or type(available) is bool or available<0:
            raise SupervisorBusy('host headroom unknown')
        if available<binding.memory_bytes+self.reserve:
            raise SupervisorBusy('host headroom exhausted')


def linux_mem_available():
    with open('/proc/meminfo','rb') as handle:
        for line in handle:
            if line.startswith(b'MemAvailable:'): return int(line.split()[1])*1024
    raise OSError('MemAvailable missing')
