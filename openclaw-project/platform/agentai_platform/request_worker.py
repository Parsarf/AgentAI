"""Customer request worker: claims waiting requests, runs each through the chat driver, hands the slot back.

Runs as the unprivileged app user. It never sees a cell token or docker; the gateway factory it is given talks to the host cell bridge. With `max_parallel` 1 (the
default) one tick handles at most one request, start to finish. With more, a tick starts as many requests as there are accounts with a cell up and nothing running,
each in its own thread, and returns without waiting for them (the next tick looks again). A request left uncertain (crash, lease loss) is recovered from the runtime's
own state; other accounts' requests go on. A request whose run waits for a person is parked: it gives up its running slot (not its cell or its reservation) and a
later tick takes it back when the person has answered or the run has ended.
"""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .adapters import CapabilityUnavailable
from .lifecycle.types import Conflict
from .request_queue import Defer, Parked, Recover, RequestClaim, RequestReceipt
from . import timing


def where(error) -> dict:
    """Where an unexpected failure happened, safe for the journal: the error's type and the code lines it passed through (file, line, function). Never its message and
    never a value: a message can carry a customer's words, a path or a key. Without this a failed request left only the name of an exception class, or nothing at all."""
    frames = [f'{Path(f.filename).name}:{f.lineno} {f.name}' for f in traceback.extract_tb(error.__traceback__)][-8:]
    return {'error': type(error).__name__, 'frames': frames}


class RequestWorker:
    def __init__(self, queue, driver, capacity, *, owner='request-worker', lease_seconds=120, clock=time.time, abandon_after=1800, shadow=None, runner=None, goals=None, max_parallel=1):
        self.queue, self.driver, self.capacity, self.owner = queue, driver, capacity, owner
        self.max_parallel = max(1, int(max_parallel))
        self._pool = ThreadPoolExecutor(max_workers=self.max_parallel, thread_name_prefix='request') if self.max_parallel > 1 else None
        self._active = {}                 # request id -> (account id, future): what this process is running right now
        self._lock = threading.Lock()
        self._errors = []                 # `where()` of failures in worker threads, reported by the next tick
        self.lease_seconds, self.clock, self.abandon_after = lease_seconds, clock, abandon_after
        self.runner = runner   # callable -> PlanRunner (or a PlanRunner): advances launched plans after every tick
        self.goals = goals     # goals.GoalChain: admits the next turn of a goal that is still active after a turn
        self.shadow = shadow   # optional observer; can never alter or block execution

    def _uncertain_claims(self):
        """Every uncertain request that holds a slot and that no thread of this process is running."""
        with self.queue.store.connect() as con:
            rows = con.execute("""SELECT r.account_id,r.id,r.project_id,r.actor_id,r.message,r.fence,r.lease_owner,r.conversation_id
                FROM request_slots s JOIN customer_requests r ON r.account_id=s.account_id AND r.id=s.request_id
                WHERE r.state='uncertain' ORDER BY r.sequence""").fetchall()
        with self._lock:
            busy = set(self._active)
        return [RequestClaim(r['account_id'], r['id'], r['project_id'], r['actor_id'], r['message'], r['fence'], r['lease_owner'], r['conversation_id'])
                for r in rows if r['id'] not in busy]

    def _uncertain_claim(self):
        claims = self._uncertain_claims()
        return claims[0] if claims else None

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
            except Exception as error:
                # Plan and goal progress is retried on the next tick; it must never break request handling. It is reported, though: a goal that silently never continued looked like a finished task.
                report = {**report, 'follow_error': where(error)}
        return report

    def _tick(self):
        if self._pool is not None:
            return self._tick_parallel()
        stuck = self._uncertain_claim()
        if stuck is not None:
            return self._settle_uncertain(stuck)
        parked = self._parked_tick()
        if parked is not None:
            return parked
        claim = self.queue.claim(owner=self.owner, capacity=self.capacity(), lease_seconds=self.lease_seconds)
        if claim is None:
            return {'ran': 0}
        return self._begin(claim)

    def _begin(self, claim):
        """A freshly claimed request: it must be funded, then it runs. -> the report of what happened (or, in parallel mode, that it started)."""
        with self.queue.store.connect() as con:
            funded = con.execute("SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=? AND state='active'",
                                 (claim.account_id, claim.request_id)).fetchone()
        if not funded:
            # Never admitted (no reservation): fail it now instead of letting it hold a running slot.
            done = self.queue.finish(claim, RequestReceipt(claim.account_id, claim.request_id, claim.fence, 'failed',
                                                           'This request could not be funded or started. Nothing ran and nothing was charged. Please send it again.', True))
            return {'ran': 0, 'failed_unfunded': bool(done)}
        timing.bind(claim.request_id)
        timing.mark(claim.request_id, 'claim', fence=claim.fence)
        if self.shadow is not None:
            self.shadow.before(claim)
        return self._run(claim)

    # -- several at once ------------------------------------------------------------------------------------------------------------------------
    def _spawn(self, claim, fn):
        """Run `fn()` for this request in its own thread. The request is `active` until it ends; a failure is kept for the next tick's report."""
        def job():
            timing.bind(claim.request_id)
            try:
                return fn()
            except Exception as error:     # the queue already marked the request uncertain; the loop must not lose the failure
                with self._lock:
                    self._errors.append(where(error))
            finally:
                with self._lock:
                    self._active.pop(claim.request_id, None)
        with self._lock:
            self._active[claim.request_id] = (claim.account_id, None)
        future = self._pool.submit(job)
        with self._lock:
            if claim.request_id in self._active:
                self._active[claim.request_id] = (claim.account_id, future)

    def _tick_parallel(self):
        report = {'ran': 0}
        with self._lock:
            errors, self._errors = self._errors, []
        if errors:
            report['thread_errors'] = errors[:5]
        # 1. Uncertain requests (crash, lease loss): reconcile them, each in a thread, so a slow runtime does not hold the others.
        for stuck in self._uncertain_claims():
            if self._capacity_left() < 1:
                break
            self._spawn(stuck, lambda stuck=stuck: self._settle_uncertain(stuck))
            report['settling'] = report.get('settling', 0) + 1
        # 2. Parked requests that are ready (or whose run ended).
        for parked in self.queue.parked():
            if self._capacity_left() < 1:
                break
            with self._lock:
                if parked.request_id in self._active:
                    continue
            state = self.driver.check_parked(parked)
            if state == 'waiting':
                continue
            claim = self.queue.unpark(parked, owner=self.owner, lease_seconds=self.lease_seconds, need_slot=state == 'ready')
            if claim is None:
                continue
            self._spawn(claim, lambda claim=claim: self._run(claim, observed=False))
            report['resumed'] = report.get('resumed', 0) + 1
        # 3. New requests, one per account with a cell up, fairly ordered, while this process has threads to spare.
        while self._capacity_left() >= 1:
            with self._lock:
                running_accounts = {a for a, _ in self._active.values()}
            claim = self.queue.claim(owner=self.owner, capacity=self.capacity(), lease_seconds=self.lease_seconds, exclude=running_accounts)
            if claim is None:
                break
            self._spawn(claim, lambda claim=claim: self._begin(claim))
            report['started'] = report.get('started', 0) + 1
        with self._lock:
            report['active'] = len(self._active)
        if report.get('started') or report.get('resumed') or report.get('settling'):
            report['ran'] = 1
        return report

    def _capacity_left(self):
        with self._lock:
            return self.max_parallel - len(self._active)

    def wait_idle(self, timeout=None):
        """Block until every request thread of this process has ended (tests and shutdown)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if not self._active:
                    return True
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.01)

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
        timing.mark(claim.request_id, 'finish_start', state=getattr(receipt, 'state', ''))
        finished = self.queue.finish(claim, receipt)
        timing.mark(claim.request_id, 'finish_done', committed=bool(finished))      # the slot is free and the UI can read the final state from here on
        if self.shadow is not None and observed:
            timing.mark(claim.request_id, 'shadow_join_start')
            self.shadow.after(claim, receipt)
            timing.mark(claim.request_id, 'shadow_join_done')        # the single worker thread is busy until here: the next claim cannot start earlier
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
            # Since it was last known alive (its lease, which is at most 120 s ahead of that moment), not since the message was sent: a request that had waited its turn for half an hour was abandoned, and charged
            # its whole reservation, on the first reconnect that failed.
            started = con.execute('SELECT max(created_epoch,coalesce(lease_until,0)-120) FROM customer_requests WHERE account_id=? AND id=?',
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
