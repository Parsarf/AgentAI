"""Account-bound metadata coordination. Runtime effects occur outside DB transactions.

The application can queue only fixed operations. A privileged supervisor must use
its own host-owned binding registry; this app database alone is not root authority.
Expired/unknown work is reconciled, never blindly dispatched a second time.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import re
import time
import uuid
from agentai_platform.security import NotFound, Principal
from agentai_platform.store import Store
from agentai_platform.capacity import CapacityResult
from .types import KINDS, Claim, Receipt, Conflict

IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('invalid identifier')
    return value

class Coordinator:
    def __init__(self, store: Store, *, profiles=frozenset({'trial-unmeasured-v1'}), clock=time.time):
        self.store, self.profiles, self.clock = store, frozenset(profiles), clock
        if not self.profiles: raise ValueError('profiles required')
        for profile in self.profiles: identifier(profile)

    @contextmanager
    def transaction(self):
        if hasattr(self.store, 'transaction'):
            with self.store.transaction() as con: yield con
            return
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                yield con
                con.execute('COMMIT')
            except Exception:
                con.execute('ROLLBACK')
                raise

    def _account(self, con, account, kind):
        row = con.execute('SELECT status FROM accounts WHERE id=?', (account,)).fetchone()
        if not row or row['status']=='deleted': raise NotFound()
        if kind not in {'stop','backup','delete'} and row['status']!='active': raise NotFound()

    def _operator(self, con, principal, kind):
        if principal.role != 'operator': raise NotFound()
        # MFA/session checks are done by the HTTP boundary. Recheck grant/account
        # inside the write transaction to cover revocation and expiry races.
        granted = con.execute("""SELECT 1 FROM accounts_operatorgrant g
            JOIN accounts_identity i ON i.user_id=g.user_id
            JOIN auth_user u ON u.id=i.user_id
            WHERE g.user_id=? AND g.account_id=? AND g.action=?
            AND julianday(g.expires_at)>julianday(?,'unixepoch')
            AND i.role='operator' AND i.verified=1 AND u.is_active=1""",
            (principal.actor_id, principal.account_id, 'lifecycle_'+kind, self.clock())).fetchone()
        if not granted: raise NotFound()
        self._account(con, principal.account_id, kind)

    def _audit(self, con, account, actor, obj, action, outcome):
        con.execute('''INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id)
            VALUES (?,?,?,?,?,?,?)''', (account,uuid.uuid4().hex,str(actor),obj,'lifecycle.'+action,outcome,uuid.uuid4().hex))

    def request(self, principal: Principal, *, kind, key, generation=None,
                target_profile='trial-unmeasured-v1', backup_ref=None):
        identifier(key)
        if kind not in KINDS or target_profile not in self.profiles: raise ValueError('unsupported request')
        if generation is not None and (type(generation) is not int or generation<1): raise ValueError('invalid generation')
        if kind=='create' and generation is not None: raise ValueError('create has no prior generation')
        if kind!='create' and generation is None: raise ValueError('generation required')
        if (kind=='restore') != (backup_ref is not None): raise ValueError('restore requires a backup reference')
        if backup_ref is not None: identifier(backup_ref)
        account = principal.account_id
        # No customer image, path, token, address, shell, native name or environment.
        body = json.dumps({'kind':kind,'generation':generation,'profile':target_profile,'backup':backup_ref},sort_keys=True,separators=(',',':'))
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.transaction() as con:
            self._operator(con, principal, kind)
            existing = con.execute('SELECT * FROM operations WHERE account_id=? AND idempotency_key=?',(account,key)).fetchone()
            if existing:
                if existing['request_hash']!=digest: raise Conflict('idempotency payload changed')
                return self._public(con, account, existing['id'])
            cell = con.execute('''SELECT c.*,d.generation FROM lifecycle_cells c JOIN deployments d
                ON d.account_id=c.account_id AND d.id=c.deployment_id WHERE c.account_id=?''',(account,)).fetchone()
            if kind=='create':
                if cell: raise Conflict('account already bound')
                if con.execute("SELECT count(*) FROM lifecycle_cells c JOIN deployments d ON d.account_id=c.account_id AND d.id=c.deployment_id WHERE d.state!='deleted'").fetchone()[0]>=2:
                    raise Conflict('trial account capacity reached')
                deployment = uuid.uuid4().hex
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'pending')",(account,deployment))
                con.execute('INSERT INTO lifecycle_cells(account_id,deployment_id,tenant_ref,profile_revision) VALUES (?,?,?,?)',
                            (account,deployment,'aa-'+uuid.uuid4().hex,target_profile))
                current_generation=1
            else:
                if not cell: raise NotFound()
                deployment=cell['deployment_id'];current_generation=cell['generation']
                if current_generation!=generation: raise Conflict('stale generation')
                if con.execute("SELECT 1 FROM operations WHERE account_id=? AND state IN ('pending','running','uncertain')",(account,)).fetchone():
                    raise Conflict('account operation unresolved')
                if kind=='restore':
                    backup=con.execute('SELECT profile_revision FROM lifecycle_backups WHERE account_id=? AND id=?',(account,backup_ref)).fetchone()
                    if not backup: raise NotFound()
                    if backup[0]!=target_profile: raise Conflict('restore profile mismatch')
                if kind=='upgrade' and not con.execute('SELECT 1 FROM lifecycle_backups WHERE account_id=? AND generation=?',(account,current_generation)).fetchone():
                    raise Conflict('upgrade requires current-generation backup')
                if kind not in {'upgrade','restore'} and target_profile!=cell['profile_revision']:
                    raise Conflict('profile revision changed')
            operation = uuid.uuid4().hex
            con.execute('''INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation)
                VALUES (?,?,?,?,'pending',?,?,?)''',(account,operation,deployment,kind,key,digest,current_generation))
            con.execute('''INSERT INTO lifecycle_details(account_id,operation_id,target_profile,backup_ref,updated_at)
                VALUES (?,?,?,?,?)''',(account,operation,target_profile,backup_ref,int(self.clock())))
            self._audit(con,account,principal.actor_id,operation,kind,'pending')
            return self._public(con,account,operation)

    def _public(self, con, account, operation):
        row=con.execute('''SELECT o.id,o.kind,o.state,o.generation,d.attempts,d.error_code
            FROM operations o JOIN lifecycle_details d ON d.account_id=o.account_id AND d.operation_id=o.id
            WHERE o.account_id=? AND o.id=?''',(account,operation)).fetchone()
        if not row: raise NotFound()
        return dict(row)

    def get(self, principal, operation=None):
        with self.store.connect() as con:
            self.store._authorize(con,principal)
            if operation: return self._public(con,principal.account_id,operation)
            rows=con.execute('''SELECT o.id FROM operations o JOIN lifecycle_details d
                ON d.account_id=o.account_id AND d.operation_id=o.id
                WHERE o.account_id=? ORDER BY o.created_at,o.id LIMIT 100''',(principal.account_id,)).fetchall()
            return [self._public(con,principal.account_id,r['id']) for r in rows]

    def claim(self, account, operation, *, owner, capacity: CapacityResult, lease_seconds=60):
        # Capacity must be a fresh trusted supervisor assessment, not app/API data.
        identifier(owner)
        if type(lease_seconds) is not int or not 1<=lease_seconds<=120: raise ValueError('invalid lease')
        with self.transaction() as con:
            row=self._row(con,account,operation)
            if row['state']=='running' and row['lease_until']<=self.clock():
                self._uncertain(con,row,'lease_expired')
                return None
            if row['state']!='pending': return None
            self._account(con,account,row['kind'])
            cell=con.execute('SELECT * FROM lifecycle_cells WHERE account_id=?',(account,)).fetchone()
            deploy=con.execute('SELECT generation,state FROM deployments WHERE account_id=? AND id=?',(account,row['deployment_id'])).fetchone()
            if deploy['generation']!=row['generation'] or deploy['state']=='deleted': raise Conflict('stale deployment')
            other=con.execute("SELECT 1 FROM operations WHERE account_id=? AND id!=? AND state IN ('running','uncertain')",(account,operation)).fetchone()
            if other: raise Conflict('account operation unresolved')
            state=cell['observed_state'];kind=row['kind']
            if kind in {'stop','upgrade','restore','backup','delete'} and con.execute(
                "SELECT 1 FROM tasks WHERE account_id=? AND state IN ('running','waiting_for_approval','paused')",(account,)).fetchone():
                raise Conflict('task must drain before maintenance')
            allowed={'create':{'absent'},'start':{'stopped'},'stop':{'running','stopped'},
                     'backup':{'stopped'},'restore':{'stopped'},'upgrade':{'stopped','running'},'delete':{'stopped','absent'}}
            if state not in allowed[kind]: raise Conflict('operation requires a different observed state')
            # Even stopped maintenance/create need measured storage/isolation/profile
            # admission. Do not turn missing runtime proof into an unrestricted call.
            if capacity.admitted_slots<1 or capacity.blockers:
                con.execute("UPDATE lifecycle_details SET error_code='capacity_wait' WHERE account_id=? AND operation_id=?",(account,operation))
                return None
            task_slot=con.execute('SELECT account_id FROM request_slot WHERE id=1').fetchone()
            if task_slot and task_slot[0]!=account:
                con.execute("UPDATE lifecycle_details SET error_code='capacity_wait' WHERE account_id=? AND operation_id=?",(account,operation))
                return None
            slot=con.execute('SELECT * FROM lifecycle_slot WHERE id=1').fetchone()
            if slot and slot['account_id']!=account:
                con.execute("UPDATE lifecycle_details SET error_code='capacity_wait' WHERE account_id=? AND operation_id=?",(account,operation))
                return None
            if not slot:
                con.execute("INSERT INTO lifecycle_slot VALUES (1,?,?,?,'reserved')",(account,row['deployment_id'],operation))
            if row['attempts']>=3: raise Conflict('retry limit reached')
            fence=row['fence']+1
            con.execute("UPDATE operations SET state='running' WHERE account_id=? AND id=?",(account,operation))
            con.execute('''UPDATE lifecycle_details SET attempts=attempts+1,fence=?,lease_owner=?,lease_until=?,
                retry_safe=0,error_code=NULL,updated_at=? WHERE account_id=? AND operation_id=?''',
                (fence,owner,int(self.clock())+lease_seconds,int(self.clock()),account,operation))
            self._audit(con,account,'supervisor',operation,kind,'pending')
            return Claim(account,row['deployment_id'],cell['tenant_ref'],operation,kind,row['generation'],row['target_profile'],row['backup_ref'],fence,owner)

    def _row(self, con, account, operation):
        row=con.execute('''SELECT o.*,d.target_profile,d.backup_ref,d.attempts,d.fence,d.lease_owner,d.lease_until,d.retry_safe
            FROM operations o JOIN lifecycle_details d ON d.account_id=o.account_id AND d.operation_id=o.id
            WHERE o.account_id=? AND o.id=?''',(account,operation)).fetchone()
        if not row: raise NotFound()
        return row

    def _uncertain(self, con, row, code):
        con.execute("UPDATE operations SET state='uncertain' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
        con.execute('''UPDATE lifecycle_details SET error_code=?,retry_safe=0,updated_at=?
            WHERE account_id=? AND operation_id=?''',(code,int(self.clock()),row['account_id'],row['id']))
        con.execute("UPDATE lifecycle_cells SET observed_state='unknown' WHERE account_id=?",(row['account_id'],))
        con.execute("UPDATE lifecycle_slot SET state='uncertain' WHERE account_id=?",(row['account_id'],))
        self._audit(con,row['account_id'],'supervisor',row['id'],row['kind'],'uncertain')

    def uncertain(self, claim):
        with self.transaction() as con:
            row=self._row(con,claim.account_id,claim.operation_id)
            self._fence(row,claim)
            self._uncertain(con,row,'runtime_outcome_unknown')

    def _fence(self, row, claim):
        if (row['deployment_id'],row['generation'],row['kind'],row['target_profile'],row['backup_ref'])!=(claim.deployment_id,claim.generation,claim.kind,claim.target_profile,claim.backup_ref):
            raise Conflict('claim binding changed')
        if row['fence']!=claim.fence or row['lease_owner']!=claim.owner or row['state'] not in {'running','uncertain'}:
            raise Conflict('worker fenced')

    def finish(self, claim, receipt, *, reconciled=False):
        # A runtime receipt is a strong boundary, including target binding and
        # proof no delayed work can still run when a slot is released.
        if (receipt.account_id,receipt.deployment_id,receipt.operation_id,receipt.generation)!=(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation):
            raise Conflict('receipt binding mismatch')
        if type(receipt.fence) is not int or receipt.fence!=claim.fence:
            raise Conflict('receipt fence mismatch')
        if receipt.state not in {'absent','stopped','running'} or type(receipt.applied) is not bool or type(receipt.quiesced) is not bool:
            raise Conflict('invalid receipt')
        desired={'create':'stopped','start':'running','stop':'stopped','upgrade':'running','backup':'stopped','restore':'stopped','delete':'absent'}[claim.kind]
        if receipt.applied and receipt.state!=desired: raise Conflict('receipt does not prove operation')
        if receipt.state!='running' and not receipt.quiesced: raise Conflict('runtime not drained')
        if claim.kind=='backup' and receipt.applied and receipt.backup_ref!=claim.operation_id:
            raise Conflict('backup receipt mismatch')
        if receipt.backup_ref is not None and claim.kind!='backup': raise Conflict('unexpected backup receipt')
        with self.transaction() as con:
            row=self._row(con,claim.account_id,claim.operation_id)
            self._fence(row,claim)
            if not reconciled and (row['state']!='running' or row['lease_until']<=self.clock()):
                self._uncertain(con,row,'lease_expired')
                return False
            if reconciled and row['state']!='uncertain': raise Conflict('reconciliation not required')
            account,operation=claim.account_id,claim.operation_id
            result='completed' if receipt.applied else 'failed'
            generation=claim.generation+(1 if receipt.applied and claim.kind in {'upgrade','restore'} else 0)
            profile=claim.target_profile if receipt.applied else con.execute('SELECT profile_revision FROM lifecycle_cells WHERE account_id=?',(account,)).fetchone()[0]
            con.execute('UPDATE lifecycle_cells SET observed_state=?,profile_revision=? WHERE account_id=?',(receipt.state,profile,account))
            deployment_state={'running':'ready','stopped':'stopped','absent':'deleted' if receipt.applied and claim.kind=='delete' else 'failed'}[receipt.state]
            con.execute('UPDATE deployments SET state=?,generation=? WHERE account_id=? AND id=?',(deployment_state,generation,account,claim.deployment_id))
            con.execute('UPDATE operations SET state=? WHERE account_id=? AND id=?',(result,account,operation))
            # A definitive non-effect may be retried only if the driver proves
            # old work is quiesced. A failed-but-running result retains the slot.
            con.execute('''UPDATE lifecycle_details SET retry_safe=?,error_code=?,updated_at=?
                WHERE account_id=? AND operation_id=?''',
                (int(not receipt.applied and receipt.quiesced),'runtime_rejected' if not receipt.applied else None,int(self.clock()),account,operation))
            if receipt.state=='running':
                slot=con.execute('SELECT account_id FROM lifecycle_slot WHERE id=1').fetchone()
                if not slot or slot[0]!=account: raise Conflict('missing execution reservation')
                con.execute("UPDATE lifecycle_slot SET state='active',operation_id=? WHERE account_id=?",(operation,account))
            else:
                con.execute('DELETE FROM lifecycle_slot WHERE account_id=?',(account,))
            if claim.kind=='backup' and receipt.applied:
                con.execute('INSERT INTO lifecycle_backups VALUES (?,?,?,?,?)',(account,receipt.backup_ref,operation,generation,profile))
            self._audit(con,account,'supervisor',operation,claim.kind,result)
            return True

    def retry(self, principal, operation):
        with self.transaction() as con:
            row=self._row(con,principal.account_id,operation)
            self._operator(con,principal,row['kind'])
            if row['state']!='failed' or not row['retry_safe'] or row['attempts']>=3: raise Conflict('retry not safe')
            self._audit(con,principal.account_id,principal.actor_id,operation,'retry','pending')
            con.execute("UPDATE operations SET state='pending' WHERE account_id=? AND id=?",(principal.account_id,operation))
            return self._public(con,principal.account_id,operation)

    def run(self, driver, account, operation, *, capacity, owner='worker'):
        # Gate before acquiring a lease. Disabled native runtime produces no effect.
        with self.store.connect() as con: row=self._row(con,account,operation)
        driver.check(row['kind'])
        claim=self.claim(account,operation,owner=owner,capacity=capacity)
        if not claim: return False
        try:
            receipt=driver.execute(claim)
            return self.finish(claim,receipt)
        except Exception:
            self.uncertain(claim)
            raise

    def reconcile(self, driver, account, operation):
        with self.transaction() as con:
            row=self._row(con,account,operation)
            if row['state']=='running' and row['lease_until']<=self.clock(): self._uncertain(con,row,'lease_expired')
            elif row['state']!='uncertain': raise Conflict('operation not uncertain')
            cell=con.execute('SELECT tenant_ref FROM lifecycle_cells WHERE account_id=?',(account,)).fetchone()
            claim=Claim(account,row['deployment_id'],cell[0],operation,row['kind'],row['generation'],row['target_profile'],row['backup_ref'],row['fence'],row['lease_owner'])
        receipt=driver.reconcile(claim)
        if receipt is None: return False
        return self.finish(claim,receipt,reconciled=True)
