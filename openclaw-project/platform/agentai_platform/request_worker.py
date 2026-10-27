"""Customer request worker: claims one waiting request, runs it through the chat driver, hands the slot back.

Runs as the unprivileged app user. It never sees a cell token or docker; the gateway factory it is given talks to the host cell bridge. One tick handles at most one
request. A request left uncertain (crash, lease loss) is recovered from the runtime's own state before anything else is claimed. A request whose run waits for a
person is parked: it gives up the one running slot (not its cell or its reservation) and a later tick takes it back when the person has answered or the run has ended.
"""
import time

from .adapters import CapabilityUnavailable
from .lifecycle.types import Conflict
from .request_queue import Defer, Parked, Recover, RequestClaim, RequestReceipt


class RequestWorker:
    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time, abandon_after=1800, shadow=None, runner=None, goals=None):
        self.queue, self.driver, self.capacity, self.owner = queue, driver, capacity, owner
        self.lease_seconds, self.clock, self.abandon_after = lease_seconds, clock, abandon_after
        self.runner = runner   # callable -> PlanRunner (or a PlanRunner): advances launched plans after every tick
        self.goals = goals     # goals.GoalChain: admits the next turn of a goal that is still active after a turn
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
        report = self._tick()
        for follow in (self.runner, self.goals):
            if follow is None:
                continue
            try:
                follow = follow() if callable(follow) else follow
                started = follow.tick()
                if started:
                    report = {**report, 'followed': started}
            except Exception:
                pass   # plan and goal progress is retried on the next tick; it must never break request handling
        return report

    def _tick(self):
        stuck = self._uncertain_claim()
        if stuck is not None:
            return self._settle_uncertain(stuck)
        parked = self._parked_tick()
        if parked is not None:
            return parked
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
        return self._run(claim)

    def _run(self, claim, *, observed=True):
        """Drive one claimed request as far as it goes: finished, parked on a person, or sent back to wait for the session."""
        try:
            receipt = self.driver.execute(claim)
        except Exception:
            self.queue.uncertain(claim)
            raise
        if isinstance(receipt, Parked):
            self.queue.park(claim, receipt.reason)
            return {'ran': 1, 'parked': receipt.reason}
        if isinstance(receipt, Defer):
            self.queue.defer(claim)
            return {'ran': 0, 'deferred': True}
        finished = self.queue.finish(claim, receipt)
        if self.shadow is not None and observed:
            self.shadow.after(claim, receipt)
        return {'ran': 1, 'finished': bool(finished)}

    def _settle_uncertain(self, stuck):
        try:
            result = self.queue.reconcile(self.driver, stuck)
            if isinstance(result, Recover):          # the run is alive (or ended unseen): carry on supervising it under a new fence
                return self._run(self.queue.recover(stuck, owner=self.owner, lease_seconds=self.lease_seconds), observed=False)
            if result:
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

    def _parked_tick(self):
        """Look at the requests waiting for a person, oldest first. One that is ready needs the slot back; one whose run ended (or that waited too long, or was stopped) is only closed."""
        for parked in self.queue.parked():
            state = self.driver.check_parked(parked)
            if state == 'waiting':
                continue
            claim = self.queue.unpark(parked, owner=self.owner, lease_seconds=self.lease_seconds, need_slot=state == 'ready')
            if claim is None:
                continue                                   # the slot is busy: it stays parked and is looked at again
            return self._run(claim, observed=False)
        return None
