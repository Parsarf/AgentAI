"""Customer schedules with stricter unattended authority (Phase 10, NATIVE-06).

Schedules are product records in local time with an IANA timezone, a bounded
timeout and a per-run task budget. Creation is refused until the enforcement
proof flag is set (``enforcement_proven=False`` by default), matching the rule
that no new customer schedule is enabled before enforcement proof. A due run
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


class ScheduleDisabled(Conflict):
    pass


def unattended_decision(approval_state: str) -> str:
    """Stricter unattended authority: only an explicit, unexpired grant allows."""
    return {'granted': 'allow', 'pending': 'wait'}.get(approval_state, 'deny')


class ScheduleService:
    def __init__(self, store, *, enforcement_proven=False, clock=time.time):
        self.store, self.clock, self.enforcement_proven = store, clock, enforcement_proven
        self.coordinator = Coordinator(store, clock=clock)

    def create(self, principal: Principal, project_id: str, name: str, *, timezone: str, hour: int,
               minute: int = 0, timeout_seconds: int = 300, task_budget_microusd: int = 0,
               watcher_id: str | None = None) -> str:
        if not self.enforcement_proven:
            raise ScheduleDisabled('customer schedules are disabled until enforcement is proven')
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
                timeout_seconds,task_budget_microusd,watcher_id,state,created_epoch)
                VALUES (?,?,?,?,?,?,?,?,?,?,'active',?)''',
                        (principal.account_id, project_id, schedule_id, name, timezone, hour, minute,
                         timeout_seconds, task_budget_microusd, watcher_id, int(self.clock())))
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
