"""Customer request worker: claims one waiting request, runs it through the chat driver, hands the slot back.

Runs as the unprivileged app user. It never sees a cell token or docker; the
gateway factory it is given talks to the host cell bridge. One tick handles at
most one request. A request left uncertain (crash, lease loss) is reconciled
from the cell's own transcript before anything else is claimed.
"""
import time

from .adapters import CapabilityUnavailable
from .lifecycle.types import Conflict
from .request_queue import RequestClaim, RequestReceipt


class RequestWorker:
    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time, abandon_after=1800, shadow=None):
        self.queue, self.driver, self.capacity, self.owner = queue, driver, capacity, owner
        self.lease_seconds, self.clock, self.abandon_after = lease_seconds, clock, abandon_after
        self.shadow = shadow   # optional observer; can never alter or block execution

    def _uncertain_claim(self):
        with self.queue.store.connect() as con:
            row = con.execute("""SELECT r.account_id,r.id,r.project_id,r.actor_id,r.message,r.fence,r.lease_owner,r.conversation_id
                FROM request_slot s JOIN customer_requests r ON r.account_id=s.account_id AND r.id=s.request_id
                WHERE r.state='uncertain'""").fetchone()
        if not row:
            return None
        return RequestClaim(row['account_id'], row['id'], row['project_id'], row['actor_id'], row['message'],
                            row['fence'], row['lease_owner'], row['conversation_id'])

    def tick(self):
        stuck = self._uncertain_claim()
        if stuck is not None:
            try:
                if self.queue.reconcile(self.driver, stuck):
                    return {'reconciled': True}
            except (CapabilityUnavailable, Conflict):
                pass
            with self.queue.store.connect() as con:
                started = con.execute('SELECT created_epoch FROM customer_requests WHERE account_id=? AND id=?',
                                      (stuck.account_id, stuck.request_id)).fetchone()[0]
            if self.clock() - started > self.abandon_after:
                # The runtime has been unreachable too long: stop the request so the shared slot is not held forever.
                return {'reconciled': bool(self.queue.finish(stuck, self.driver.abandon(stuck), reconciled=True)), 'abandoned': True}
            return {'reconciled': False, 'blocked': 'uncertain request awaiting reconciliation'}
        claim = self.queue.claim(owner=self.owner, capacity=self.capacity(), lease_seconds=self.lease_seconds)
        if claim is None:
            return {'ran': 0}
        with self.queue.store.connect() as con:
            funded = con.execute("SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=? AND state='active'",
                                 (claim.account_id, claim.request_id)).fetchone()
        if not funded:
            # Never admitted (no reservation): fail it now instead of letting it hold the single running slot.
            done = self.queue.finish(claim, RequestReceipt(claim.account_id, claim.request_id, claim.fence, 'failed',
                                                           'This request could not be funded or started. Nothing ran and nothing was charged. Please send it again.', True))
            return {'ran': 0, 'failed_unfunded': bool(done)}
        if self.shadow is not None:
            self.shadow.before(claim)
        try:
            receipt = self.driver.execute(claim)
            finished = self.queue.finish(claim, receipt)
            if self.shadow is not None:
                self.shadow.after(claim, receipt)
        except Exception:
            self.queue.uncertain(claim)
            raise
        return {'ran': 1, 'finished': bool(finished)}
