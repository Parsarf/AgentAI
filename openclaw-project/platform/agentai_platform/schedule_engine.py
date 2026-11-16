"""The schedule engine (roadmap #78, with the watcher engine of #79): starts the recurring tasks customers have set up, safely and without anyone watching.

Rules this module enforces, each proved by tests/test_schedule_engine.py:
* at most ONE run per schedule per local day, recorded in `schedule_runs` before anything starts (the row's primary key is the guard, so a restart, a crash or a second engine can never
  fire it twice); the run itself is started under a fixed request key, so a crash between the record and the start is finished, not repeated;
* a run missed while the host was down follows the schedule's own policy: `run_once` runs it late, once; `skip` only runs it within its grace window and records the day as missed.
  Nothing is ever back-filled: after three days down it is one run, not three;
* a schedule runs only while the customer's grant (given when they created it, for a limited time) is current; an expired grant denies, and the day is recorded as denied;
* a schedule tied to a watcher runs only when the watcher saw a change (an unchanged check costs no model call and starts nothing);
* the run is an ordinary request with the schedule's own time limit and spending limit, admitted by the same budget as any task; the assistant is told nobody is watching;
* an unattended run never waits for a person: if it needs an answer, a takeover or a permission it stops and says so (the driver ends it as blocked). A permission it asked for stays
  unanswered, so a schedule can never do what the customer could not approve themselves;
* it runs on the account's own cell and on its own turn: the account's one interactive slot, never in front of what the customer is doing now.
The customer-facing feature stays off until the owner switch `customer_schedules` is on; this engine does nothing while `enabled()` is false.
"""
from __future__ import annotations
import datetime as dt
import time
from zoneinfo import ZoneInfo

from .lifecycle.coordinator import Coordinator
from .security import Principal

REFUSED = {'BudgetDenied': 'budget', 'Conflict': 'busy', 'CapabilityUnavailable': 'not_ready'}      # fixed words for the customer; never an exception's own text


class ScheduleEngine:
    def __init__(self, store, chat, *, enabled=lambda: False, clock=time.time):
        self.store, self.chat, self.enabled, self.clock = store, chat, enabled, clock
        self.coordinator = Coordinator(store, clock=clock)

    # -- one pass -----------------------------------------------------------------------------------------------------------------------------
    def tick(self) -> dict:
        if not self.enabled():
            return {'enabled': False}
        report = {'enabled': True, 'fired': 0, 'missed': 0, 'denied': 0, 'unchanged': 0, 'refused': 0, 'recovered': 0}
        self.sync()
        with self.store.connect() as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM schedules WHERE state='active' AND prompt<>'' ORDER BY created_epoch LIMIT 200")]
        for row in rows:
            try:
                outcome = self._consider(row)
            except Exception:
                continue                                           # one schedule's trouble never stops the others; it is tried again on the next pass
            if outcome:
                report[outcome] += 1
        report['recovered'] = self._recover()
        return report

    def _consider(self, row: dict):
        now = self.clock()
        local = dt.datetime.fromtimestamp(now, ZoneInfo(row['timezone']))
        slot = local.replace(hour=row['hour_local'], minute=row['minute_local'], second=0, microsecond=0)
        if local < slot:
            # Today's time has not come. Yesterday's run is still owed if the day turned before it was looked at (the host was down over midnight): it then follows the schedule's
            # own policy like any late run. One day back and no further: nothing is back-filled. A schedule made after that time owes nothing for it.
            slot = (local - dt.timedelta(days=1)).replace(hour=row['hour_local'], minute=row['minute_local'], second=0, microsecond=0)
            if row['created_epoch'] > slot.timestamp():
                return None
        day = slot.date().isoformat()
        late = now - slot.timestamp()          # real seconds, not wall-clock arithmetic: on the day the clocks go forward a time in the skipped hour is not "an hour late"
        with self.coordinator.transaction() as con:
            if con.execute('SELECT 1 FROM schedule_runs WHERE account_id=? AND schedule_id=? AND day=?', (row['account_id'], row['id'], day)).fetchone():
                return None                                         # today's run (or its reason not to run) is already recorded
            def record(state, reason=''):
                con.execute('INSERT INTO schedule_runs(account_id,schedule_id,day,state,reason,created_epoch) VALUES (?,?,?,?,?,?)', (row['account_id'], row['id'], day, state, reason, int(now)))
                con.execute('UPDATE schedules SET last_fired_day=? WHERE account_id=? AND id=?', (day, row['account_id'], row['id']))
            if row['missed_policy'] == 'skip' and late > row['grace_seconds']:
                record('missed', 'missed_window')
                return 'missed'
            if not (row['approved_until_epoch'] and row['approved_until_epoch'] > now):
                record('denied', 'grant_expired')
                return 'denied'
            if row['watcher_id']:
                pending = con.execute("SELECT observed_hash FROM watcher_notifications WHERE account_id=? AND watcher_id=? AND state='pending' ORDER BY created_epoch LIMIT 1",
                                      (row['account_id'], row['watcher_id'])).fetchone()
                if not pending:
                    record('unchanged', 'no_change')               # the cheap check saw nothing: no request, no model call
                    return 'unchanged'
                con.execute("UPDATE watcher_notifications SET state='delivered' WHERE account_id=? AND watcher_id=? AND observed_hash=?", (row['account_id'], row['watcher_id'], pending['observed_hash']))
            record('firing')
        return self._start(row, day)

    # -- starting a run (safe to repeat: the request key is fixed) --------------------------------------------------------------------------------
    def _principal(self, con, account):
        row = con.execute("SELECT actor_id FROM memberships WHERE account_id=? AND role='customer' AND status='active' ORDER BY actor_id LIMIT 1", (account,)).fetchone()
        return Principal(account, row['actor_id'], 'customer') if row else None

    def _conversation(self, principal, row):
        if row['conversation_id']:
            return row['conversation_id']
        conversation = self.chat.create_conversation(principal, row['project_id'])['id']
        try:
            self.chat.rename_conversation(principal, conversation, row['name'][:90])
        except Exception:
            pass                                                   # a title is a convenience
        if conversation:
            with self.coordinator.transaction() as con:
                con.execute('UPDATE schedules SET conversation_id=? WHERE account_id=? AND id=? AND conversation_id IS NULL', (conversation, row['account_id'], row['id']))
        return conversation

    def _start(self, row: dict, day: str):
        with self.store.connect() as con:
            principal = self._principal(con, row['account_id'])
        if principal is None:
            self._finish(row, day, 'refused', 'no_customer')
            return 'refused'
        key = f'sched-{row["id"]}-{day}'
        try:
            conversation = self._conversation(principal, row)
            if not conversation:
                raise LookupError('no conversation')
            result = self.chat._spawn(principal, conversation, message=row['prompt'], key=key, intent='schedule',
                                      context={'schedule': row['id'], 'unattended': True, 'timeout_seconds': row['timeout_seconds'], 'budget_microusd': row['task_budget_microusd']},
                                      shown=f'Scheduled: {row["name"]}', budget_microusd=row['task_budget_microusd'] or None)
        except Exception as error:
            self._finish(row, day, 'refused', REFUSED.get(type(error).__name__, 'not_started'))
            return 'refused'
        with self.coordinator.transaction() as con:
            con.execute("UPDATE schedule_runs SET state='started',request_id=? WHERE account_id=? AND schedule_id=? AND day=? AND state='firing'", (result['id'], row['account_id'], row['id'], day))
        return 'fired'

    def _finish(self, row, day, state, reason):
        with self.coordinator.transaction() as con:
            con.execute('UPDATE schedule_runs SET state=?,reason=?,finished_epoch=? WHERE account_id=? AND schedule_id=? AND day=? AND state=?', (state, reason, int(self.clock()), row['account_id'], row['id'], day, 'firing'))

    def _recover(self) -> int:
        """A run recorded as `firing` whose start never finished (a crash between the record and the request): start it again under the same key, which never makes a second run."""
        with self.store.connect() as con:
            stuck = [dict(r) for r in con.execute("""SELECT s.*,r.day AS run_day FROM schedule_runs r JOIN schedules s ON s.account_id=r.account_id AND s.id=r.schedule_id
                WHERE r.state='firing' AND r.created_epoch<? LIMIT 50""", (int(self.clock()) - 30,))]
        done = 0
        for row in stuck:
            if self._start(row, row['run_day']) == 'fired':
                done += 1
        return done

    # -- what happened to the runs that were started --------------------------------------------------------------------------------------------
    def sync(self):
        with self.store.connect() as con:
            started = [dict(r) for r in con.execute("""SELECT r.account_id,r.schedule_id,r.day,q.state,q.outcome FROM schedule_runs r
                JOIN customer_requests q ON q.account_id=r.account_id AND q.id=r.request_id WHERE r.state='started' AND q.state IN ('completed','failed','cancelled') LIMIT 200""")]
        for r in started:
            state = 'completed' if r['state'] == 'completed' and r['outcome'] in ('completed', None) else 'blocked' if r['outcome'] in ('blocked', 'partial') else 'failed'
            with self.coordinator.transaction() as con:
                con.execute("UPDATE schedule_runs SET state=?,finished_epoch=? WHERE account_id=? AND schedule_id=? AND day=? AND state='started'", (state, int(self.clock()), r['account_id'], r['schedule_id'], r['day']))

    def history(self, principal: Principal, schedule_id: str, limit=14):
        """What the customer sees: each day's outcome in fixed words."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return [dict(r) for r in con.execute('SELECT day,state,reason,request_id,created_epoch,finished_epoch FROM schedule_runs WHERE account_id=? AND schedule_id=? ORDER BY day DESC LIMIT ?',
                                                 (principal.account_id, schedule_id, max(1, min(int(limit), 60))))]
