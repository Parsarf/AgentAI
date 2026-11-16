"""How long Lumina keeps each kind of data: one table, the single source of truth (roadmap #18). Stdlib only.

One row per kind of data: how long it is kept, what starts the clock, what deletes it, and whether the customer can change that. Everything that talks about retention
reads this table:

* the sweeper (`sweep`, run by the `retention_sweep` command on a daily timer) enforces every row marked `sweeper`;
* the customer's "How long we keep things" page is generated from it (`public`);
* the privacy check (privacy/derive.py) reads it, and a test fails when a table in the database belongs to no row, so a new kind of data cannot appear without a
  retention decision;
* account deletion (data_deletion.py) walks the same rows, so every kind of data has a delete step.

`days` None means "kept until the customer deletes it or the account is deleted". A row whose `by` is not `sweeper` is enforced somewhere else, named in `by`.
"""
from __future__ import annotations
import time
from dataclasses import dataclass

DAY = 86400


@dataclass(frozen=True)
class Rule:
    key: str
    title: str                         # what the customer reads
    days: float | None                 # how long it is kept (None: until the customer deletes it, or the account is deleted)
    clock: str                         # what starts the clock, in words
    by: str                            # sweeper | browser service | backup job | server logs | customer | never stored
    tables: tuple = ()                 # the database tables that hold it (every table belongs to exactly one rule)
    change: str = ''                   # how the customer can change it ('' = they cannot)
    note: str = ''
    at_deletion: str = 'deleted'       # deleted | kept (why is in `note`): what account deletion does with it


RULES: tuple[Rule, ...] = (
    Rule('messages', 'Chats, tasks, plans and the results shown in them', None, 'until you delete the chat or your account', 'customer',
         ('conversations', 'chat_messages', 'chat_deliveries', 'customer_requests', 'tasks', 'projects', 'ui_blocks', 'data_blocks', 'card_images', 'plan_revisions', 'plan_phase_runs',
          'plan_proposals', 'plan_settings', 'plan_launches', 'gen_artifact_state', 'gen_artifact_events', 'browse_runs', 'browse_steps', 'browse_sessions', 'route_decisions',
          'optimization_calls', 'optimization_activations', 'location_requests'),
         change='Delete a chat, or your account, in Settings.'),
    Rule('events', 'The step-by-step activity timeline of a task', 30, 'from when each step happened', 'sweeper', ('events', 'event_streams'),
         note='For a chat older than 90 days the timeline of its tasks is removed as well, whatever its age.'),
    Rule('artifacts', 'Files your assistant made', None, 'until you delete the file or your account', 'customer', ('artifacts',), change='Delete a file in Files.'),
    Rule('download_tickets', 'One-time download links', 1, 'from when the link ended', 'sweeper', ('download_tickets',)),
    Rule('uploads', 'Files you uploaded', None, 'until you delete the file or your account', 'customer', ('project_files', 'file_folders', 'file_places'), change='Delete a file in Files.',
         note='This includes the folders you made and the names you gave your files.'),
    Rule('browser_pictures', 'Pictures and traces from browser tasks', 1, 'from when the task ended', 'browser service', (),
         note='Deleted by the browser service every 15 minutes; they are files, not database rows.'),
    Rule('memory', 'Memory, saved choices and skills', None, 'until you forget them or delete your account', 'customer',
         ('memory_entries', 'memory_terms', 'longterm_memories', 'saved_choices', 'skills', 'skill_versions'), change='Forget one note or all of them in Settings, Memory.'),
    Rule('document_passages', 'Passages of your documents in the knowledge index', None, 'not stored yet', 'never stored', (),
         note='The knowledge index does not exist yet. When it does, a removed source takes its passages with it.'),
    Rule('connections', 'Connected services: what is connected, what it may reach, and how fresh its data is', None, 'until you remove the connection or delete your account', 'customer',
         ('connector_connections', 'connector_grants', 'connector_freshness', 'connector_secrets', 'connector_drafts', 'browser_profiles', 'mcp_connections', 'mcp_tool_choices',
          'action_auto_approvals', 'telegram_links', 'telegram_link_codes', 'telegram_outbox', 'telegram_updates', 'hub_sync', 'hub_calendars', 'hub_settings'),
         change='Remove a connection in Settings. Its tokens are deleted at once.'),
    # The dashboard's copy of connected mail and calendars (#D2). The sync window IS these rows: hub_sync.py reads its limits from here.
    Rule('mail_headers', 'Mail from your connected accounts: who it is from and to, the subject and a short preview', 90,
         'from when the message was sent (starred mail is kept while it is starred)', 'sweeper', ('hub_messages', 'hub_threads'),
         change='Remove the account in Mail, or choose which labels it may read.', note='Older mail is not copied: it is searched in your mail service when you ask.'),
    Rule('mail_bodies', 'The full text of a message, and the names of its attachments', 90, 'from when you or your assistant last opened it', 'sweeper', (),
         note='A message is only fetched in full when it is opened.'),
    Rule('calendar_events', 'Events from your connected calendars', 31, 'from when the event ended', 'sweeper', ('hub_events',),
         change='Remove the account in Calendar, or choose which calendars it may read.', note='Events up to twelve months ahead are kept current.'),
    Rule('connection_setup', 'Unfinished attempts to connect a service', 1, 'from when the attempt ended', 'sweeper', ('connector_link_states',)),
    Rule('connector_records', 'Records of what was read or changed in connected services', 180, 'from when it finished', 'sweeper',
         ('connector_operations', 'connector_revocations', 'mcp_calls', 'actions', 'handoffs', 'workflows'),
         note='A change that is still waiting for you, or still being carried out, is never removed by this.'),
    Rule('schedules', 'Schedules, watchers and long jobs', None, 'until you delete them or your account', 'customer',
         ('schedules', 'watchers', 'watcher_notifications', 'objectives', 'objective_checkpoints', 'objective_children'), change='Delete a schedule, or cancel a job, in the app.'),
    Rule('schedule_runs', 'The daily record of what each schedule did', 180, 'from the day of the run', 'sweeper', ('schedule_runs',)),
    Rule('vault', 'Saved logins and cards, and your own model key', None, 'until you remove them or delete your account', 'customer', ('vault_items',), change='Remove them in Settings.'),
    Rule('receipts', 'Usage and billing records', None, 'kept while your account exists; what accounting rules require is kept after it', 'customer',
         ('provider_receipts', 'usage_entries', 'task_reservations', 'entitlements', 'billing_customers', 'billing_checkout_sessions', 'billing_subscriptions', 'billing_invoices',
          'billing_flags', 'billing_inbox', 'billing_operations', 'spend_limits'),
         note='Amounts and dates of charges are financial records. They hold no chat content.', at_deletion='kept'),
    Rule('spend_marks', 'Internal cost bookkeeping between tasks', 30, 'from when the task ran', 'sweeper', ('spend_marks',)),
    Rule('audit', 'The security record of sensitive actions', 180, 'from when the action happened', 'sweeper', ('audit_events',),
         note='When an account is deleted one line remains that says it was deleted, and when.', at_deletion='kept'),
    Rule('exports', 'Archives of your data that you asked for', 7, 'from when the archive was made', 'sweeper', ('account_jobs',),
         note='The archive file is deleted after 7 days. The record that an export or a deletion was done is kept with the security record.', at_deletion='kept'),
    Rule('account', 'Your account, sign-in and organization', None, 'until your account is deleted', 'customer',
         ('accounts', 'memberships', 'organizations', 'organization_members', 'organization_policies', 'signups'),
         change='Delete your account in Settings.', note='After deletion the account id remains as an empty record so it can never be reused.', at_deletion='kept'),
    Rule('cell', 'Your assistant itself: its workspace, its settings and its own model key', None, 'until your account is deleted', 'customer',
         ('deployments', 'operations', 'lifecycle_cells', 'lifecycle_details', 'lifecycle_backups', 'lifecycle_slot', 'cell_slots', 'request_slot', 'request_slots')),
    Rule('financial_records', 'Amounts and dates of what was charged, kept after an account is deleted', None, 'as long as accounting rules require', 'never stored', ('financial_records',),
         note='They exist only for a deleted account and link to no chat, task or file.', at_deletion='kept'),
    Rule('logs', 'Technical server logs', 7, 'from when the line was written', 'server logs', (), note='They hold no chat content.', at_deletion='kept'),
    Rule('backups', 'Encrypted backups of our systems', 30, 'from when the backup was made', 'backup job', (),
         note='Something you delete can remain in a backup until the backup expires. A backup is never used to bring deleted data back.', at_deletion='kept'),
    Rule('test_only', 'The synthetic test service', None, 'holds only what a test puts in it', 'customer', ('synthetic_records', 'synthetic_faults')),
    Rule('platform', 'Lumina\'s own bookkeeping, with no customer data', None, 'not customer data', 'never stored', ('schema_migrations',), at_deletion='kept'),
)

BY_KEY = {r.key: r for r in RULES}
TABLE_RULE = {table: rule.key for rule in RULES for table in rule.tables}


def rule_of(table: str):
    return TABLE_RULE.get(table)


def unassigned(con) -> list[str]:
    """Tables in this database that belong to no rule (the test and the privacy check fail on any)."""
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE ? ORDER BY name", ('sqlite_%',))]
    return [n for n in names if n not in TABLE_RULE]


def public() -> list[dict]:
    """What the customer is shown: "How long we keep things"."""
    def words(rule):
        if rule.by == 'never stored':
            return rule.clock.capitalize() + '.'
        if rule.days is None:
            return rule.clock[0].upper() + rule.clock[1:] + '.'
        length = f'{int(rule.days * 24)} hours' if rule.days < 1 or (rule.days == 1 and rule.by == 'browser service') else f'{int(rule.days)} day{"s" if rule.days != 1 else ""}'
        return f'{length}, {rule.clock}.'
    return [{'key': r.key, 'title': r.title, 'kept': words(r), 'days': r.days, 'you_can': r.change, 'note': r.note}
            for r in RULES if r.key not in ('platform', 'test_only', 'spend_marks', 'download_tickets', 'connection_setup')]


def as_facts() -> dict:
    """For the privacy record: every limit this table sets, by key, and which of them the sweeper enforces."""
    return {'days': {r.key: r.days for r in RULES if r.days is not None}, 'swept': sorted(r.key for r in RULES if r.by == 'sweeper')}


# -- the sweeper ----------------------------------------------------------------------------------------------------------------------------------------------
def _audit_delete(con, cutoff_iso) -> int:
    """The security record is append-only by a trigger. Retention is the one thing allowed to remove old lines: the delete guard is lifted inside this transaction only and
    put back before it ends (SQLite rolls the trigger back with everything else if anything fails)."""
    con.execute('DROP TRIGGER IF EXISTS audit_no_delete')
    removed = con.execute('DELETE FROM audit_events WHERE created_at<?', (cutoff_iso,)).rowcount
    con.execute("CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append only'); END")
    return removed


def sweep(store, *, now=None, storage=None) -> dict:
    """Enforce every `sweeper` row once. -> {rule key: rows removed}. Safe to run at any time and any number of times. `storage` is the file store (storage.RootStore), used
    to delete export archives; without it only their rows are marked."""
    now = int(now if now is not None else time.time())
    iso = lambda days: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now - int(days * DAY)))
    epoch = lambda days: now - int(days * DAY)
    done = {}
    from .lifecycle.coordinator import Coordinator
    with Coordinator(store).transaction() as con:      # one transaction, on whichever connection this process uses (the web app's own, or a worker's)
        if True:
            days = BY_KEY['events'].days
            done['events'] = con.execute('DELETE FROM events WHERE created_at<?', (iso(days),)).rowcount
            done['download_tickets'] = con.execute('DELETE FROM download_tickets WHERE expires_epoch<?', (epoch(BY_KEY['download_tickets'].days),)).rowcount
            done['connection_setup'] = con.execute('DELETE FROM connector_link_states WHERE expires_epoch<?', (epoch(BY_KEY['connection_setup'].days),)).rowcount
            old = epoch(BY_KEY['connector_records'].days)
            done['connector_records'] = (
                con.execute("DELETE FROM connector_operations WHERE created_epoch<? AND state IN ('completed','failed','cancelled')", (old,)).rowcount
                + con.execute('DELETE FROM connector_revocations WHERE created_epoch<?', (old,)).rowcount
                + con.execute("DELETE FROM mcp_calls WHERE created_epoch<? AND state NOT IN ('pending','approved','dispatching')", (old,)).rowcount
                + con.execute("DELETE FROM handoffs WHERE created_epoch<? AND state NOT IN ('waiting','answered')", (old,)).rowcount
                + con.execute("DELETE FROM actions WHERE updated_epoch<? AND state NOT IN ('proposed','approved','executing','uncertain')", (old,)).rowcount
                + con.execute("DELETE FROM workflows WHERE updated_epoch<? AND state NOT IN ('proposed','approved','running')", (old,)).rowcount)
            day = time.strftime('%Y-%m-%d', time.gmtime(epoch(BY_KEY['schedule_runs'].days)))
            done['schedule_runs'] = con.execute("DELETE FROM schedule_runs WHERE day<? AND state NOT IN ('firing','started')", (day,)).rowcount
            done['spend_marks'] = con.execute('DELETE FROM spend_marks WHERE epoch<?', (epoch(BY_KEY['spend_marks'].days),)).rowcount
            done['audit'] = _audit_delete(con, iso(BY_KEY['audit'].days))
            from . import hub_sync
            done.update(hub_sync.sweep(con, now))
            expired = [dict(r) for r in con.execute("SELECT id,account_id,archive_ref FROM account_jobs WHERE kind='export' AND archive_ref IS NOT NULL AND finished_epoch<?",
                                                    (epoch(BY_KEY['exports'].days),))]
            for job in expired:
                con.execute("UPDATE account_jobs SET archive_ref=NULL,archive_bytes=NULL,state='expired' WHERE id=?", (job['id'],))
            done['exports'] = len(expired)
    if storage is not None:
        for job in expired:
            try:
                storage.delete([job['account_id']] + job['archive_ref'].split('/'))
            except (OSError, ValueError):
                pass
    return done
