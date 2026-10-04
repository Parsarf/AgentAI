"""Host custody and serialized dispatch; contains no shell or agent loop.

This database is separate from the app database and inaccessible to its user.
Only a host operator enrolls bindings. The authenticated controller can submit
fixed claims against those bindings. A native backend must prove every receipt;
this module does not turn a container status or fixture into native acceptance.
"""
from contextlib import contextmanager
from dataclasses import asdict, fields
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from .fleet_plan import FleetBinding
from .types import KINDS, RUNNABLE, Claim, Conflict, Receipt


class SupervisorBusy(Exception): pass
class OutcomeUncertain(Exception): pass


def decode_claim(payload):
    if type(payload) is not dict or set(payload)!={f.name for f in fields(Claim)}:
        raise Conflict('invalid claim schema')
    for name in ('account_id','owner','target_profile'):
        value=payload[name]
        if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value):
            raise Conflict('invalid claim identity')
    for name in ('deployment_id','operation_id'):
        if type(payload[name]) is not str or not re.fullmatch(r'[a-f0-9]{32}',payload[name]):
            raise Conflict('invalid operation identity')
    if type(payload['tenant_ref']) is not str or not re.fullmatch(r'aa-[a-f0-9]{32}',payload['tenant_ref']):
        raise Conflict('invalid tenant identity')
    if type(payload['kind']) is not str or payload['kind'] not in KINDS:
        raise Conflict('invalid operation kind')
    for name in ('generation','fence'):
        if type(payload[name]) is not int or not 1<=payload[name]<=2**63-1:
            raise Conflict('invalid operation revision')
    backup=payload['backup_ref']
    if (payload['kind']=='restore')!=(backup is not None):
        raise Conflict('invalid backup reference')
    if backup is not None and (type(backup) is not str or not re.fullmatch(r'[a-f0-9]{32}',backup)):
        raise Conflict('invalid backup reference')
    return Claim(**payload)


def validate_receipt(claim, receipt):
    if type(receipt) is not Receipt:
        raise Conflict('invalid receipt schema')
    if (receipt.account_id,receipt.deployment_id,receipt.operation_id,receipt.generation,receipt.fence)!=(
            claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,claim.fence):
        raise Conflict('receipt binding mismatch')
    if type(receipt.generation) is not int or type(receipt.fence) is not int:
        raise Conflict('invalid receipt revision')
    if type(receipt.applied) is not bool or type(receipt.quiesced) is not bool:
        raise Conflict('invalid receipt flags')
    desired={'create':'stopped','start':'running','stop':'stopped','backup':'stopped',
             'restore':'stopped','upgrade':'running','delete':'absent'}[claim.kind]
    if receipt.state not in {'absent','stopped','running'} or (receipt.applied and receipt.state!=desired):
        raise Conflict('invalid receipt state')
    if receipt.state!='running' and not receipt.quiesced:
        raise Conflict('runtime not quiesced')
    expected=claim.operation_id if claim.kind=='backup' and receipt.applied else None
    if receipt.backup_ref!=expected: raise Conflict('invalid backup receipt')


class HostSupervisor:
    def __init__(self, root, backend, *, owner_uid=None, admission=None):
        self.root=Path(root)
        self.owner_uid=os.geteuid() if owner_uid is None else owner_uid
        self.backend=backend
        # Independent host-side dispatch bound (e.g. HeadroomAdmission); None only
        # in disposable environments. Rejections are SupervisorBusy, never intents.
        self.admission=admission
        self.root.mkdir(mode=0o700,parents=False,exist_ok=True)
        self._private(self.root,directory=True)
        self.db=self.root/'custody.sqlite3'
        self.lock=self.root/'effects.lock'
        # O_NOFOLLOW and exclusive creation prevent existing links from being
        # accepted as private custody. Production passes owner_uid=0.
        for path in (self.db,self.lock):
            fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            os.close(fd);self._private(path)
        with self.serialized(),self.connect() as con:
            version=con.execute('PRAGMA user_version').fetchone()[0]
            if version not in {0,1}: raise Conflict('unsupported custody schema')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS bindings(
                  account TEXT PRIMARY KEY, deployment TEXT UNIQUE NOT NULL,
                  tenant TEXT UNIQUE NOT NULL, port INTEGER UNIQUE NOT NULL,
                  spec TEXT NOT NULL, generation INTEGER NOT NULL,
                  state TEXT NOT NULL DEFAULT 'absent');
                CREATE TABLE IF NOT EXISTS journal(
                  operation TEXT PRIMARY KEY, account TEXT NOT NULL,
                  digest TEXT NOT NULL, claim TEXT NOT NULL, fence INTEGER NOT NULL,
                  status TEXT NOT NULL, receipt TEXT,
                  FOREIGN KEY(account) REFERENCES bindings(account));
                PRAGMA user_version=1;
            ''')

    def _private(self,path,*,directory=False):
        s=path.lstat()
        if s.st_uid!=self.owner_uid or stat.S_IMODE(s.st_mode)&0o077:
            raise PermissionError('custody must be private and host-owned')
        if (not stat.S_ISDIR(s.st_mode) if directory else not stat.S_ISREG(s.st_mode) or s.st_nlink!=1):
            raise PermissionError('unsafe custody path')

    @contextmanager
    def serialized(self):
        self._private(self.lock)
        fd=os.open(self.lock,os.O_RDWR|os.O_NOFOLLOW)
        try:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise SupervisorBusy('supervisor busy') from None
            yield
        finally:
            os.close(fd)

    @contextmanager
    def connect(self):
        self._private(self.db)
        con=sqlite3.connect(self.db,timeout=2)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON');con.execute('PRAGMA synchronous=FULL')
        try:
            with con: yield con
        finally: con.close()

    def enroll(self,binding,*,generation=1):
        """Host operator only. Not exposed by the socket protocol; never upserts."""
        if type(binding) is not FleetBinding or type(generation) is not int or generation<1:
            raise ValueError('invalid enrollment')
        # Validate the same wire identity constraints before storing custody.
        decode_claim(dict(account_id=binding.account_id,deployment_id=binding.deployment_id,
            tenant_ref=binding.tenant_ref,operation_id='0'*32,kind='create',generation=generation,
            target_profile=binding.profile_revision,backup_ref=None,fence=1,owner='host'))
        spec=asdict(binding);spec['backup_root']=str(binding.backup_root)
        with self.serialized(),self.connect() as con:
            con.execute('INSERT INTO bindings(account,deployment,tenant,port,spec,generation) VALUES (?,?,?,?,?,?)',
                (binding.account_id,binding.deployment_id,binding.tenant_ref,binding.port,
                 json.dumps(spec,sort_keys=True),generation))

    def check(self,kind):
        if type(kind) is not str or kind not in KINDS: raise Conflict('unsupported operation')
        self.backend.check(kind)

    def _binding(self,con,claim):
        row=con.execute('SELECT * FROM bindings WHERE account=?',(claim.account_id,)).fetchone()
        if not row or (row['deployment'],row['tenant'])!=(claim.deployment_id,claim.tenant_ref):
            raise Conflict('host binding mismatch')
        spec=json.loads(row['spec']);spec['backup_root']=Path(spec['backup_root'])
        binding=FleetBinding(**spec)
        if binding.profile_revision!=claim.target_profile:
            raise Conflict('host profile mismatch')
        return row,binding

    def _hash(self,claim):
        body=asdict(claim)
        # A definitively rejected, drained attempt may retry at a higher fence.
        # The effect's payload stays immutable; owner/fence identify an attempt.
        body.pop('fence');body.pop('owner')
        return hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()

    def execute(self,claim):
        claim=decode_claim(asdict(claim));self.check(claim.kind)
        with self.serialized():
            with self.connect() as con:
                bound,binding=self._binding(con,claim)
                old=con.execute('SELECT * FROM journal WHERE operation=?',(claim.operation_id,)).fetchone()
                if old:
                    if old['account']!=claim.account_id or old['digest']!=self._hash(claim):
                        raise Conflict('operation payload changed')
                    if old['status']!='completed': raise OutcomeUncertain('reconciliation required')
                    prior=Receipt(**json.loads(old['receipt']))
                    old_claim=Claim(**json.loads(old['claim']))
                    if claim==old_claim: return prior
                    if prior.applied or not prior.quiesced or claim.fence<=old['fence']:
                        raise Conflict('attempt is not safely retryable')
                if claim.generation!=bound['generation']:
                    raise Conflict('stale host revision')
                if con.execute("SELECT 1 FROM journal WHERE status!='completed'").fetchone():
                    raise OutcomeUncertain('global unresolved effect')
                if con.execute("SELECT 1 FROM bindings WHERE state='running' AND account!=?",(claim.account_id,)).fetchone():
                    raise SupervisorBusy('global active cell')
                if self.admission is not None and claim.kind in RUNNABLE:
                    self.admission(binding,claim.kind)
                allowed={'create':{'absent'},'start':{'stopped'},'stop':{'running','stopped'},
                         'backup':{'stopped'},'restore':{'stopped'},'upgrade':{'running','stopped'},
                         'delete':{'absent','stopped'}}[claim.kind]
                if bound['state'] not in allowed: raise Conflict('host state requires reconciliation')
                if claim.kind=='upgrade':
                    backups=con.execute("SELECT claim,receipt FROM journal WHERE account=? AND status='completed'",(claim.account_id,)).fetchall()
                    if not any(json.loads(b['claim'])['kind']=='backup' and
                               json.loads(b['claim'])['generation']==claim.generation and
                               json.loads(b['receipt'])['applied'] for b in backups):
                        raise Conflict('current host backup required')
                if claim.kind=='restore':
                    backup=con.execute('SELECT claim,receipt FROM journal WHERE operation=? AND account=? AND status=?',
                        (claim.backup_ref,claim.account_id,'completed')).fetchone()
                    if not backup: raise Conflict('backup not in host custody')
                    source=Claim(**json.loads(backup['claim']));saved=Receipt(**json.loads(backup['receipt']))
                    if source.kind!='backup' or not saved.applied or source.generation!=claim.generation:
                        raise Conflict('backup revision mismatch')
                con.execute('''INSERT INTO journal VALUES (?,?,?,?,?,? ,NULL)
                    ON CONFLICT(operation) DO UPDATE SET claim=excluded.claim,fence=excluded.fence,
                    status=excluded.status,receipt=NULL''',
                    (claim.operation_id,claim.account_id,self._hash(claim),json.dumps(asdict(claim)),claim.fence,'running'))
            # Committed intent precedes effects. Holding the process lock prevents
            # another executor from dispatching while this one is still alive.
            try:
                receipt=self.backend.execute(binding,claim)
                validate_receipt(claim,receipt)
                self._complete(claim,receipt)
                return receipt
            except Exception:
                with self.connect() as con:
                    con.execute("UPDATE journal SET status='uncertain' WHERE operation=?",(claim.operation_id,))
                raise

    def _complete(self,claim,receipt):
        with self.connect() as con:
            con.execute("UPDATE journal SET status='completed',receipt=? WHERE operation=? AND fence=?",
                (json.dumps(asdict(receipt)),claim.operation_id,claim.fence))
            generation=claim.generation+int(receipt.applied and claim.kind in {'restore','upgrade'})
            con.execute('UPDATE bindings SET state=?,generation=? WHERE account=?',
                (receipt.state,generation,claim.account_id))

    def reconcile(self,claim):
        claim=decode_claim(asdict(claim))
        with self.serialized():
            with self.connect() as con:
                _,binding=self._binding(con,claim)
                row=con.execute('SELECT * FROM journal WHERE operation=?',(claim.operation_id,)).fetchone()
                if not row: return None # Never dispatch from reconciliation.
                if Claim(**json.loads(row['claim']))!=claim: raise Conflict('reconcile attempt mismatch')
                if row['status']=='completed': return Receipt(**json.loads(row['receipt']))
            # A crash-left running intent is uncertain, regardless of lease age.
            # Backend must prove old work is drained; observation alone is insufficient.
            receipt=self.backend.reconcile(binding,claim)
            if receipt is None: return None
            validate_receipt(claim,receipt);self._complete(claim,receipt)
            return receipt
