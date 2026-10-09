"""Quiet watchers (Phase 10, NATIVE-06).

A cheap deterministic observation (caller supplies the observed content
hash) is compared with the last observed state. Unchanged => zero model
calls and no notification. Changed => escalate only if the per-task budget
admission callback allows it; notifications are deduplicated by observed
hash, so restarts and repeated checks never double-notify. Creating a watcher
is idempotent by (project, name), so restarts do not duplicate jobs.
"""
from __future__ import annotations
import json
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

MAX_WATCHERS = 20
MIN_INTERVAL = 300


class WatcherService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def ensure(self, principal: Principal, project_id: str, name: str, check_spec: dict,
               interval_seconds: int = 3600) -> str:
        identifier(project_id)
        if type(interval_seconds) is not int or interval_seconds < MIN_INTERVAL:
            raise ValueError('interval below minimum')
        if not isinstance(name, str) or not 1 <= len(name) <= 80 or not isinstance(check_spec, dict):
            raise ValueError('invalid watcher')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT id FROM watchers WHERE account_id=? AND project_id=? AND name=?',
                              (principal.account_id, project_id, name)).fetchone()
            if row:
                return row['id']
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            if con.execute('SELECT count(*) FROM watchers WHERE account_id=?',
                           (principal.account_id,)).fetchone()[0] >= MAX_WATCHERS:
                raise Conflict('watcher limit reached')
            watcher_id = uuid.uuid4().hex
            con.execute('''INSERT INTO watchers(account_id,project_id,id,name,check_spec,interval_seconds,
                state,created_epoch) VALUES (?,?,?,?,?,?,'active',?)''',
                        (principal.account_id, project_id, watcher_id, name,
                         json.dumps(check_spec, sort_keys=True), interval_seconds, int(self.clock())))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, watcher_id,
                                    'watcher.create', 'completed')
            return watcher_id

    def observe(self, principal: Principal, watcher_id: str, observed_hash: str, *, admit) -> dict:
        """Record one deterministic check. ``admit()`` -> bool is the task-budget
        and authority admission for the model escalation; it is called only on change."""
        if not isinstance(observed_hash, str) or len(observed_hash) != 64:
            raise ValueError('observed hash must be sha256 hex')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT state,last_observed_hash FROM watchers WHERE account_id=? AND id=?''',
                              (principal.account_id, identifier(watcher_id))).fetchone()
            if not row:
                raise NotFound('unavailable')
            now = int(self.clock())
            con.execute('UPDATE watchers SET last_checked_epoch=? WHERE account_id=? AND id=?',
                        (now, principal.account_id, watcher_id))
            if row['state'] != 'active':
                return {'changed': False, 'escalate': False, 'model_calls': 0, 'reason': 'paused'}
            if row['last_observed_hash'] == observed_hash:
                return {'changed': False, 'escalate': False, 'model_calls': 0, 'reason': 'unchanged'}
            if row['last_observed_hash'] is None:
                con.execute('UPDATE watchers SET last_observed_hash=? WHERE account_id=? AND id=?',
                            (observed_hash, principal.account_id, watcher_id))
                return {'changed': False, 'escalate': False, 'model_calls': 0, 'reason': 'baseline'}
            seen = con.execute('''SELECT state FROM watcher_notifications WHERE account_id=? AND watcher_id=?
                AND observed_hash=?''', (principal.account_id, watcher_id, observed_hash)).fetchone()
            if seen and seen['state'] != 'denied':
                return {'changed': True, 'escalate': False, 'model_calls': 0, 'reason': 'duplicate'}
            allowed = bool(admit())
            if not seen:
                con.execute('INSERT INTO watcher_notifications VALUES (?,?,?,?,?)',
                            (principal.account_id, watcher_id, observed_hash,
                             'pending' if allowed else 'denied', now))
            elif allowed:
                con.execute('''UPDATE watcher_notifications SET state='pending' WHERE account_id=?
                    AND watcher_id=? AND observed_hash=?''', (principal.account_id, watcher_id, observed_hash))
            if allowed:
                con.execute('UPDATE watchers SET last_observed_hash=? WHERE account_id=? AND id=?',
                            (observed_hash, principal.account_id, watcher_id))
            return {'changed': True, 'escalate': allowed, 'model_calls': 0,
                    'reason': 'changed' if allowed else 'admission_denied'}

    def mark_delivered(self, principal: Principal, watcher_id: str, observed_hash: str) -> None:
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            cur = con.execute('''UPDATE watcher_notifications SET state='delivered' WHERE account_id=?
                AND watcher_id=? AND observed_hash=? AND state='pending' ''',
                              (principal.account_id, watcher_id, observed_hash))
            if cur.rowcount != 1:
                raise NotFound('unavailable')
