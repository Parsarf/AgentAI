"""Verified native Fleet CLI backend; refuses until output schemas are custody-proven.

Executes only the fixed plans prepared by FleetPlanner for a host-enrolled
binding. Pinned binary digests, the exact invocation environment and the
observed native output schema per operation kind come from a host-authored
custody manifest; without a verified schema the driver refuses exactly like
DisabledDriver, which is why supervisor_main still ships DisabledDriver.
Executor drain means the whole process group is killed and proven reaped plus,
where the manifest proves it, a mapped native state field or the bounded
absence probe over the already-probed `fleet list --json` form. This backend
and its boundary tests are not OS isolation acceptance; Phase 15 stays NOT_RUN.
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
# candidate (empty registry). Effect-output schemas remain operator-verified.
LIST_PROBE=('fleet','list','--json')
ENV_KEY=re.compile(r'[A-Z_][A-Z0-9_]{0,63}')
FIELD=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
SHA256=re.compile(r'[a-f0-9]{64}')


class FleetCustody:
    """Host-authored manifest: pinned binaries, exact env and verified output schemas."""

    def __init__(self,manifest):
        if type(manifest) is not dict or manifest.get('schema_version')!=1 or set(manifest)!={
                'schema_version','cli','env','cwd','timeout_seconds','output_limit_bytes',
                'headroom_reserve_bytes','schemas'}:
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
        schemas=manifest['schemas']
        if type(schemas) is not dict or set(schemas)-{'create','start','stop','backup','delete'}:
            raise ValueError('unsupported native schema')
        self.schemas={kind:self._schema(kind,spec) for kind,spec in schemas.items()}

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

    def _schema(self,kind,spec):
        if type(spec) is not dict or set(spec)!={'fields','map','state_values'}:
            raise ValueError(f'invalid {kind} schema')
        fields=spec['fields']
        if type(fields) is not dict or not fields:
            raise ValueError(f'invalid {kind} fields')
        for name,kind_of in fields.items():
            if type(name) is not str or not FIELD.fullmatch(name) or kind_of not in {'str','int','bool'}:
                raise ValueError(f'invalid {kind} fields')
        mapping=spec['map']
        if type(mapping) is not dict or not {'state','applied'}<=set(mapping) \
                or set(mapping)-{'state','applied','quiesced'}:
            raise ValueError(f'invalid {kind} map')
        for role,name in mapping.items():
            if role=='quiesced' and name is True: continue
            if type(name) is not str or name not in fields:
                raise ValueError(f'invalid {kind} map')
            if role in {'applied','quiesced'} and fields[name]!='bool':
                raise ValueError(f'invalid {kind} map')
        values=spec['state_values']
        if type(values) is not dict or set(values)!={'running','stopped','absent'}:
            raise ValueError(f'invalid {kind} states')
        for names in values.values():
            if type(names) is not list or len(names)>32:
                raise ValueError(f'invalid {kind} states')
            for name in names:
                if type(name) is not str or not 1<=len(name)<=64:
                    raise ValueError(f'invalid {kind} states')
        return {'fields':fields,'map':mapping,'state_values':values}

    def receipt_fields(self,kind,payload):
        """Map a native output object through the verified schema, or stay uncertain."""
        schema=self.schemas.get(kind)
        if schema is None:
            raise CapabilityUnavailable(f'native output schema for {kind} is not verified')
        uncertain=OutcomeUncertain(f'native output does not match the verified {kind} schema')
        if type(payload) is not dict or set(payload)!=set(schema['fields']):
            raise uncertain
        for name,kind_of in schema['fields'].items():
            value=payload[name]
            if kind_of=='str' and (type(value) is not str or len(value)>256): raise uncertain
            if kind_of=='int' and (type(value) is not int or type(value) is bool
                                   or not -(2**63)<=value<2**63): raise uncertain
            if kind_of=='bool' and type(value) is not bool: raise uncertain
        mapping=schema['map']
        state=payload[mapping['state']]
        canonical=[target for target,names in schema['state_values'].items() if state in names]
        if not canonical: raise uncertain
        applied=payload[mapping['applied']]
        quiesced=True if mapping.get('quiesced') is True else payload[mapping['quiesced']]
        return canonical[0],applied,quiesced


class FleetCliDriver:
    """Executes fixed Fleet plans under the pinned candidate CLI. Never receives secrets."""

    def __init__(self,custody):
        self.custody=custody

    def check(self,kind):
        if type(kind) is not str or kind not in KINDS: raise Conflict('unsupported operation')
        if kind not in self.custody.schemas:
            raise CapabilityUnavailable(f'native output schema for {kind} is not verified')

    def _argv(self,binding,claim):
        # The planner owns every argument; the argv[0] bin name becomes the pinned pair.
        return [str(self.custody.node),str(self.custody.entry),
                *FleetPlanner({binding.account_id:binding}).command(claim)[1:]]

    def execute(self,binding,claim):
        if type(claim) is not Claim: raise Conflict('invalid claim')
        code,stdout=self._run(self._argv(binding,claim))
        if code!=0: raise OutcomeUncertain('native executor rejected')
        state,applied,quiesced=self.custody.receipt_fields(claim.kind,self._decode(stdout))
        backup_ref=None
        if claim.kind=='backup':
            self._verify_archive(binding,claim.operation_id)
            backup_ref=claim.operation_id
        if claim.kind=='delete' and applied: self._require_absent(binding)
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       state,applied,quiesced,backup_ref,fence=claim.fence)

    def reconcile(self,binding,claim):
        # Registry absence proves a non-effect only where absence is the claimed
        # terminal state; presence and other kinds stay uncertain instead of guessed.
        if claim.kind not in {'create','delete'}: return None
        try:
            self._require_absent(binding)
        except OutcomeUncertain:
            return None
        return Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
                       'absent',claim.kind=='delete',True,fence=claim.fence)

    def _run(self,argv):
        with tempfile.TemporaryDirectory(prefix='aa-fleet-') as scratch:
            out=Path(scratch)/'stdout.json';err=Path(scratch)/'stderr.txt'
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

    def _require_absent(self,binding):
        code,stdout=self._run([str(self.custody.node),str(self.custody.entry),*LIST_PROBE])
        if code!=0: raise OutcomeUncertain('native registry probe rejected')
        if binding.tenant_ref.encode() in stdout:
            raise OutcomeUncertain('tenant still present in the native registry')


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
