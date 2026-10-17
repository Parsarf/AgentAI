"""Durable serial customer intake. The privileged adapter owns budget/native effects."""
from dataclasses import dataclass
import hashlib
import json
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
    conversation_id: str | None = None

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
    def __init__(self,store,clock=time.time,*,require_cell=False):
        # require_cell (production): a request runs only while its own account's cell holds the active lifecycle slot.
        self.require_cell=require_cell
        self.store=store;self.clock=clock;self.coordinator=Coordinator(store,clock=clock)
    def submit(self,principal,*,message,key,conversation_id=None,intent='chat',context=None):
        identifier(key)
        if not isinstance(message,str) or not message.strip() or len(message)>16000 or '\x00' in message:raise ValueError('invalid message')
        if intent not in ('chat','plan','execute','phase','browse'):raise ValueError('invalid intent')
        context_json=json.dumps(context,sort_keys=True,separators=(',',':')) if context else None
        digest=hashlib.sha256(message.encode()).hexdigest() if intent=='chat' and not context_json else hashlib.sha256((message+'|'+intent+'|'+(context_json or '')).encode()).hexdigest()
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            old=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND idempotency_key=?',(principal.account_id,key)).fetchone()
            if old:
                if old['payload_hash']!=digest or old['conversation_id']!=conversation_id:raise Conflict('request payload changed')
                return self._view(c,old)
            if c.execute("SELECT count(*) FROM customer_requests WHERE account_id=? AND state='waiting'",(principal.account_id,)).fetchone()[0]>=3:raise Conflict('queue full')
            if conversation_id is not None:
                # The request belongs to the project its conversation lives in (budget admission checks that pairing).
                project=c.execute('SELECT project_id FROM conversations WHERE account_id=? AND id=?',(principal.account_id,conversation_id)).fetchone()
                if not project:raise NotFound('unavailable')
            else:
                project=c.execute('SELECT id FROM projects WHERE account_id=? ORDER BY created_at,id LIMIT 1',(principal.account_id,)).fetchone()
                if not project:raise Conflict('account setup incomplete')
            request=uuid.uuid4().hex
            c.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,intent,context_json)
                VALUES (?,?,?,?,?,?,?,?,'waiting',?,?,?)''',(principal.account_id,request,principal.actor_id,project[0],conversation_id,key,digest,message,int(self.clock()),intent,context_json))
            self.coordinator._audit(c,principal.account_id,principal.actor_id,request,'request_submit','completed')
            return self._view(c,c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone())
    def _public(self,row,ahead=None):
        # `ahead`: how many tasks run before this one (the task using the slot, then earlier unpaused waiting tasks of any account); None unless it is waiting its turn.
        view={k:row[k] for k in ['id','message','state','cancel_requested','result','created_epoch','conversation_id']}
        view.update(paused=bool(row['paused']),retry_of=row['retry_of'],ahead=ahead)
        return view
    @staticmethod
    def _ahead(c,row):
        if row['state']!='waiting' or row['paused']:return None
        busy=c.execute('SELECT count(*) FROM request_slot').fetchone()[0]
        return busy+c.execute("SELECT count(*) FROM customer_requests WHERE state='waiting' AND paused=0 AND sequence<?",(row['sequence'],)).fetchone()[0]
    def _view(self,c,row):return self._public(row,self._ahead(c,row))
    def get(self,principal,request=None):
        with self.store.connect() as c:
            self.store._authorize(c,principal)
            if request:
                row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
                if not row:raise NotFound()
                return self._view(c,row)
            return [self._view(c,r) for r in c.execute('SELECT * FROM customer_requests WHERE account_id=? ORDER BY sequence DESC LIMIT 100',(principal.account_id,)).fetchall()]
    def cancel(self,principal,request):
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
            if not row:raise NotFound()
            if row['state']=='waiting':c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND id=?",(principal.account_id,request))
            elif row['state'] in {'starting','running','uncertain'}:c.execute('UPDATE customer_requests SET cancel_requested=1 WHERE account_id=? AND id=?',(principal.account_id,request))
            self.coordinator._audit(c,principal.account_id,principal.actor_id,request,'request_cancel','completed')
            return self._public(c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone())
    def pause(self,principal,request):
        """Hold a task that has not started: it keeps its place in the account's queue limit and its budget reservation, but is never claimed and never wakes the assistant."""
        return self._hold(principal,request,1)
    def resume(self,principal,request):
        return self._hold(principal,request,0)
    def _hold(self,principal,request,paused):
        with self.coordinator.transaction() as c:
            self.store._authorize(c,principal)
            row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
            if not row:raise NotFound()
            if row['state']!='waiting':raise Conflict('only a task that has not started can be paused or resumed')
            if row['paused']!=paused:
                c.execute('UPDATE customer_requests SET paused=? WHERE account_id=? AND id=?',(paused,principal.account_id,request))
                self.coordinator._audit(c,principal.account_id,principal.actor_id,request,'request_pause' if paused else 'request_resume','completed')
            return self._view(c,c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone())
    def retry_source(self,principal,request):
        """What a retry re-runs: only a task that failed or was cancelled. Also the earlier retry attempts (keys `retry-<id>-<n>`), so a repeat press finds the live one
        and an attempt that was refused (budget) and cancelled is followed by a new key instead of being handed the dead request again."""
        with self.store.connect() as c:
            self.store._authorize(c,principal)
            row=c.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?',(principal.account_id,request)).fetchone()
            if not row:raise NotFound()
            if row['state'] not in {'failed','cancelled'}:raise Conflict('only a failed or cancelled task can be retried')
            if not row['conversation_id']:raise Conflict('this task has no conversation to retry in')
            mark='retry-'+request+'-'
            attempts=c.execute("SELECT * FROM customer_requests WHERE account_id=? AND substr(idempotency_key,1,?)=? ORDER BY sequence DESC",(principal.account_id,len(mark),mark)).fetchall()
            return {'message':row['message'],'conversation_id':row['conversation_id'],'intent':row['intent'],'context':json.loads(row['context_json']) if row['context_json'] else None,
                    'attempts':len(attempts),'latest':self._view(c,attempts[0]) if attempts else None}
    def mark_retry(self,principal,request,source):
        with self.coordinator.transaction() as c:
            c.execute('UPDATE customer_requests SET retry_of=? WHERE account_id=? AND id=? AND retry_of IS NULL',(source,principal.account_id,request))
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
                row=c.execute("SELECT * FROM customer_requests WHERE state='waiting' AND paused=0 ORDER BY sequence LIMIT 1").fetchone()
                if not row:return None
                authorized=c.execute("SELECT 1 FROM accounts a JOIN memberships m ON m.account_id=a.id WHERE a.id=? AND a.status='active' AND m.actor_id=? AND m.status='active' AND m.role='customer'",(row['account_id'],row['actor_id'])).fetchone()
                if authorized:break
                c.execute("UPDATE customer_requests SET state='cancelled' WHERE account_id=? AND id=?",(row['account_id'],row['id']))
                self.coordinator._audit(c,row['account_id'],'worker',row['id'],'request_revoked','completed')
            cell_slot=c.execute('SELECT account_id,state FROM lifecycle_slot WHERE id=1').fetchone()
            if cell_slot and (cell_slot['account_id']!=row['account_id'] or cell_slot['state']!='active'):return None
            if self.require_cell and not cell_slot and row['intent']!='browse':return None     # a browse run uses its own sandbox, not the assistant's cell
            c.execute('INSERT INTO request_slot VALUES (1,?,?)',(row['account_id'],row['id']))
            fence=row['fence']+1
            c.execute("UPDATE customer_requests SET state='starting',fence=?,lease_owner=?,lease_until=? WHERE account_id=? AND id=?",(fence,owner,int(self.clock())+lease_seconds,row['account_id'],row['id']))
            self.coordinator._audit(c,row['account_id'],'worker',row['id'],'request_claim','pending')
            return RequestClaim(row['account_id'],row['id'],row['project_id'],row['actor_id'],row['message'],fence,owner,row['conversation_id'])
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
            held=c.execute('SELECT account_id,state FROM lifecycle_slot WHERE id=1').fetchone()
            # The cell may stay up for the same account (idle sleep stops it later); anything else must stop first.
            if held and not (self.require_cell and held['account_id']==claim.account_id and held['state']=='active'):raise Conflict('agent cell must stop before handoff')
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
