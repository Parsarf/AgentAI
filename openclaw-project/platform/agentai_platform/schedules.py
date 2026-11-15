"""Customer schedules with stricter unattended authority (Phase 10, NATIVE-06).

Schedules are product records in local time with an IANA timezone, a bounded
timeout and a per-run task budget. Creation is refused unless the enforcement
proof flag is set. ENFORCEMENT_PROVEN is True because tests/test_schedule_engine.py
(the engine in schedule_engine.py) proves the rules: one run per local day however
many passes, restarts or engines; the schedule's own time and spending limit; the
customer's grant expiring; missed runs by policy and never back-filled; no
waiting for a person; no run for another account. The customer feature itself
stays behind the owner switch `customer_schedules` (off). A due run
is admitted only through the budget/authority callback; cheap watcher checks
come first (unchanged => no model run). Unattended approvals that are
unavailable or expired deny; pending ones wait. The native scheduler's
reported capacity of eight is a historical limit to verify, not a product
field: this service caps schedules per account at five and never claims
exactly-once firing (one firing record per local day per schedule).
"""
from __future__ import annotations
import datetime as dt
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

MAX_SCHEDULES = 5
ENFORCEMENT_PROVEN = True      # see the module docstring: a test fails if the cases that prove it are removed


class ScheduleDisabled(Conflict):
    pass


def unattended_decision(approval_state: str) -> str:
    """Stricter unattended authority: only an explicit, unexpired grant allows."""
    return {'granted': 'allow', 'pending': 'wait'}.get(approval_state, 'deny')


class ScheduleService:
    def __init__(self, store, *, enforcement_proven=None, clock=time.time):
        self.store, self.clock = store, clock
        self.enforcement_proven = ENFORCEMENT_PROVEN if enforcement_proven is None else enforcement_proven
        self.coordinator = Coordinator(store, clock=clock)

    def create(self, principal: Principal, project_id: str, name: str, *, timezone: str, hour: int,
               minute: int = 0, timeout_seconds: int = 300, task_budget_microusd: int = 0,
               watcher_id: str | None = None, prompt: str = '', missed_policy: str = 'skip', grace_seconds: int = 900,
               approve_days: int = 30) -> str:
        """Creating a schedule is the customer's grant to run it unattended, for `approve_days` days (then it needs their say-so again).
        `missed_policy`: what to do with a run whose time passed while the host was down: 'run_once' (run it once, late) or 'skip' (only run it within `grace_seconds` of its time)."""
        if not self.enforcement_proven:
            raise ScheduleDisabled('customer schedules are disabled until enforcement is proven')
        if not isinstance(prompt, str) or len(prompt) > 2000 or '\x00' in prompt:
            raise ValueError('invalid prompt')
        if missed_policy not in ('run_once', 'skip') or type(grace_seconds) is not int or not 60 <= grace_seconds <= 86400 or type(approve_days) is not int or not 1 <= approve_days <= 365:
            raise ValueError('invalid schedule policy')
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError('unknown timezone')
        for value, low, high in ((hour, 0, 23), (minute, 0, 59), (timeout_seconds, 30, 900)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('schedule value out of range')
        if type(task_budget_microusd) is not int or task_budget_microusd < 0:
            raise ValueError('invalid budget')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, identifier(project_id))).fetchone():
                raise NotFound('unavailable')
            existing = con.execute('SELECT id FROM schedules WHERE account_id=? AND project_id=? AND name=?',
                                   (principal.account_id, project_id, name)).fetchone()
            if existing:
                return existing['id']
            if con.execute('SELECT count(*) FROM schedules WHERE account_id=?',
                           (principal.account_id,)).fetchone()[0] >= MAX_SCHEDULES:
                raise Conflict('schedule limit reached')
            if watcher_id and not con.execute('SELECT 1 FROM watchers WHERE account_id=? AND id=?',
                                              (principal.account_id, watcher_id)).fetchone():
                raise NotFound('unavailable')
            schedule_id = uuid.uuid4().hex
            con.execute('''INSERT INTO schedules(account_id,project_id,id,name,timezone,hour_local,minute_local,
                timeout_seconds,task_budget_microusd,watcher_id,state,created_epoch,prompt,missed_policy,grace_seconds,approved_until_epoch)
                VALUES (?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?)''',
                        (principal.account_id, project_id, schedule_id, name, timezone, hour, minute,
                         timeout_seconds, task_budget_microusd, watcher_id, int(self.clock()), prompt.strip(), missed_policy, grace_seconds,
                         int(self.clock()) + approve_days * 86400))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, schedule_id,
                                    'schedule.create', 'completed')
            return schedule_id

    def due(self, principal: Principal, schedule_id: str, *, admit, approval_state='denied',
            changed=True) -> dict:
        """Decide one tick. ``admit()`` is the task-budget admission; ``changed`` is the
        result of the cheap deterministic check (False => zero model calls)."""
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT * FROM schedules WHERE account_id=? AND id=?',
                              (principal.account_id, identifier(schedule_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['state'] != 'active':
                return {'run': False, 'reason': 'paused'}
            local = dt.datetime.fromtimestamp(self.clock(), ZoneInfo(row['timezone']))
            if (local.hour, local.minute) < (row['hour_local'], row['minute_local']):
                return {'run': False, 'reason': 'not_due'}
            day = local.date().isoformat()
            if row['last_fired_day'] == day:
                return {'run': False, 'reason': 'already_fired_today'}
            decision = unattended_decision(approval_state)
            if decision == 'wait':
                return {'run': False, 'reason': 'waiting_for_approval'}
            if decision == 'deny':
                return {'run': False, 'reason': 'unattended_authority_denied'}
            if not changed:
                con.execute('UPDATE schedules SET last_fired_day=? WHERE account_id=? AND id=?',
                            (day, principal.account_id, schedule_id))
                return {'run': False, 'reason': 'unchanged', 'model_calls': 0}
            if not admit():
                return {'run': False, 'reason': 'admission_denied'}
            con.execute('UPDATE schedules SET last_fired_day=? WHERE account_id=? AND id=?',
                        (day, principal.account_id, schedule_id))
            return {'run': True, 'reason': 'due', 'timeout_seconds': row['timeout_seconds'],
                    'task_budget_microusd': row['task_budget_microusd']}
