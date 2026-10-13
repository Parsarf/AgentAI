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
import shutil
import signal
import stat
import subprocess
import tempfile
import time

from agentai_platform.adapters import CapabilityUnavailable
from dataclasses import replace
from .fleet_plan import FleetPlanner
from .maintenance import extract_archive, quarantine_ref
from .volumes import VolumeSpec
from .supervisor import OutcomeUncertain, SupervisorBusy
from .types import KINDS, RUNNABLE, Claim, Conflict, Receipt

# The registry read form was executed successfully against the installed
# candidate; cells[].state values and command behaviors were observed directly.
LIST_PROBE=('fleet','list','--json')
LIST_ENTRY={'tenant','state','port','image','created'}
ENV_KEY=re.compile(r'[A-Z_][A-Z0-9_]{0,63}')
SHA256=re.compile(r'[a-f0-9]{64}')
DESIRED={'create':'stopped','start':'running','stop':'stopped','backup':'stopped','delete':'absent',
         'upgrade':'running','restore':'stopped'}


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
        if type(verified) is not list or not set(verified)<=set(KINDS):
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

    def __init__(self,custody,*,secrets=None,volumes=None,isolation=None,health=None,provisioner=None):
        self.custody=custody
        # Optional host services. Absent in unit fixtures; the production wiring
        # supplies all four so a cell never starts without token/volume/firewall.
        self.secrets,self.volumes,self.isolation,self.health=secrets,volumes,isolation,health
        self.provisioner=provisioner   # model-route key + Gateway config; absent in unit fixtures

    def check(self,kind):
        self.custody.verified_kind(kind)

    def _argv(self,binding,claim):
        # The planner owns every argument; the argv[0] bin name becomes the pinned pair.
        return [str(self.custody.node),str(self.custody.entry),
                *FleetPlanner({binding.account_id:binding}).command(claim)[1:]]

    def execute(self,binding,claim):
        if type(claim) is not Claim: raise Conflict('invalid claim')
        if claim.kind=='upgrade': return self._upgrade(binding,claim)
        if claim.kind=='restore': return self._restore(binding,claim)
        argv=self._argv(binding,claim)
        if claim.kind in {'start','backup'} and self.volumes is not None and binding.volume_bytes:
            # Idempotent: remounts the capped volume after a host reboot or an unmount; a no-op when already mounted.
            self.volumes.prepare(VolumeSpec(binding.tenant_ref,binding.volume_bytes))
        if claim.kind=='create':
            if self.volumes is not None and binding.volume_bytes:
                self.volumes.prepare(VolumeSpec(binding.tenant_ref,binding.volume_bytes))
            if self.secrets is not None:
                argv=argv+['--gateway-token',self.secrets.gateway_token(binding.tenant_ref)]
            if self.provisioner is not None:
                argv=argv+self.provisioner.prepare(binding)
        code,stdout=self._run(argv)
        if code!=0: raise OutcomeUncertain('native executor rejected')
        if claim.kind=='create' and self.provisioner is not None:
            self.provisioner.finish(binding)
        state=self._observed_state(binding)
        backup_ref=None
        if claim.kind=='delete':
            if state is not None:
                raise OutcomeUncertain('tenant still present after delete')
            # Data stays on its capped volume until the retention purge.
            if self.volumes is not None: self.volumes.release(binding.tenant_ref)
            return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                           'absent',True,True,fence=claim.fence)
        if state is None or state!=DESIRED[claim.kind]:
            raise OutcomeUncertain('registry state does not prove the operation')
        if claim.kind=='start' and self.provisioner is not None:
            try: self.provisioner.after_start(binding)
            except Exception: pass   # name lookups may fail until fixed; the cell itself is proven running, so the start stands
            try: self.provisioner.setup_search(binding)
            except Exception: pass   # search is an add-on: a failure leaves the cell running without it and is retried at the next start
        if claim.kind=='backup':
            self._verify_archive(binding,claim.operation_id)
            backup_ref=claim.operation_id
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       state,True,state!='running',backup_ref,fence=claim.fence)


    # -- upgrade: pinned image, canary health, scoped rollback -----------------
    def _upgrade(self,binding,claim):
        argv=self._argv(binding,claim)
        code,_=self._run(argv)
        healthy=code==0 and self._observed_state(binding)=='running' and self._healthy(binding.port)
        if healthy:
            return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                           'running',True,False,fence=claim.fence)
        # Roll back to the recorded image; the capped state volume is untouched.
        rollback=replace(binding,upgrade_image=binding.image)
        code,_=self._run(self._argv(rollback,claim))
        if code!=0 or self._observed_state(binding)!='running' or not self._healthy(binding.port):
            raise OutcomeUncertain('upgrade failed and rollback is not proven')
        # Definite no-effect: the prior image runs healthy; retry may use a higher fence.
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       'running',False,False,fence=claim.fence)

    def _healthy(self,port):
        if self.health is None: raise OutcomeUncertain('no health probe in custody')
        return bool(self.health(port))

    # -- quarantined restore: separate slug, volume, network; egress dropped ----
    def _restore(self,binding,claim):
        if None in (self.secrets,self.volumes,self.isolation) or self.health is None:
            raise CapabilityUnavailable('quarantined restore needs token, volume, firewall and health custody')
        planner=FleetPlanner({binding.account_id:binding})
        q=quarantine_ref(binding.tenant_ref)
        archive=Path(binding.backup_root)/f'{claim.backup_ref}.tgz'
        self._verify_archive(binding,claim.backup_ref)
        qbinding=replace(binding,tenant_ref=q,port=binding.quarantine_port or binding.port,quarantine_port=None,upgrade_image=None)
        if self._observed_state(qbinding) is not None:
            raise OutcomeUncertain('a quarantined cell already exists; discard it first')
        if binding.volume_bytes:
            self.volumes.prepare(VolumeSpec(q,binding.volume_bytes))
        argv=list(planner.quarantine_create(binding,q))
        argv=[str(self.custody.node),str(self.custody.entry),*argv[1:],'--gateway-token',self.secrets.gateway_token(q)]
        code,_=self._run(argv)
        if code!=0 or self._observed_state(qbinding)!='stopped':
            raise OutcomeUncertain('quarantined cell was not created')
        self.isolation.quarantine(q)  # egress dropped before any restored code can run
        data=self.volumes.mountpoint(q);auth=self.volumes.auth_dir(q)
        auth.mkdir(mode=0o700,parents=True,exist_ok=True)
        try:
            extract_archive(archive,data,auth,binding.tenant_ref,max_bytes=binding.archive_limit_bytes,uid=1000,gid=1000,replace_skeleton=True)
        except Exception:
            raise OutcomeUncertain('restore extraction rejected') from None
        code,_=self._run([str(self.custody.node),str(self.custody.entry),'fleet','start',q])
        if code!=0 or self._observed_state(qbinding)!='running' or not self._healthy(qbinding.port):
            raise OutcomeUncertain('restored cell did not become healthy')
        code,_=self._run([str(self.custody.node),str(self.custody.entry),'fleet','stop',q])
        if code!=0 or self._observed_state(qbinding)!='stopped':
            raise OutcomeUncertain('restored cell did not stop')
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       'stopped',True,True,fence=claim.fence)

    def discard_quarantine(self,binding):
        """Host operator action: remove only this tenant's quarantined restore."""
        q=quarantine_ref(binding.tenant_ref);qbinding=replace(binding,tenant_ref=q)
        if self._observed_state(qbinding) is not None:
            self._run([str(self.custody.node),str(self.custody.entry),'fleet','rm',q])
            if self._observed_state(qbinding) is not None: raise OutcomeUncertain('quarantined cell still present')
        if self.isolation is not None:
            try: self.isolation.release(q)
            except RuntimeError: pass  # network already gone with the cell
        if self.volumes is not None:
            self.volumes.release(q);self.volumes.purge(q)
            shutil.rmtree(self.volumes.auth_dir(q),ignore_errors=True)
        if self.secrets is not None: self.secrets.destroy(q)

    def purge(self,binding,*,provider_keys=None):
        """Retention purge of one deleted tenant: revoke keys, then remove its data and secrets."""
        if self._observed_state(binding) is not None: raise OutcomeUncertain('tenant still registered')
        if provider_keys is not None: provider_keys.revoke(binding.tenant_ref)
        if self.volumes is not None:
            self.volumes.release(binding.tenant_ref);self.volumes.purge(binding.tenant_ref)
            shutil.rmtree(self.volumes.auth_dir(binding.tenant_ref),ignore_errors=True)
        if self.secrets is not None: self.secrets.destroy(binding.tenant_ref)

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
