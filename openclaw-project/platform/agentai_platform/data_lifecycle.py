"""Leaving with your data, and leaving completely (roadmap #19 export, #20 deletion, #21 offboarding).

Three kinds of JOB, all rows of `account_jobs`, all moved by `AccountJobs.tick()` (the `account_jobs` command on a timer). Each job is durable: its `steps_json` is a list of
checkpoints, one per store that was handled, so a job that is interrupted carries on from the last finished step and never repeats one.

EXPORT writes one archive: a folder of JSON files plus the original files, with `manifest.json` listing every kind, how many items, and a hash of each file. The schema is
documented in platform/DATA_EXPORT.md. Tokens, keys and sealed secrets are never in it. It is delivered by a single-use link that expires; the archive itself is deleted
after the time the retention table gives it.

DELETION is driven by the retention table (retention.py): every kind of data has a delete step, every store outside the database has an adapter, and the job ends with a
VERIFICATION SCAN of every store for the account id. What remains by design is stated to the customer: the empty account record (so its id is never reused), the line of
the security record that says it was deleted, the amounts and dates accounting requires, and backups until they expire.

OFFBOARDING is the guided way out: stop the work, offer the export and wait for the choice, end every connection, cancel the subscription, wait out a cooling-off period
the customer can cancel, delete, and confirm by email with the deletion report.

Nothing here deletes anything unless a customer (or an operator, for them) started the job, and the deletion itself never starts before the cooling-off has passed.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
import zipfile

from . import retention
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

COOLING_OFF_SECONDS = 7 * 86400
TICKET_SECONDS = 900
LEASE_SECONDS = 300
SCHEMA_VERSION = 1
OPEN = ('requested', 'running', 'waiting')

# What an export holds: (file in the archive, what it is, table, columns never exported). Every table is read `WHERE account_id=?`; a column not listed is exported as it is.
# A table that is not here is not exported (see NEVER_EXPORTED for why each one is left out).
SECRET_COLUMNS = {'connector_connections': ('secret_ref', 'refresh_lock_epoch'), 'mcp_connections': ('secret_json', 'oauth_state_hash', 'oauth_actor', 'oauth_session', 'oauth_browser_hash'),
                  'vault_items': ('kid', 'nonce', 'ciphertext'), 'browser_profiles': ('credential_ref', 'session_ref'), 'customer_requests': ('lease_owner', 'payload_hash', 'idempotency_key'),
                  'conversations': ('native_session_ref',)}
EXPORT = (
    ('conversations/conversations.json', 'Your chats', 'conversations'), ('conversations/messages.json', 'Every message in them', 'chat_messages'),
    ('conversations/projects.json', 'Projects', 'projects'), ('tasks/tasks.json', 'Tasks you asked for and how each ended', 'customer_requests'),
    ('tasks/plans.json', 'Plans, tables and forms shown in chats', 'ui_blocks'), ('tasks/documents.json', 'Documents and cards shown in chats', 'data_blocks'),
    ('tasks/plan_revisions.json', 'Versions of plans', 'plan_revisions'), ('tasks/plan_phase_runs.json', 'How each phase of a plan went', 'plan_phase_runs'),
    ('tasks/plan_proposals.json', 'Suggested changes to plans', 'plan_proposals'), ('tasks/long_jobs.json', 'Long jobs', 'objectives'),
    ('tasks/long_job_checkpoints.json', 'What long jobs did', 'objective_checkpoints'), ('tasks/browser_runs.json', 'Browser tasks', 'browse_runs'),
    ('files/files.json', 'Files your assistant made (the files themselves are in files/made/)', 'artifacts'), ('files/uploads.json', 'Files you uploaded (in files/uploaded/)', 'project_files'),
    ('files/folders.json', 'The folders you made', 'file_folders'), ('files/places.json', 'Which folder each file is in, and the names you gave them', 'file_places'),
    ('memory/project_memory.json', 'Project memory', 'memory_entries'), ('memory/long_term_memory.json', 'Long-term memory notes', 'longterm_memories'),
    ('memory/saved_choices.json', 'Saved choices', 'saved_choices'), ('memory/skills.json', 'Skills', 'skills'), ('memory/skill_versions.json', 'Versions of skills', 'skill_versions'),
    ('automation/schedules.json', 'Schedules', 'schedules'), ('automation/schedule_runs.json', 'What each schedule did', 'schedule_runs'), ('automation/watchers.json', 'Watchers', 'watchers'),
    ('connections/connections.json', 'Connected services (never their tokens)', 'connector_connections'), ('connections/grants.json', 'What each connection may reach', 'connector_grants'),
    ('connections/remote_tools.json', 'Remote tool servers (never their credentials)', 'mcp_connections'), ('connections/remote_tool_choices.json', 'Which remote tools are allowed', 'mcp_tool_choices'),
    ('connections/automatic_approvals.json', 'Changes you allowed without asking', 'action_auto_approvals'), ('connections/removed.json', 'Connections that were removed, with what was stopped', 'connector_revocations'),
    ('connections/saved_logins.json', 'Saved logins and cards (names only, never the secrets)', 'vault_items'),
    ('actions/actions.json', 'Changes prepared or made in connected services', 'actions'), ('actions/workflows.json', 'Workflows', 'workflows'), ('actions/questions.json', 'Questions and approvals asked of you', 'handoffs'),
    ('mail/messages.json', 'The copy of your connected mail that Lumina holds: who, subject, preview, and the text of messages that were opened', 'hub_messages'),
    ('calendar/calendars.json', 'Your connected calendars and how you set them up', 'hub_calendars'), ('calendar/events.json', 'The copy of your calendar events that Lumina holds', 'hub_events'),
    ('settings/mail_and_calendar.json', 'Your mail and calendar settings', 'hub_settings'),
    ('settings/spending_limits.json', 'Your spending limits', 'spend_limits'), ('settings/plan_settings.json', 'Per-plan settings', 'plan_settings'),
    ('usage/receipts.json', 'What each task cost', 'provider_receipts'), ('usage/usage.json', 'Usage entries', 'usage_entries'),
)
NEVER_EXPORTED = {
    'connector_secrets': 'sealed tokens', 'connector_link_states': 'unfinished sign-in attempts', 'download_tickets': 'one-time links', 'telegram_link_codes': 'one-time codes',
    'event_streams': 'stream positions', 'events': 'the step-by-step timeline (kept 30 days; the results are in the chats)', 'chat_deliveries': 'delivery bookkeeping',
    'hub_threads': 'the list of threads (made from the messages in mail/messages.json)', 'hub_sync': 'sync bookkeeping',
    'tasks': 'bookkeeping (the tasks are in tasks/tasks.json)', 'task_reservations': 'budget bookkeeping', 'entitlements': 'plan bookkeeping',
}
# Deletion: rows of these tables stay. Everything else that has an `account_id` column goes.
KEPT_AT_DELETION = ('accounts', 'memberships', 'audit_events', 'account_jobs', 'financial_records', 'billing_customers', 'billing_checkout_sessions', 'billing_subscriptions',
                    'billing_invoices', 'billing_flags', 'billing_inbox', 'billing_operations', 'entitlements')
REMAINS_BY_DESIGN = (
    'An empty record of the account, so its id can never be reused.',
    'The line of the security record that says the account was deleted, and when. Older lines expire after 180 days.',
    'The amounts and dates of what was charged, as accounting rules require. They link to no chat, task or file.',
    'Encrypted backups made before the deletion, until they expire (at most 30 days). A backup is never used to bring deleted data back.',
)


# Tables the sign-in layer owns (the web framework's own, in the same database file). They are handled by the `identity` adapter, which knows what must stay (the security
# record, the tombstone) and erases the address LAST, after the confirmation email has gone out. This module never touches them.
IDENTITY_PREFIXES = ('accounts_', 'auth_', 'django_', 'otp_')


def _tables_with_account(con):
    out = []
    # Read completely before the next statement: the web app's connection has one cursor, and a second statement would end this one's rows.
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE ? ORDER BY name", ('sqlite_%',)).fetchall():
        if not name.startswith(IDENTITY_PREFIXES) and any(c[1] == 'account_id' for c in con.execute(f'PRAGMA table_info("{name}")').fetchall()):
            out.append(name)
    return out


class AccountJobs:
    """`storage`: storage.RootStore or None (no file store on this host: there are then no files to export or delete). `adapters`: the stores outside the database, each a
    callable or None: {'memory': fn(account)->detail, 'model_key': fn(account), 'custody': fn(account)->count, 'cell': fn(account)->'done'|'waiting', 'identity': fn(account),
    'billing': fn(account)->detail, 'connections': fn(account)->count, 'mail': fn(account, actor, report), 'scan': fn(account)->{store: remaining}}. A missing adapter is
    recorded as `not_on_this_host`, never silently skipped."""

    def __init__(self, store, *, storage=None, adapters=None, signing_key=b'', clock=time.time, cooling_off=COOLING_OFF_SECONDS):
        self.store, self.storage, self.adapters, self.key, self.clock, self.cooling_off = store, storage, adapters or {}, signing_key, clock, cooling_off
        self.coordinator = Coordinator(store, clock=clock)

    # -- views -------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def public(row) -> dict:
        return {'id': row['id'], 'kind': row['kind'], 'state': row['state'], 'scope': json.loads(row['scope_json']), 'steps': json.loads(row['steps_json']),
                'report': json.loads(row['report_json']) if row['report_json'] else None, 'archive_bytes': row['archive_bytes'], 'has_archive': bool(row['archive_ref']),
                'waiting_for': row['waiting_for'], 'not_before_epoch': row['not_before_epoch'], 'created_epoch': row['created_epoch'], 'finished_epoch': row['finished_epoch']}

    def _job(self, con, account_id, job_id):
        row = con.execute('SELECT * FROM account_jobs WHERE account_id=? AND id=?', (account_id, str(job_id))).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    def listing(self, principal: Principal, kind=None) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('SELECT * FROM account_jobs WHERE account_id=?' + (' AND kind=?' if kind else '') + ' ORDER BY created_epoch DESC LIMIT 20',
                               (principal.account_id, kind) if kind else (principal.account_id,)).fetchall()
            return [self.public(r) for r in rows]

    def get(self, principal: Principal, job_id: str) -> dict:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return self.public(self._job(con, principal.account_id, job_id))

    def _new(self, con, account_id, actor_id, kind, scope, *, state='requested', not_before=None, waiting_for=None) -> str:
        now, job = int(self.clock()), uuid.uuid4().hex
        con.execute('''INSERT INTO account_jobs(id,account_id,actor_id,kind,scope_json,state,not_before_epoch,waiting_for,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (job, account_id, actor_id, kind, json.dumps(scope, sort_keys=True), state, not_before, waiting_for, now, now))
        return job

    def _step(self, job_id, name, detail=None, state='done'):
        """One checkpoint: recorded once. -> False when this step was already done (the job is being resumed)."""
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT steps_json FROM account_jobs WHERE id=?', (job_id,)).fetchone()
            steps = json.loads(row['steps_json'])
            if any(s['step'] == name and s['state'] == 'done' for s in steps):
                return False
            steps = [s for s in steps if s['step'] != name] + [{'step': name, 'state': state, 'detail': detail, 'at': int(self.clock())}]
            con.execute('UPDATE account_jobs SET steps_json=?,updated_epoch=? WHERE id=?', (json.dumps(steps), int(self.clock()), job_id))
        return True

    def _done(self, job_id, name) -> bool:
        with self.store.connect() as con:
            return any(s['step'] == name and s['state'] == 'done' for s in json.loads(con.execute('SELECT steps_json FROM account_jobs WHERE id=?', (job_id,)).fetchone()['steps_json']))

    def _finish(self, job_id, state, report=None):
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            con.execute('UPDATE account_jobs SET state=?,report_json=coalesce(?,report_json),waiting_for=NULL,lease_until=0,finished_epoch=?,updated_epoch=? WHERE id=?',
                        (state, json.dumps(report) if report is not None else None, now if state in ('completed', 'failed', 'cancelled') else None, now, job_id))

    def _adapter(self, name, *args):
        """-> (detail, ok). A store this host does not have is said so; a store that failed is said so and the job tries it again."""
        fn = self.adapters.get(name)
        if fn is None:
            return 'not_on_this_host', True
        try:
            return fn(*args), True
        except Exception as error:
            return 'failed:' + type(error).__name__, False

    # -- export (#19) --------------------------------------------------------------------------------------------------------------------------
    def request_export(self, principal: Principal, *, organization=False) -> dict:
        with self.coordinator.transaction() as con:
            require(principal, 'organization.export' if organization else 'data.export', con=con)
            if con.execute(f"SELECT 1 FROM account_jobs WHERE account_id=? AND kind='export' AND state IN ({','.join('?' * len(OPEN))})", (principal.account_id, *OPEN)).fetchone():
                raise Conflict('an export is already being made')
            accounts = [principal.account_id]
            if organization:
                from .permissions import organization_of
                accounts = [r[0] for r in con.execute("SELECT account_id FROM organization_members WHERE organization_id=? AND status='active' ORDER BY created_epoch",
                                                      (organization_of(con, principal.account_id),))] or accounts
            job = self._new(con, principal.account_id, principal.actor_id, 'export', {'accounts': accounts, 'organization': bool(organization)})
            self.coordinator._audit(con, principal.account_id, principal.actor_id, job, 'data.export.request', 'completed')
            return self.public(self._job(con, principal.account_id, job))

    def _export_rows(self, con, table, account):
        skip = set(SECRET_COLUMNS.get(table, ()))
        columns = [c[1] for c in con.execute(f'PRAGMA table_info("{table}")') if c[1] not in skip and c[2].upper() != 'BLOB']
        if not columns:
            return []
        return [dict(zip(columns, row)) for row in con.execute(f'SELECT {",".join(chr(34) + c + chr(34) for c in columns)} FROM "{table}" WHERE account_id=?', (account,))]

    def run_export(self, job_id: str):
        with self.store.connect() as con:
            job = con.execute('SELECT * FROM account_jobs WHERE id=?', (job_id,)).fetchone()
        scope, owner = json.loads(job['scope_json']), job['account_id']
        if self.storage is None:
            return self._finish(job_id, 'failed', {'reason': 'no file store on this host'})
        parts = [owner, 'exports', job_id + '.zip']
        self.storage.delete(parts)                                   # a half-written archive from an interrupted run is started again from nothing
        fd = self.storage._open_chain(parts, create_dirs=True, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        manifest, digest = {'schema_version': SCHEMA_VERSION, 'made_epoch': int(self.clock()), 'accounts': [], 'files': [], 'not_included': NEVER_EXPORTED}, hashlib.sha256()
        with os.fdopen(fd, 'wb') as handle:
            os.fchmod(handle.fileno(), 0o600)
            with zipfile.ZipFile(handle, 'w', zipfile.ZIP_DEFLATED) as archive:
                def put(name, data: bytes, kind, count):
                    archive.writestr(name, data)
                    manifest['files'].append({'file': name, 'what': kind, 'items': count, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
                for account in scope['accounts']:
                    base = f'members/{account}/' if scope.get('organization') else ''
                    manifest['accounts'].append(account)
                    with self.store.connect() as con:
                        present = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        for name, kind, table in EXPORT:
                            if table not in present:
                                continue
                            rows = self._export_rows(con, table, account)
                            put(base + name, json.dumps(rows, indent=1, ensure_ascii=False, default=str).encode(), kind, len(rows))
                        made = [dict(r) for r in con.execute('SELECT id,version,display_name,storage_ref FROM artifacts WHERE account_id=? ORDER BY id,version', (account,))]
                        uploads = [dict(r) for r in con.execute("SELECT id,display_name,storage_ref FROM project_files WHERE account_id=? AND state='scanned' ORDER BY id", (account,))]
                    for item, folder in [(m, f'files/made/{m["id"]}/v{m["version"]}/') for m in made] + [(u, f'files/uploaded/{u["id"]}/') for u in uploads]:
                        try:
                            data = self.storage.read_private([account] + item['storage_ref'].split('/'))
                        except (OSError, ValueError):
                            manifest['files'].append({'file': base + folder + item['display_name'], 'what': 'a file that could not be read', 'items': 0, 'bytes': 0, 'sha256': None})
                            continue
                        put(base + folder + os.path.basename(item['display_name'])[:200], data, 'file', 1)
                    self._step(job_id, 'account:' + account, {'files': len(made) + len(uploads)})
                archive.writestr('manifest.json', json.dumps(manifest, indent=1).encode())
                archive.writestr('README.txt', ('Your Lumina data export.\n\nmanifest.json lists every file in this archive, what it is, how many items it holds and its SHA-256 hash.\n'
                                                'The layout and every field are described in DATA_EXPORT.md of the Lumina platform (schema version %d).\n'
                                                'Tokens, passwords, keys and other secrets are never part of an export.\n' % SCHEMA_VERSION).encode())
        size = self.storage.size(parts)
        with self.storage.open_private(parts) as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                digest.update(chunk)
        with self.coordinator.transaction() as con:
            con.execute("UPDATE account_jobs SET archive_ref=?,archive_bytes=?,archive_sha256=? WHERE id=?", ('exports/' + job_id + '.zip', size, digest.hexdigest(), job_id))
        self._finish(job_id, 'completed', {'files': len(manifest['files']), 'bytes': size, 'sha256': digest.hexdigest(), 'kept_days': retention.BY_KEY['exports'].days})

    def _ticket_hash(self, ticket):
        return hmac.new(self.key, ticket.encode(), hashlib.sha256).hexdigest()

    def export_ticket(self, principal: Principal, job_id: str) -> dict:
        """A single-use link to the archive that expires. The link is the only thing that can fetch it."""
        if len(self.key) < 32:
            raise Conflict('downloads are not set up on this host')
        ticket = secrets.token_urlsafe(32)
        with self.coordinator.transaction() as con:
            require(principal, 'data.export', con=con)
            row = self._job(con, principal.account_id, job_id)
            if row['kind'] != 'export' or row['state'] != 'completed' or not row['archive_ref']:
                raise Conflict('this export has no archive to download')
            con.execute('UPDATE account_jobs SET ticket_hash=?,ticket_expires_epoch=? WHERE id=?', (self._ticket_hash(ticket), int(self.clock()) + TICKET_SECONDS, row['id']))
            return {'path': f'/v1/exports/{row["id"]}/download?ticket={ticket}', 'expires_in': TICKET_SECONDS, 'size_bytes': row['archive_bytes'], 'sha256': row['archive_sha256']}

    def consume_export_ticket(self, job_id: str, ticket: str):
        """-> (storage parts, size). Single use; an expired or used link fetches nothing."""
        if not isinstance(ticket, str) or not ticket or len(self.key) < 32:
            raise NotFound('unavailable')
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT * FROM account_jobs WHERE id=? AND kind=?', (str(job_id), 'export')).fetchone()
            if (not row or not row['archive_ref'] or not row['ticket_hash'] or not hmac.compare_digest(row['ticket_hash'], self._ticket_hash(ticket))
                    or (row['ticket_expires_epoch'] or 0) <= self.clock()):
                raise NotFound('unavailable')
            con.execute('UPDATE account_jobs SET ticket_hash=NULL,ticket_expires_epoch=NULL WHERE id=?', (row['id'],))
            return [row['account_id']] + row['archive_ref'].split('/'), row['archive_bytes']

    # -- deletion (#20) ------------------------------------------------------------------------------------------------------------------------
    def delete_conversation(self, principal: Principal, conversation_id: str) -> dict:
        """Partial deletion: one chat. Its messages, plans, shown results and timeline are removed. Where files it made are still kept, an empty record of the chat stays so
        they still belong somewhere; otherwise every row of it goes. -> what was removed (counts)."""
        account = principal.account_id
        with self.coordinator.transaction() as con:
            if True:
                require(principal, 'data.delete', con=con)
                row = con.execute('SELECT id,parent_id FROM conversations WHERE account_id=? AND id=? AND deleted_epoch IS NULL', (account, str(conversation_id))).fetchone()
                if not row or row['parent_id']:
                    raise NotFound('unavailable')
                if con.execute("SELECT 1 FROM customer_requests WHERE account_id=? AND conversation_id IN (SELECT id FROM conversations WHERE account_id=? AND (id=? OR parent_id=?)) AND state IN ('waiting','starting','running','uncertain')",
                               (account, account, row['id'], row['id'])).fetchone():
                    raise Conflict('stop the running task first')
                ids = [row['id']] + [r[0] for r in con.execute('SELECT id FROM conversations WHERE account_id=? AND parent_id=?', (account, row['id']))]      # the chat and its hidden lanes
                marks = ','.join('?' * len(ids))
                requests = [r[0] for r in con.execute(f'SELECT id FROM customer_requests WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))]
                removed = {}
                def run(name, sql, args):
                    removed[name] = removed.get(name, 0) + con.execute(sql, args).rowcount
                con.execute('PRAGMA defer_foreign_keys=ON')
                blocks = [r[0] for r in con.execute(f'SELECT id FROM ui_blocks WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))]
                for chunk in (blocks[i:i + 400] for i in range(0, len(blocks), 400)):
                    for table in ('plan_phase_runs', 'plan_revisions', 'plan_proposals', 'plan_settings', 'plan_launches'):
                        run('plans', f'DELETE FROM {table} WHERE account_id=? AND block_id IN ({",".join("?" * len(chunk))})', (account, *chunk))
                for chunk in (requests[i:i + 400] for i in range(0, len(requests), 400)):
                    m = ','.join('?' * len(chunk))
                    run('timeline', f'DELETE FROM events WHERE account_id=? AND task_id IN ({m})', (account, *chunk))
                    run('deliveries', f'DELETE FROM chat_deliveries WHERE account_id=? AND request_id IN ({m})', (account, *chunk))
                    for table, column in (('actions', 'request_id'), ('handoffs', 'request_id'), ('workflows', 'request_id'), ('mcp_calls', 'request_id'), ('browse_steps', 'request_id'),
                                          ('browse_sessions', 'request_id'), ('browse_runs', 'request_id'), ('location_requests', 'request_id'), ('spend_marks', 'request_id'), ('request_slots', 'request_id')):
                        try:
                            run('task_records', f'DELETE FROM {table} WHERE account_id=? AND {column} IN ({m})', (account, *chunk))
                        except Exception as error:
                            if 'no such' not in str(error):
                                raise
                run('messages', f'DELETE FROM chat_messages WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                run('shown', f'DELETE FROM data_blocks WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                run('shown', f'DELETE FROM ui_blocks WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                run('long_jobs', f'UPDATE objectives SET conversation_id=NULL,cancelled=1,app_state=\'cancelled\' WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                files = con.execute(f'SELECT count(*) FROM artifacts WHERE account_id=? AND task_id IN (SELECT id FROM tasks WHERE account_id=? AND conversation_id IN ({marks}))',
                                    (account, account, *ids)).fetchone()[0]
                costs = con.execute(f'''SELECT (SELECT count(*) FROM provider_receipts WHERE account_id=? AND task_id IN (SELECT id FROM tasks WHERE account_id=? AND conversation_id IN ({marks})))
                    + (SELECT count(*) FROM usage_entries WHERE account_id=? AND task_id IN (SELECT id FROM tasks WHERE account_id=? AND conversation_id IN ({marks})))
                    + (SELECT count(*) FROM task_reservations WHERE account_id=? AND task_id IN (SELECT id FROM tasks WHERE account_id=? AND conversation_id IN ({marks})))''',
                                    (account, account, *ids, account, account, *ids, account, account, *ids)).fetchone()[0]
                now = int(self.clock())
                if files or costs:
                    # Files it made are still in Files, and what its tasks cost is still on the account: an empty record of the chat and its tasks stays for those to hang on.
                    run('task_text', f"UPDATE customer_requests SET message='[deleted]',result=NULL,outcome_note=NULL,context_json=NULL WHERE account_id=? AND conversation_id IN ({marks})", (account, *ids))
                    con.execute(f"UPDATE conversations SET deleted_epoch=?,title=NULL,native_session_ref=NULL,archived_epoch=coalesce(archived_epoch,?) WHERE account_id=? AND id IN ({marks})", (now, now, account, *ids))
                else:
                    run('tasks', f'DELETE FROM customer_requests WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                    run('tasks', f'DELETE FROM tasks WHERE account_id=? AND conversation_id IN ({marks})', (account, *ids))
                    run('chat', f'DELETE FROM conversations WHERE account_id=? AND id IN ({marks})', (account, *ids))
                self.coordinator._audit(con, account, principal.actor_id, row['id'], 'data.delete.conversation', 'completed')
        return {'conversation_id': row['id'], 'removed': removed, 'files_kept': files, 'kept_empty_record': bool(files or costs)}

    def request_deletion(self, account_id: str, actor_id: str, *, not_before=None) -> str:
        """Start the deletion of one account (called by offboarding after the cooling-off, or by an operator). -> the job id."""
        with self.coordinator.transaction() as con:
            existing = con.execute(f"SELECT id FROM account_jobs WHERE account_id=? AND kind='deletion' AND state IN ({','.join('?' * len(OPEN))})", (account_id, *OPEN)).fetchone()
            if existing:
                return existing['id']
            job = self._new(con, account_id, actor_id, 'deletion', {'account': account_id}, not_before=not_before)
            self.coordinator._audit(con, account_id, actor_id, job, 'data.delete.request', 'completed')
            return job

    def stop_work(self, account_id: str) -> dict:
        """Nothing new starts and what runs is asked to stop: waiting tasks are cancelled, running ones are told to stop, schedules and watchers are paused."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            waiting = con.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND state='waiting'", (account_id,)).rowcount
            con.execute("UPDATE tasks SET state='cancelled' WHERE account_id=? AND state='queued'", (account_id,))
            running = con.execute("UPDATE customer_requests SET cancel_requested=1 WHERE account_id=? AND state IN ('starting','running','uncertain')", (account_id,)).rowcount
            schedules = con.execute("UPDATE schedules SET state='paused',pause_reason='The account is being closed.' WHERE account_id=? AND state='active'", (account_id,)).rowcount
            watchers = con.execute("UPDATE watchers SET state='paused' WHERE account_id=? AND state='active'", (account_id,)).rowcount
            jobs = con.execute("UPDATE objectives SET cancelled=1,app_state='cancelled',updated_epoch=? WHERE account_id=? AND cancelled=0 AND app_state IN ('active','paused','needs_reconciliation')", (now, account_id)).rowcount
            pending = con.execute("UPDATE actions SET state='expired',ended_reason='connection_removed',updated_epoch=? WHERE account_id=? AND state IN ('proposed','approved')", (now, account_id)).rowcount
            con.execute("UPDATE handoffs SET state='cancelled',answered_epoch=? WHERE account_id=? AND state='waiting'", (now, account_id))
        return {'tasks_cancelled': waiting, 'tasks_stopping': running, 'schedules_paused': schedules, 'watchers_paused': watchers, 'jobs_cancelled': jobs, 'changes_ended': pending}

    def _still_running(self, account_id) -> int:
        with self.store.connect() as con:
            return con.execute("SELECT count(*) FROM customer_requests WHERE account_id=? AND state IN ('starting','running','uncertain')", (account_id,)).fetchone()[0]

    def run_deletion(self, job_id: str):
        """Each store is one checkpoint. A store that cannot be handled now leaves the job `waiting` and it is tried again; it is never passed over."""
        with self.store.connect() as con:
            job = con.execute('SELECT * FROM account_jobs WHERE id=?', (job_id,)).fetchone()
        account, actor = job['account_id'], job['actor_id']
        if job['not_before_epoch'] and job['not_before_epoch'] > self.clock():
            return self._wait(job_id, 'cooling_off')
        if not self._done(job_id, 'stop_work'):
            with self.coordinator.transaction() as con:
                con.execute("UPDATE accounts SET status='deleting' WHERE id=? AND status IN ('active','suspended')", (account,))      # from here nobody can sign in to it or start anything in it
            self._step(job_id, 'stop_work', self.stop_work(account))
        if self._still_running(account):
            return self._wait(job_id, 'running_tasks')
        # The stores outside the database, each with its adapter.
        for name in ('connections', 'custody', 'memory', 'model_key', 'cell'):
            if self._done(job_id, name):
                continue
            detail, ok = self._adapter(name, account)
            if not ok or detail == 'waiting':
                self._step(job_id, name, detail, state='waiting')
                return self._wait(job_id, name)
            self._step(job_id, name, detail)
        if not self._done(job_id, 'files'):
            self._step(job_id, 'files', self._delete_files(account))
        if not self._done(job_id, 'database'):
            self._step(job_id, 'database', self._delete_rows(account, actor, job_id))
        scan = self.verify(account)
        self._step(job_id, 'verification', {'clean': scan['clean']})
        report = {'deleted_epoch': int(self.clock()), 'verification': scan, 'remains_by_design': list(REMAINS_BY_DESIGN)}
        if not self._done(job_id, 'confirmation'):
            # The confirmation, with the deletion report, goes out BEFORE the sign-in identity is erased: the address is the last thing to go, and it is needed to send this.
            detail, _ok = self._adapter('mail', account, actor, report)
            self._step(job_id, 'confirmation', detail)
        if not self._done(job_id, 'identity'):
            detail, ok = self._adapter('identity', account)
            if not ok:
                self._step(job_id, 'identity', detail, state='waiting')
                return self._wait(job_id, 'identity')
            self._step(job_id, 'identity', detail)
        left, ok = self._adapter('scan_identity', account)      # the last check: is the address really gone?
        report['verification']['identity'] = left
        if not ok or (isinstance(left, int) and left > 0):
            report['verification']['clean'] = False
        self._finish(job_id, 'completed' if report['verification']['clean'] else 'failed', report)

    def _wait(self, job_id, what):
        with self.coordinator.transaction() as con:
            con.execute("UPDATE account_jobs SET state='waiting',waiting_for=?,lease_until=0,updated_epoch=? WHERE id=?", (what, int(self.clock()), job_id))

    def _delete_files(self, account) -> dict:
        """Every file of the account in the file store: files it made, uploads, pictures of first pages, export archives."""
        if self.storage is None:
            return {'files': 'not_on_this_host'}
        root, removed = self.storage.root / account, 0
        if not root.is_symlink() and root.is_dir():
            for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                try:
                    if path.is_symlink() or path.is_file():
                        path.unlink(); removed += 1
                    else:
                        path.rmdir()
                except OSError:
                    pass
            try:
                root.rmdir()
            except OSError:
                pass
        return {'files_removed': removed}

    def _delete_rows(self, account, actor, job_id) -> dict:
        """Every row of the account, in one transaction: what accounting needs is copied out first (amounts and dates only), then every table that has an account id is emptied
        of it except the ones that stay by design. Foreign keys are checked when it commits, so the order does not matter and nothing is left dangling."""
        removed = {}
        with self.coordinator.transaction() as con:
            if True:
                con.execute('PRAGMA defer_foreign_keys=ON')
                con.execute('''INSERT OR IGNORE INTO financial_records(account_id,kind,reference,provider,price_version,amount_microusd,occurred)
                    SELECT account_id,'provider_receipt',provider_request_id,provider,price_version,amount_microusd,datetime(observed_epoch,'unixepoch') FROM provider_receipts WHERE account_id=?''', (account,))
                con.execute('''INSERT OR IGNORE INTO financial_records(account_id,kind,reference,provider,price_version,amount_microusd,occurred)
                    SELECT account_id,'usage_entry',id,provider,price_version,amount_microusd,created_at FROM usage_entries WHERE account_id=?''', (account,))
                org = con.execute('SELECT organization_id FROM accounts WHERE id=?', (account,)).fetchone()
                for table in _tables_with_account(con):
                    if table in KEPT_AT_DELETION:
                        continue
                    # Some records are append-only by a trigger (receipts, usage). Deleting the whole account is the one thing allowed to remove them: the guard is lifted
                    # inside this transaction only and put back exactly as it was before it ends (if anything fails, SQLite rolls the guard back with everything else).
                    guards = [g for g in con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall() if 'BEFORE DELETE' in g[1].upper()]
                    for guard in guards:
                        con.execute(f'DROP TRIGGER "{guard[0]}"')
                    count = con.execute(f'DELETE FROM "{table}" WHERE account_id=?', (account,)).rowcount
                    for guard in guards:
                        con.execute(guard[1].replace('%', '%%') if type(con).__name__ == 'Queries' else guard[1])      # the web app's connection formats its SQL: a literal % must be doubled there
                    if count:
                        removed[table] = count
                for scope in (account, 'org:' + account):          # settings stored under the account id in tables that have no foreign key to it
                    for table in ('safety_overrides', 'safety_access'):
                        try:
                            count = con.execute(f'DELETE FROM {table} WHERE account_id=?', (scope,)).rowcount
                            if count:
                                removed[table] = removed.get(table, 0) + count
                        except Exception as error:
                            if 'no such table' not in str(error):
                                raise
                # An organization with nobody left in it ends with its last account: the one this account belonged to, and the organization of one it started as.
                for organization in {org[0] if org and org[0] else account, account}:
                    if not con.execute('SELECT 1 FROM organization_members WHERE organization_id=?', (organization,)).fetchone():
                        con.execute('DELETE FROM organization_policies WHERE organization_id=?', (organization,))
                        con.execute('UPDATE accounts SET organization_id=NULL WHERE organization_id=?', (organization,))
                        con.execute("UPDATE organizations SET status='deleted',name='' WHERE id=?", (organization,))
                con.execute("UPDATE memberships SET status='revoked' WHERE account_id=?", (account,))
                con.execute("UPDATE accounts SET status='deleted' WHERE id=?", (account,))
                con.execute('''INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id) VALUES (?,?,?,?,?,?,?)''',
                            (account, uuid.uuid4().hex, 'system', account, 'account.deleted', 'completed', job_id))                 # the tombstone line
        return {'rows_removed': sum(removed.values()), 'tables': len(removed)}

    def verify(self, account: str) -> dict:
        """The verification scan: every store, looked at for this account. `clean` is True only when nothing is found outside what remains by design."""
        found = {}
        with self.store.connect() as con:
            for table in _tables_with_account(con):
                count = con.execute(f'SELECT count(*) FROM "{table}" WHERE account_id=?', (account,)).fetchone()[0]
                if count and table not in KEPT_AT_DELETION:
                    found['db.' + table] = count
            for table, column in (('organization_members', 'account_id'), ('organizations', 'id')):
                extra = con.execute(f"SELECT count(*) FROM {table} WHERE {column}=?" + (" AND status!='deleted'" if table == 'organizations' else ''), (account,)).fetchone()[0]
                if extra:
                    found['db.' + table] = extra
            status = con.execute('SELECT status FROM accounts WHERE id=?', (account,)).fetchone()
            kept = {t: con.execute(f'SELECT count(*) FROM "{t}" WHERE account_id=?', (account,)).fetchone()[0] for t in ('audit_events', 'financial_records', 'account_jobs')}
        if self.storage is not None and (self.storage.root / account).exists():
            found['files'] = sum(1 for _ in (self.storage.root / account).rglob('*')) or 1
        outside, ok = self._adapter('scan', account)
        if isinstance(outside, dict):
            found.update({'outside.' + k: v for k, v in outside.items() if v})
        elif not ok:
            found['outside.scan'] = outside
        return {'clean': not found and bool(status) and status[0] == 'deleted', 'found': found, 'kept_by_design': kept, 'account_record': status[0] if status else None,
                'outside_stores': 'checked' if isinstance(outside, dict) else outside}

    # -- offboarding (#21) ---------------------------------------------------------------------------------------------------------------------
    def offboarding(self, principal: Principal) -> dict | None:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute("SELECT * FROM account_jobs WHERE account_id=? AND kind='offboarding' ORDER BY created_epoch DESC LIMIT 1", (principal.account_id,)).fetchone()
            return {**self.public(row), 'cooling_off_seconds': self.cooling_off, 'remains_by_design': list(REMAINS_BY_DESIGN)} if row else None

    def start_offboarding(self, principal: Principal, *, for_account=None, cooling_off=None) -> dict:
        """The customer asks to close their account (or an owner or admin removes a member: `for_account`). Work stops at once; the job then waits for the export choice."""
        account = principal.account_id
        with self.coordinator.transaction() as con:
            if for_account and for_account != principal.account_id:
                from .permissions import organization_of
                require(principal, 'member.remove', con=con)
                if organization_of(con, for_account) != organization_of(con, principal.account_id):
                    raise NotFound('unavailable')
                account = for_account
            else:
                require(principal, 'data.delete', con=con)
            if con.execute(f"SELECT 1 FROM account_jobs WHERE account_id=? AND kind='offboarding' AND state IN ({','.join('?' * len(OPEN))})", (account, *OPEN)).fetchone():
                raise Conflict('this account is already being closed')
            job = self._new(con, account, principal.actor_id, 'offboarding', {'account': account, 'by_member': account == principal.account_id,
                                                                            'cooling_off': self.cooling_off if cooling_off is None else int(cooling_off)}, state='waiting', waiting_for='export_choice')
            self.coordinator._audit(con, account, principal.actor_id, job, 'account.offboarding.start', 'completed')
        self._step(job, 'stop_work', self.stop_work(account))
        with self.store.connect() as con:
            return self.public(con.execute('SELECT * FROM account_jobs WHERE id=?', (job,)).fetchone())

    def start_offboarding_by_operator(self, account_id: str, operator: str, *, cooling_off=None, export=False) -> str:
        """The operator command: the same flow for an account whose customer asked by email."""
        with self.coordinator.transaction() as con:
            if not con.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
                raise NotFound('unavailable')
            existing = con.execute(f"SELECT id FROM account_jobs WHERE account_id=? AND kind='offboarding' AND state IN ({','.join('?' * len(OPEN))})", (account_id, *OPEN)).fetchone()
            if existing:
                return existing['id']
            job = self._new(con, account_id, 'operator:' + str(operator)[:40], 'offboarding',
                            {'account': account_id, 'by_member': False, 'cooling_off': self.cooling_off if cooling_off is None else int(cooling_off)}, state='waiting', waiting_for='export_choice')
            self.coordinator._audit(con, account_id, 'operator', job, 'account.offboarding.start', 'completed')
        self._step(job, 'stop_work', self.stop_work(account_id))
        self._choose(account_id, job, bool(export))
        return job

    def choose_export(self, principal: Principal, export: bool) -> dict:
        """Step two: "export my data first" or "no export". The job only moves on once this is answered."""
        with self.store.connect() as con:
            require(principal, 'data.delete', con=con)
            row = con.execute("SELECT * FROM account_jobs WHERE account_id=? AND kind='offboarding' AND state='waiting' AND waiting_for='export_choice'", (principal.account_id,)).fetchone()
        if not row:
            raise Conflict('there is nothing to choose now')
        self._choose(principal.account_id, row['id'], bool(export))
        return self.offboarding(principal)

    def _choose(self, account_id, job_id, export):
        child = None
        if export:
            with self.coordinator.transaction() as con:
                open_export = con.execute(f"SELECT id FROM account_jobs WHERE account_id=? AND kind='export' AND state IN ({','.join('?' * len(OPEN))})", (account_id, *OPEN)).fetchone()
                actor = con.execute('SELECT actor_id FROM account_jobs WHERE id=?', (job_id,)).fetchone()['actor_id']
                child = open_export['id'] if open_export else self._new(con, account_id, actor, 'export', {'accounts': [account_id], 'organization': False})
        self._step(job_id, 'export_choice', {'export': bool(export)})
        with self.coordinator.transaction() as con:
            con.execute("UPDATE account_jobs SET state='running',waiting_for=NULL,child_job_id=?,updated_epoch=? WHERE id=?", (child, int(self.clock()), job_id))

    def cancel_offboarding(self, principal: Principal) -> dict:
        """The customer changes their mind, any time before the deletion starts. Nothing has been deleted; connections that were already ended stay ended (reconnect them)."""
        with self.coordinator.transaction() as con:
            require(principal, 'data.delete', con=con)
            row = con.execute(f"SELECT * FROM account_jobs WHERE account_id=? AND kind='offboarding' AND state IN ({','.join('?' * len(OPEN))})", (principal.account_id, *OPEN)).fetchone()
            if not row:
                raise Conflict('this account is not being closed')
            if any(s['step'] == 'deletion_started' for s in json.loads(row['steps_json'])):
                raise Conflict('the deletion has already started and cannot be stopped')
            now = int(self.clock())
            con.execute("UPDATE account_jobs SET state='cancelled',waiting_for=NULL,finished_epoch=?,updated_epoch=? WHERE id=?", (now, now, row['id']))
            con.execute("UPDATE schedules SET state='active',pause_reason=NULL WHERE account_id=? AND state='paused' AND pause_reason='The account is being closed.'", (principal.account_id,))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, row['id'], 'account.offboarding.cancel', 'completed')
        return self.offboarding(principal)

    def run_offboarding(self, job_id: str):
        with self.store.connect() as con:
            job = con.execute('SELECT * FROM account_jobs WHERE id=?', (job_id,)).fetchone()
        account, scope = job['account_id'], json.loads(job['scope_json'])
        chose_export = any(s['step'] == 'export_choice' and (s.get('detail') or {}).get('export') for s in json.loads(job['steps_json']))
        if chose_export and job['child_job_id'] and not self._done(job_id, 'export'):
            with self.store.connect() as con:
                child = con.execute('SELECT state,archive_bytes FROM account_jobs WHERE id=?', (job['child_job_id'],)).fetchone()
            if child and child['state'] in OPEN:
                return self._wait(job_id, 'export')
            self._step(job_id, 'export', {'state': child['state'] if child else 'missing', 'bytes': child['archive_bytes'] if child else None})
        if not self._done(job_id, 'connections'):
            detail, ok = self._adapter('connections', account)
            if not ok:
                return self._wait(job_id, 'connections')
            self._step(job_id, 'connections', detail)
        if not self._done(job_id, 'subscription'):
            detail, ok = self._adapter('billing', account)
            if not ok:
                return self._wait(job_id, 'subscription')
            self._step(job_id, 'subscription', detail)
        if not self._done(job_id, 'cooling_off'):
            with self.store.connect() as con:
                until = con.execute('SELECT not_before_epoch FROM account_jobs WHERE id=?', (job_id,)).fetchone()[0]
            if until is None:
                until = int(self.clock()) + int(scope.get('cooling_off', self.cooling_off))
                with self.coordinator.transaction() as con:
                    con.execute('UPDATE account_jobs SET not_before_epoch=? WHERE id=?', (until, job_id))
            if until > self.clock():
                return self._wait(job_id, 'cooling_off')
            self._step(job_id, 'cooling_off', {'ended_epoch': until})
        if not self._done(job_id, 'deletion_started'):
            deletion = self.request_deletion(account, job['actor_id'])
            self._step(job_id, 'deletion_started', {'job': deletion})
        with self.store.connect() as con:
            deletion = con.execute("SELECT id,state,report_json FROM account_jobs WHERE account_id=? AND kind='deletion' ORDER BY created_epoch DESC LIMIT 1", (account,)).fetchone()
        if deletion['state'] in OPEN:
            return self._wait(job_id, 'deletion')
        report = json.loads(deletion['report_json'] or '{}')
        self._step(job_id, 'deletion', {'state': deletion['state'], 'clean': (report.get('verification') or {}).get('clean')})      # the confirmation email went out with the deletion itself
        self._finish(job_id, 'completed' if deletion['state'] == 'completed' else 'failed', report)

    # -- the loop ------------------------------------------------------------------------------------------------------------------------------
    def tick(self, limit=5) -> dict:
        """One pass over the jobs that can move. A job is leased while it runs, so two workers never run the same one."""
        now, report = int(self.clock()), {'export': 0, 'deletion': 0, 'offboarding': 0, 'errors': 0}
        with self.coordinator.transaction() as con:
            rows = [dict(r) for r in con.execute("""SELECT id,kind FROM account_jobs WHERE lease_until<=? AND (state IN ('requested','running')
                OR (state='waiting' AND coalesce(waiting_for,'')!='export_choice')) ORDER BY CASE kind WHEN 'export' THEN 0 WHEN 'deletion' THEN 1 ELSE 2 END,updated_epoch LIMIT ?""", (now, limit))]
            for r in rows:
                con.execute("UPDATE account_jobs SET state='running',lease_until=?,updated_epoch=? WHERE id=?", (now + LEASE_SECONDS, now, r['id']))
        for r in rows:
            try:
                {'export': self.run_export, 'deletion': self.run_deletion, 'offboarding': self.run_offboarding}[r['kind']](r['id'])
                report[r['kind']] += 1
            except Exception:
                report['errors'] += 1
                with self.coordinator.transaction() as con:      # left for the next pass, which carries on from its last checkpoint
                    con.execute("UPDATE account_jobs SET state='waiting',waiting_for='retry',lease_until=? WHERE id=? AND state='running'", (now + 60, r['id']))
        return report
