"""Privacy-safe diagnostics for support and incident triage.

Built from counts, states, error codes and hashed tenant labels. It never reads message text, files,
memory, prompts, artifacts, tokens or tenant references, and every string passes the alert sanitizer.
Support sees which account hash is in what state and why a task failed, not what the customer did.
"""
import hashlib
import json
import sqlite3
import time

from .alerts import clean


def label(account_id):
    return hashlib.sha256(('account-label:' + account_id).encode()).hexdigest()[:12]


def collect(app_db, *, clock=time.time, monitor_status=None, backup_status=None):
    con = sqlite3.connect(f'file:{app_db}?mode=ro', uri=True)
    now = int(clock())
    def rows(sql, *a): return con.execute(sql, a).fetchall()
    try:
        accounts = []
        for (account,) in rows("SELECT id FROM accounts WHERE status!='deleted' ORDER BY id"):
            tasks = dict(rows('SELECT state,count(*) FROM tasks WHERE account_id=? GROUP BY state', account))
            ops = [{'kind': k, 'state': s, 'error': e or '', 'age_s': now - int(c or now)} for k, s, e, c in rows(
                """SELECT o.kind,o.state,d.error_code,strftime('%s',o.created_at) FROM operations o JOIN lifecycle_details d ON d.account_id=o.account_id AND d.operation_id=o.id
                   WHERE o.account_id=? ORDER BY o.created_at DESC LIMIT 5""", account)]
            cell = rows('SELECT observed_state FROM lifecycle_cells WHERE account_id=?', account)
            ent = rows('SELECT id,status FROM entitlements WHERE account_id=? ORDER BY valid_until DESC LIMIT 1', account)
            accounts.append({'account': label(account), 'tasks': tasks, 'recent_operations': ops, 'cell': cell[0][0] if cell else 'none',
                             'entitlement': {'id': ent[0][0], 'status': ent[0][1]} if ent else None,
                             'failed_tasks_24h': rows("SELECT count(*) FROM tasks WHERE account_id=? AND state IN ('failed','blocked','budget_exhausted') AND created_at>=datetime(?,'unixepoch','-1 day')", account, now)[0][0]})
        data = {'generated_epoch': now, 'accounts': accounts,
                'queue': {'uncertain_operations': rows("SELECT count(*) FROM operations WHERE state='uncertain'")[0][0],
                          'pending_operations': rows("SELECT count(*) FROM operations WHERE state='pending'")[0][0]},
                'monitor': {'overall': (monitor_status or {}).get('overall'), 'failing': [c['check'] for c in (monitor_status or {}).get('checks', []) if c['status'] in ('warn', 'crit', 'unknown')]},
                'backup': {k: (backup_status or {}).get(k) for k in ('last_success_epoch', 'last_complete', 'offsite_copy')}}
    finally:
        con.close()
    return json.loads(clean(json.dumps(data), 200000))   # one more pass over the whole document
