"""Scoped account restore and verified set retrieval. Nothing here writes to the live database.

`restore_account` builds a NEW database file from the live one, applies account A's backup rows by
explicit per-table rules, and proves before returning that every other account's rows are byte-for-byte
unchanged, that no ledger row was lost or rewritten, and that the file passes integrity and foreign-key
checks. The operator swaps it in with the app stopped. Anything unclassified aborts: adding a table
without deciding how it restores is a hard error, not a silent gap.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .backup import VERIFIERS, sha256_file
from .crypto import AgeCrypto

# Backup wins on conflict; rows created after the backup are kept.
RESTORE = ['projects', 'conversations', 'project_files', 'artifacts', 'memory_entries', 'memory_terms', 'skills', 'skill_versions',
           'watchers', 'schedules', 'watcher_notifications', 'objectives', 'objective_checkpoints', 'objective_children', 'connector_drafts']
# Live wins; only rows missing live are added (then neutralized).
MERGE = ['tasks', 'customer_requests', 'chat_messages', 'chat_deliveries', 'events', 'browser_profiles']
# Append-only history: add what is missing, never change or remove anything.
LEDGER = ['usage_entries', 'provider_receipts', 'task_reservations', 'audit_events', 'optimization_calls', 'optimization_activations', 'route_decisions',
          'accounts_audit', 'accounts_tombstone']
# Never restored: identity, billing and entitlements (current provider state wins), host-bound lifecycle, channels,
# tickets, streams, connector grants and every global (non-account) table.
LIVE = ['accounts', 'accounts_identity', 'accounts_operatorgrant', 'memberships', 'entitlements', 'deployments', 'operations',
        'lifecycle_cells', 'lifecycle_details', 'lifecycle_backups', 'lifecycle_slot', 'request_slot',
        'billing_customers', 'billing_checkout_sessions', 'billing_subscriptions', 'billing_invoices', 'billing_flags', 'billing_inbox',
        'billing_operations', 'connector_connections', 'connector_link_states', 'connector_operations', 'telegram_links',
        'telegram_link_codes', 'telegram_outbox', 'telegram_updates', 'download_tickets', 'event_streams',
        'accounts_actiontoken', 'accounts_emailjob', 'accounts_ratebucket', 'auth_group', 'auth_group_permissions', 'auth_permission',
        'auth_user', 'auth_user_groups', 'auth_user_user_permissions', 'django_content_type', 'django_migrations', 'django_session',
        'otp_totp_totpdevice', 'schema_migrations']
SCOPE = {**{t: 'restore' for t in RESTORE}, **{t: 'merge' for t in MERGE}, **{t: 'ledger' for t in LEDGER}, **{t: 'live' for t in LIVE}}
NON_TERMINAL_TASK = ('queued', 'running', 'waiting_for_approval', 'paused')
NON_TERMINAL_REQUEST = ('waiting', 'starting', 'running', 'uncertain')


class RestoreError(Exception): pass


def tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]


def columns(con, schema, table):
    return [r[1] for r in con.execute(f'PRAGMA {schema}.table_info("{table}")')]


def check_classified(con, schema='main'):
    unknown = sorted(t for t in [r[0] for r in con.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")] if t not in SCOPE)
    if unknown: raise RestoreError('unclassified tables (decide how they restore): ' + ', '.join(unknown))


def table_digest(con, schema, table, account=None, exclude=False):
    cols = columns(con, schema, table)
    has = 'account_id' in cols
    sql = f'SELECT * FROM {schema}."{table}"'
    args = ()
    if account is not None and has:
        sql += ' WHERE account_id IS NOT ?' if exclude else ' WHERE account_id = ?'
        args = (account,)
    elif account is not None and exclude is False:
        return None   # a global table has no per-account rows
    digest = hashlib.sha256()
    rows = sorted(repr(tuple(r)) for r in con.execute(sql, args))
    for r in rows: digest.update(r.encode())
    return digest.hexdigest(), len(rows)


def snapshot_others(con, schema, account):
    """Digest of everything that is not account A (all other accounts plus global tables)."""
    return {t: table_digest(con, schema, t, account, exclude=True) for t in tables(con) if t != 'sqlite_sequence'}


def quiesced(con, account):
    checks = [("SELECT 1 FROM tasks WHERE account_id=? AND state IN ('queued','running','waiting_for_approval','paused') LIMIT 1", 'a task is still active'),
              ("SELECT 1 FROM customer_requests WHERE account_id=? AND state IN ('waiting','starting','running','uncertain') LIMIT 1", 'a request is still active'),
              ("SELECT 1 FROM operations WHERE account_id=? AND state IN ('pending','running','uncertain') LIMIT 1", 'a lifecycle operation is unresolved')]
    for sql, why in checks:
        if con.execute(sql, (account,)).fetchone(): raise RestoreError('account is not quiesced: ' + why)


def restore_account(backup_db, live_db, account, out_db):
    backup_db, live_db, out_db = Path(backup_db), Path(live_db), Path(out_db)
    if out_db.exists(): raise RestoreError('refusing to overwrite an existing output file')
    src = sqlite3.connect(f'file:{live_db}?mode=ro', uri=True)
    dst = sqlite3.connect(f'file:{out_db}', uri=True)
    try: src.backup(dst)
    finally: src.close()
    os.chmod(out_db, 0o600)
    con = dst
    try:
        con.execute('PRAGMA foreign_keys=OFF')
        con.execute('ATTACH DATABASE ? AS b', (f'file:{backup_db}?mode=ro',))   # read-only: the backup is never modified
        check_classified(con, 'main'); check_classified(con, 'b')
        if not con.execute('SELECT 1 FROM main.accounts WHERE id=?', (account,)).fetchone(): raise RestoreError('account does not exist live')
        if not con.execute('SELECT 1 FROM b.accounts WHERE id=?', (account,)).fetchone(): raise RestoreError('account is not in the backup')
        quiesced(con, account)
        before_others = snapshot_others(con, 'main', account)
        before_ledger = {t: {tuple(r) for r in con.execute(f'SELECT * FROM main."{t}" WHERE account_id=?', (account,))} for t in LEDGER if 'account_id' in columns(con, 'main', t)}
        have = set(tables(con)); backup_have = {r[0] for r in con.execute("SELECT name FROM b.sqlite_master WHERE type='table'")}
        tomb = set()
        if 'accounts_tombstone' in have:
            tomb = {r[0] for r in con.execute("SELECT object_id FROM main.accounts_tombstone WHERE account_id=? AND kind='conversation'", (account,))}
        report = {'restored': {}, 'added': {}, 'ledger_added': {}, 'skipped_tombstoned_conversations': len(tomb), 'neutralized': {}}
        existing_reservations = {r[0] for r in con.execute('SELECT task_id FROM main.task_reservations WHERE account_id=?', (account,))} if 'task_reservations' in have else set()
        for table in RESTORE + MERGE + LEDGER:
            if table not in have or table not in backup_have: continue
            live_cols, back_cols = columns(con, 'main', table), columns(con, 'b', table)
            common = [c for c in live_cols if c in back_cols]
            if 'account_id' not in common: continue
            where, args = 'account_id = ?', [account]
            if tomb and 'conversation_id' in common:
                where += f' AND conversation_id NOT IN ({",".join("?" * len(tomb))})'; args += sorted(tomb)
            if tomb and table == 'conversations':
                where += f' AND id NOT IN ({",".join("?" * len(tomb))})'; args += sorted(tomb)
            mode = SCOPE[table]
            # Global autoincrement keys must never carry over: another account may own that number live.
            insert_cols = [c for c in common if not (table == 'chat_messages' and c == 'id') and not (table == 'customer_requests' and c == 'sequence')]
            colsql = ','.join(f'"{c}"' for c in insert_cols)
            before = con.execute(f'SELECT count(*) FROM main."{table}" WHERE account_id=?', (account,)).fetchone()[0]
            verb = 'INSERT OR REPLACE' if mode == 'restore' else 'INSERT OR IGNORE'
            if table == 'chat_messages':
                con.execute(f'''INSERT INTO main.chat_messages({colsql}) SELECT {colsql} FROM b.chat_messages s WHERE {where}
                    AND NOT EXISTS (SELECT 1 FROM main.chat_messages m WHERE m.account_id=s.account_id AND m.conversation_id=s.conversation_id
                    AND m.provenance=s.provenance AND m.content=s.content AND m.created_at=s.created_at AND coalesce(m.native_message_id,'')=coalesce(s.native_message_id,''))''', args)
            else:
                con.execute(f'{verb} INTO main."{table}"({colsql}) SELECT {colsql} FROM b."{table}" WHERE {where}', args)
            after = con.execute(f'SELECT count(*) FROM main."{table}" WHERE account_id=?', (account,)).fetchone()[0]
            bucket = {'restore': 'restored', 'merge': 'added', 'ledger': 'ledger_added'}[mode]
            report[bucket][table] = after - before if mode != 'restore' else con.execute(f'SELECT count(*) FROM b."{table}" WHERE {where}', args).fetchone()[0]
        # Neutralize anything that could act on its own: nothing restored may start, send or spend by itself.
        n = report['neutralized']
        cur = lambda sql, *a: con.execute(sql, a).rowcount
        n['schedules_paused'] = cur("UPDATE main.schedules SET state='paused' WHERE account_id=? AND state!='paused'", account) if 'schedules' in have else 0
        n['watchers_paused'] = cur("UPDATE main.watchers SET state='paused' WHERE account_id=? AND state!='paused'", account) if 'watchers' in have else 0
        n['objectives_flagged'] = cur("UPDATE main.objectives SET app_state='needs_reconciliation' WHERE account_id=? AND app_state='active'", account) if 'objectives' in have else 0
        n['browser_profiles_revoked'] = cur("UPDATE main.browser_profiles SET state='revoked',credential_ref=NULL,session_ref=NULL WHERE account_id=?", account) if 'browser_profiles' in have else 0
        if 'tasks' in have:
            n['tasks_blocked'] = cur(f"UPDATE main.tasks SET state='blocked' WHERE account_id=? AND state IN {NON_TERMINAL_TASK!r} AND id IN (SELECT id FROM b.tasks WHERE account_id=?)", account, account)
        if 'customer_requests' in have:
            n['requests_cancelled'] = cur(f"UPDATE main.customer_requests SET state='cancelled',lease_owner=NULL,lease_until=NULL WHERE account_id=? AND state IN {NON_TERMINAL_REQUEST!r} AND id IN (SELECT id FROM b.customer_requests WHERE account_id=?)", account, account)
        if 'chat_deliveries' in have:
            n['deliveries_aborted'] = cur("UPDATE main.chat_deliveries SET state='aborted' WHERE account_id=? AND state IN ('pending','uncertain') AND (request_id,attempt) IN (SELECT request_id,attempt FROM b.chat_deliveries WHERE account_id=?)", account, account)
        if 'task_reservations' in have:
            # A reservation brought back from the backup must not hold allowance for work that will not run.
            marks = ','.join('?' * len(existing_reservations)) or "''"
            n['reservations_closed'] = cur(f"UPDATE main.task_reservations SET state='settled' WHERE account_id=? AND state IN ('active','uncertain') AND task_id NOT IN ({marks})",
                                           account, *sorted(existing_reservations))
        con.commit()
        con.execute('DETACH DATABASE b')
        # ---- proofs
        after_others = snapshot_others(con, 'main', account)
        if after_others != before_others:
            changed = sorted(t for t in before_others if before_others[t] != after_others[t])
            raise RestoreError('another account or a global table changed: ' + ', '.join(changed))
        for t, rows in before_ledger.items():
            now_rows = {tuple(r) for r in con.execute(f'SELECT * FROM main."{t}" WHERE account_id=?', (account,))}
            if not rows <= now_rows: raise RestoreError(f'ledger rows were lost or rewritten in {t}')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RestoreError('integrity check failed')
        con.execute('PRAGMA foreign_keys=ON')
        violations = con.execute('PRAGMA foreign_key_check').fetchall()
        if violations: raise RestoreError(f'{len(violations)} foreign key violations')
        report['other_accounts_unchanged'] = True; report['ledger_intact'] = True; report['billing_requires_reconcile'] = True
        return report
    except BaseException:
        con.close(); out_db.unlink(missing_ok=True); raise
    finally:
        try: con.close()
        except Exception: pass
