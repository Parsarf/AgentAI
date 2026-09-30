"""Durable serial customer intake. The privileged adapter owns budget/native effects."""
from dataclasses import dataclass
import hashlib
import time
import uuid
from .adapters import CapabilityUnavailable
from .security import NotFound
from .lifecycle.coordinator import Coordinator,identifier
from .lifecycle.types import Conflict

@dataclass(frozen=True)
class RequestClaim:
    account_id: str
    request_id: str
    project_id: str
    actor_id: str
    message: str
    fence: int
    owner: str

@dataclass(frozen=True)
class RequestReceipt:
    account_id: str
    request_id: str
    fence: int
    state: str
    public_result: str
    quiesced: bool

class DisabledRequestDriver:
    def preflight(self):raise CapabilityUnavailable('isolated runtime and provider admission not connected')
    def execute(self,claim):self.preflight()
    def reconcile(self,claim):self.preflight()

class RequestQueue:
    def __init__(self,store,clock=time.time):
        self.store=store;self.clock=clock;self.coordinator=Coordinator(store,clock=clock)
    def submit(self,principal,*,message,key):
        identifier(key)
        if not isinstance(message,str) or not message.strip() or len(message)>16000 or '\x00' in message:raise ValueError('invalid message')
        digest=hashlib.sha256(message.encode()).hexdigest()
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            old=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND idempotency_key=?',(principal.account_id,key)).fetchone()
            if old:
                if old['payload_hash']!=digest:raise Conflict('request payload changed')
                return self._public(old)
            if c.execute("SELECT count(*) FROM customer_requests WHERE account_id=? AND state='waiting'",(principal.account_id,)).fetchone()[0]>=3:raise Conflict('queue full')
            project=c.execute('SELECT id FROM projects WHERE account_id=? ORDER BY created_at,id LIMIT 1',(principal.account_id,)).fetchone()
            if not project:raise Conflict('account setup incomplete')
            request=uuid.uuid4().hex
            c.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch)
                VALUES (?,?,?,?,?,?,?,'waiting',?)''',(principal.account_id,request,principal.actor_id,project[0],key,digest,message,int(self.clock())))
            self.coordinator._audit(c,principal.account_id,principal.actor_id,request,'request_submit','completed')
            return self._public(c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone())
    def _public(self,row):
        return {k:row[k] for k in ['id','message','state','cancel_requested','result','created_epoch']}
    def get(self,principal,request=None):
        with self.store.connect() as c:
            self.store._authorize(c,principal)
            if request:
                row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
                if not row:raise NotFound()
                return self._public(row)
            return [self._public(r) for r in c.execute('SELECT * FROM customer_requests WHERE account_id=? ORDER BY sequence DESC LIMIT 100',(principal.account_id,)).fetchall()]
    def cancel(self,principal,request):
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
            if not row:raise NotFound()
            if row['state']=='waiting':c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND id=?",(principal.account_id,request))
            elif row['state'] in {'starting','running','uncertain'}:c.execute('UPDATE customer_requests SET cancel_requested=1 WHERE account_id=? AND id=?',(principal.account_id,request))
            self.coordinator._audit(c,principal.account_id,principal.actor_id,request,'request_cancel','completed')
            return self._public(c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone())
    def claim(self,*,owner,capacity,lease_seconds=60):
        identifier(owner)
        if type(lease_seconds) is not int or not 1<=lease_seconds<=120:raise ValueError('invalid lease')
        with self.coordinator.transaction() as c:
            slot=c.execute('SELECT * FROM request_slot WHERE id=1').fetchone()
            if slot:
                c.execute("UPDATE customer_requests SET state='uncertain' WHERE account_id=? AND id=? AND state IN ('starting','running') AND lease_until<=?",(slot['account_id'],slot['request_id'],int(self.clock())))
                return None
            if capacity.admitted_slots<1 or capacity.blockers:return None
            # Skip requests whose author/account was revoked while they waited.
            while True:
                row=c.execute("SELECT * FROM customer_requests WHERE state='waiting' ORDER BY sequence LIMIT 1").fetchone()
                if not row:return None
                authorized=c.execute("SELECT 1 FROM accounts a JOIN memberships m ON m.account_id=a.id WHERE a.id=? AND a.status='active' AND m.actor_id=? AND m.status='active' AND m.role='customer'",(row['account_id'],row['actor_id'])).fetchone()
                if authorized:break
                c.execute("UPDATE customer_requests SET state='cancelled' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
                self.coordinator._audit(c,row['account_id'],'worker',row['id'],'request_revoked','completed')
            cell_slot=c.execute('SELECT account_id,state FROM lifecycle_slot WHERE id=1').fetchone()
            if cell_slot and (cell_slot['account_id']!=row['account_id'] or cell_slot['state']!='active'):return None
            c.execute('INSERT INTO request_slot VALUES (1,?,?)',(row['account_id'],row['id']))
            fence=row['fence']+1
            c.execute("UPDATE customer_requests SET state='starting',fence=?,lease_owner=?,lease_until=? WHERE account_id=? AND id=?",(fence,owner,int(self.clock())+lease_seconds,row['account_id'],row['id']))
            self.coordinator._audit(c,row['account_id'],'worker',row['id'],'request_claim','pending')
            return RequestClaim(row['account_id'],row['id'],row['project_id'],row['actor_id'],row['message'],fence,owner)
    def _fenced(self,c,claim):
        row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(claim.account_id,claim.request_id)).fetchone()
        if not row:raise NotFound()
        if (row['project_id'],row['actor_id'],row['message'])!=(claim.project_id,claim.actor_id,claim.message):raise Conflict('claim payload changed')
        if row['fence']!=claim.fence or row['lease_owner']!=claim.owner or row['state'] not in {'starting','running','uncertain'}:raise Conflict('worker fenced')
        return row
    def uncertain(self,claim):
        with self.coordinator.transaction() as c:
            self._fenced(c,claim)
            c.execute("UPDATE customer_requests SET state='uncertain' WHERE account_id=? AND id=?",(claim.account_id,claim.request_id))
            self.coordinator._audit(c,claim.account_id,'worker',claim.request_id,'request_unknown','uncertain')
    def heartbeat(self,claim):
        with self.coordinator.transaction() as c:
            row=self._fenced(c,claim)
            if row['state']=='uncertain' or row['lease_until']<=self.clock():raise Conflict('lease expired; reconcile before resume')
            if not c.execute("SELECT 1 FROM accounts a JOIN memberships m ON a.id=m.account_id WHERE a.id=? AND a.status='active' AND m.actor_id=? AND m.role='customer' AND m.status='active'",(claim.account_id,claim.actor_id)).fetchone():
                c.execute('UPDATE customer_requests SET cancel_requested=1 WHERE account_id=? AND id=?',(claim.account_id,claim.request_id))
                cancel=True
            else:cancel=bool(row['cancel_requested'])
            c.execute("UPDATE customer_requests SET state='running',lease_until=? WHERE account_id=? AND id=?",(int(self.clock())+60,claim.account_id,claim.request_id))
            return cancel
    def finish(self,claim,receipt,*,reconciled=False):
        if (receipt.account_id,receipt.request_id,receipt.fence)!=(claim.account_id,claim.request_id,claim.fence):raise Conflict('receipt target mismatch')
        if receipt.state not in {'completed','failed','cancelled'} or receipt.quiesced is not True:raise Conflict('runtime not drained')
        if not isinstance(receipt.public_result,str) or len(receipt.public_result)>16000:raise ValueError('invalid public result')
        with self.coordinator.transaction() as c:
            row=self._fenced(c,claim)
            if not reconciled and (row['state']=='uncertain' or row['lease_until']<=self.clock()):
                c.execute("UPDATE customer_requests SET state='uncertain' WHERE account_id=? AND id=?",(claim.account_id,claim.request_id));return False
            if c.execute('SELECT 1 FROM lifecycle_slot WHERE id=1').fetchone():raise Conflict('agent cell must stop before handoff')
            reservation=c.execute('SELECT state FROM task_reservations WHERE account_id=? AND task_id=?',(claim.account_id,claim.request_id)).fetchone()
            if reservation and reservation[0] in {'active','uncertain'}:raise Conflict('usage must reconcile before handoff')
            c.execute('UPDATE customer_requests SET state=?,result=? WHERE account_id=? AND id=?',(receipt.state,receipt.public_result,claim.account_id,claim.request_id))
            c.execute('DELETE FROM request_slot WHERE account_id=? AND request_id=?',(claim.account_id,claim.request_id))
            self.coordinator._audit(c,claim.account_id,'worker',claim.request_id,'request_finish','completed')
            return True
    def run_once(self,driver,*,owner,capacity):
        # Preflight includes host-owned binding, isolated runtime and budget/route readiness.
        driver.preflight()
        claim=self.claim(owner=owner,capacity=capacity)
        if not claim:return False
        try:return self.finish(claim,driver.execute(claim))
        except Exception:
            self.uncertain(claim);raise
    def reconcile(self,driver,claim):
        with self.coordinator.transaction() as c:
            row=self._fenced(c,claim)
            if row['state']!='uncertain':raise Conflict('reconciliation not required')
        receipt=driver.reconcile(claim)
        return False if receipt is None else self.finish(claim,receipt,reconciled=True)
