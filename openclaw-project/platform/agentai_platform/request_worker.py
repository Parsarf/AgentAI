"""Customer request worker: claims one waiting request, runs it through the chat driver, hands the slot back.

Runs as the unprivileged app user. It never sees a cell token or docker; the
gateway factory it is given talks to the host cell bridge. One tick handles at
most one request. A request left uncertain (crash, lease loss) is reconciled
from the cell's own transcript before anything else is claimed.
"""
import time

from .adapters import CapabilityUnavailable
from .lifecycle.types import Conflict
from .request_queue import RequestClaim


class RequestWorker:
    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time):
        self.queue, self.driver, self.capacity, self.owner = queue, driver, capacity, owner
        self.lease_seconds, self.clock = lease_seconds, clock

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
                return {'reconciled': bool(self.queue.reconcile(self.driver, stuck))}
            except (CapabilityUnavailable, Conflict):
                return {'reconciled': False, 'blocked': 'uncertain request awaiting reconciliation'}
        claim = self.queue.claim(owner=self.owner, capacity=self.capacity(), lease_seconds=self.lease_seconds)
        if claim is None:
            return {'ran': 0}
        try:
            finished = self.queue.finish(claim, self.driver.execute(claim))
        except Exception:
            self.queue.uncertain(claim)
            raise
        return {'ran': 1, 'finished': bool(finished)}
