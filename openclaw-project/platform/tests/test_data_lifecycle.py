"""Retention (#18), export (#19), deletion (#20) and offboarding (#21)."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from agentai_platform import retention
from agentai_platform.data_lifecycle import KEPT_AT_DELETION, NEVER_EXPORTED, AccountJobs, EXPORT
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal
from agentai_platform.storage import RootStore
from agentai_platform.synthetic_connector import SyntheticBench

from tests.connector_fixture import ConnectorBase

KEY = b'k' * 32


class Base(ConnectorBase):
    def setUp(self):
        super().setUp()
        self.files = RootStore(Path(self.tmp.name) / 'files')
        self.outside = {'memory': ['note'], 'model_key': ['key'], 'mail': []}
        self.adapters = {
            'connections': lambda account: [self.connectors.revoke_by_system(account, r['id'], 'offboarding') for r in self.rows("SELECT id FROM connector_connections WHERE account_id=? AND state!='revoked'", (account,))] and 'ended' or 'none',
            'custody': lambda account: self.custody.delete_all(account),
            'memory': lambda account: self.outside['memory'].clear() or 'bank removed',
            'model_key': lambda account: self.outside['model_key'].clear() or 'removed',
            'cell': lambda account: 'done',
            'identity': lambda account: 'anonymised',
            'billing': lambda account: {'cancelled': 1},
            'mail': lambda account, actor, report: self.outside['mail'].append((account, report)) or 'sent',
            'scan': lambda account: {'memory': len(self.outside['memory']), 'model_key': len(self.outside['model_key']), 'custody': self.custody.count(account)},
            'scan_identity': lambda account: 0,
        }
        self.jobs = AccountJobs(self.store, storage=self.files, adapters=self.adapters, signing_key=KEY, clock=lambda: self.now)
        self.fill('a'); self.fill('b')

    def fill(self, account):
        """One of everything a customer has: a chat with messages, a task with a receipt, a file it made, an upload, memory, a schedule, a connection with a grant, an action."""
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,'customer',?)", (account, 'c-' + account, 'req-' + account, f'secret plans of {account}'))
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES (?,?,?,?,'completed',1)", (account, 'p-' + account, 'c-' + account, 'req-' + account))
            con.execute("UPDATE customer_requests SET conversation_id=?,state='completed' WHERE account_id=?", ('c-' + account, account))
            con.execute("INSERT INTO entitlements VALUES (?,?,'t','trial','{}',datetime('now','+1 day'))", (account, 'e-' + account))
            con.execute("INSERT INTO task_reservations VALUES (?,?,?,?,?,5,'settled',1)", (account, 'req-' + account, 'k', 'h', 'e-' + account))
            con.execute('INSERT INTO provider_receipts VALUES (?,?,?,?,?,?,?,?)', (account, 'req-' + account, 'litellm', 'rcpt-' + account, 'a' * 64, 'v1', 4200, self.now - 50))
            con.execute("INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,media_type,size_bytes,sha256,storage_ref) VALUES (?,?,?,?,1,'report.txt','text/plain',5,?,?)",
                        (account, 'p-' + account, 'req-' + account, 'art-' + account, 'b' * 64, 'artifacts/art-' + account + '/1'))
            con.execute("INSERT INTO events(account_id,task_id,id,sequence,kind,public_payload) VALUES (?,?,?,1,'progress','{}')", (account, 'req-' + account, 'ev-' + account))
            con.execute('''INSERT INTO schedules(account_id,project_id,id,name,timezone,hour_local,minute_local,timeout_seconds,task_budget_microusd,state,created_epoch)
                VALUES (?,?,?,'Daily','UTC',8,0,300,0,'active',1)''', (account, 'p-' + account, 's-' + account))
        self.files.write_private([account, 'artifacts', 'art-' + account, '1'], b'hello')
        who = self.a if account == 'a' else self.b
        connection = self.connect(who)
        self.actions.propose(who, connection, 'note.create', {'folder': 'inbox', 'title': 'T', 'body': 'B'}, request_id='req-' + account)
        return connection

    def has_columns(self, table, names):
        with self.store.connect() as con:
            have = {c[1] for c in con.execute(f'PRAGMA table_info("{table}")')}
        return set(names) <= have

    def run_jobs(self, times=6):
        for _ in range(times):
            self.jobs.tick()

    def archive(self, job_id, who=None):
        ticket = self.jobs.export_ticket(who or self.a, job_id)
        parts, size = self.jobs.consume_export_ticket(job_id, ticket['path'].split('ticket=')[1])
        return zipfile.ZipFile(io.BytesIO(self.files.read_private(parts))), ticket


class Retention(Base):
    def test_every_table_in_the_database_belongs_to_a_retention_rule(self):
        with self.store.connect() as con:
            self.assertEqual(retention.unassigned(con), [])                                              # a new table without a retention decision fails here
        tables = [t for r in retention.RULES for t in r.tables]
        self.assertEqual(len(tables), len(set(tables)))                                                  # and belongs to exactly one
        self.assertTrue(all(r.by in ('sweeper', 'browser service', 'backup job', 'server logs', 'customer', 'never stored') for r in retention.RULES))
        for kind in ('messages', 'events', 'artifacts', 'uploads', 'browser_pictures', 'memory', 'document_passages', 'connections', 'receipts', 'audit', 'logs', 'backups'):
            self.assertIn(kind, retention.BY_KEY)                                                        # every kind the roadmap names has a row

    def test_the_sweeper_enforces_every_row_it_owns_and_nothing_else(self):
        self.now = int(__import__('time').time())                                                        # rows stamped by the database carry the real time
        old = self.now - 200 * 86400
        iso = lambda days: __import__('time').strftime('%Y-%m-%dT%H:%M:%SZ', __import__('time').gmtime(self.now - days * 86400))
        with self.store.connect() as con:
            con.execute("UPDATE events SET created_at=? WHERE account_id='a'", (iso(31),))
            con.execute("INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id,created_at) VALUES ('a','old','x','y','z','completed','r',?)", (iso(181),))
            con.execute("INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id,created_at) VALUES ('a','new','x','y','z','completed','r',?)", (iso(10),))
            con.execute("INSERT INTO spend_marks(account_id,request_id,kind,spend_microusd,epoch) VALUES ('a','r','start',1,?)", (self.now - 31 * 86400,))
            con.execute("INSERT INTO download_tickets VALUES ('t1','a','art-a',1,?,NULL,1)", (self.now - 2 * 86400,))
            con.execute("UPDATE actions SET state='done',updated_epoch=? WHERE account_id='a'", (old,))
            con.execute("UPDATE handoffs SET state='resumed',created_epoch=? WHERE account_id='a'", (old,))
            con.execute("UPDATE actions SET updated_epoch=? WHERE account_id='b'", (old,))                # b's is still waiting for approval: never removed
            con.execute("UPDATE handoffs SET created_epoch=? WHERE account_id='b'", (old,))
        done = retention.sweep(self.store, now=self.now, storage=self.files)
        self.assertEqual({k: v for k, v in done.items() if v}, {'events': 1, 'audit': 1, 'spend_marks': 1, 'download_tickets': 1, 'connector_records': 2})
        self.assertEqual([r['id'] for r in self.rows("SELECT id FROM audit_events WHERE id IN ('old','new')")], ['new'])
        self.assertEqual(self.rows("SELECT count(*) AS n FROM actions WHERE account_id='b'")[0]['n'], 1)
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages")[0]['n'], 2)                 # messages are kept until their customer deletes them
        self.assertEqual(self.rows("SELECT count(*) AS n FROM events WHERE account_id='b'")[0]['n'], 1)
        with self.store.connect() as con, self.assertRaises(Exception):
            con.execute("DELETE FROM audit_events WHERE id='new'")                                        # the guard on the security record is back
        self.assertEqual({k: v for k, v in retention.sweep(self.store, now=self.now).items() if v}, {})   # running it again removes nothing

    def test_the_customers_page_and_the_privacy_record_come_from_the_same_table(self):
        shown = {r['key']: r for r in retention.public()}
        self.assertEqual(shown['events']['kept'], '30 days, from when each step happened.')
        self.assertEqual(shown['browser_pictures']['kept'], '24 hours, from when the task ended.')
        self.assertEqual(shown['messages']['kept'], 'Until you delete the chat or your account.')
        self.assertIn('Delete a chat', shown['messages']['you_can'])
        facts = retention.as_facts()
        self.assertEqual((facts['days']['events'], facts['days']['audit'], facts['days']['logs'], facts['days']['backups']), (30, 180, 7, 30))
        self.assertEqual(set(facts['swept']), {r.key for r in retention.RULES if r.by == 'sweeper'})


class Export(Base):
    def test_the_archive_holds_every_kind_with_a_manifest_and_never_a_secret(self):
        tokens = json.loads(self.custody.get('a', self.rows("SELECT secret_ref FROM connector_connections WHERE account_id='a'")[0]['secret_ref']))
        job = self.jobs.request_export(self.a)
        with self.assertRaises(Conflict):
            self.jobs.request_export(self.a)                                                              # one at a time
        self.run_jobs(2)
        done = self.jobs.get(self.a, job['id'])
        self.assertEqual((done['state'], done['has_archive']), ('completed', True))
        archive, ticket = self.archive(job['id'])
        names = set(archive.namelist())
        manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual({f['file'] for f in manifest['files']} | {'manifest.json', 'README.txt'}, names)   # the manifest lists every file ...
        for entry in manifest['files']:
            data = archive.read(entry['file'])
            self.assertEqual((len(data), __import__('hashlib').sha256(data).hexdigest()), (entry['bytes'], entry['sha256']))      # ... with its size and hash
        self.assertEqual(json.loads(archive.read('conversations/messages.json'))[0]['content'], 'secret plans of a')
        self.assertEqual(archive.read('files/made/art-a/v1/report.txt'), b'hello')                         # the original file
        self.assertEqual(json.loads(archive.read('connections/grants.json'))[0]['resource_id'], 'inbox')  # connections with their grants ...
        whole = b''.join(archive.read(n) for n in names)
        for secret in (tokens['access_token'], tokens['refresh_token'], 'secret_ref', 'ciphertext'):
            self.assertNotIn(secret.encode(), whole)                                                       # ... never tokens
        self.assertNotIn(b'secret plans of b', whole)                                                      # and nothing of another account
        counts = {f['file']: f['items'] for f in manifest['files']}
        self.assertEqual((counts['conversations/messages.json'], counts['usage/receipts.json'], counts['actions/actions.json']), (1, 1, 1))
        self.assertEqual(ticket['sha256'], done['report']['sha256'])

    def test_the_link_works_once_expires_and_belongs_to_its_account(self):
        job = self.jobs.request_export(self.a); self.run_jobs(2)
        with self.assertRaises(NotFound):
            self.jobs.export_ticket(self.b, job['id'])                                                     # another account cannot get a link to it
        ticket = self.jobs.export_ticket(self.a, job['id'])['path'].split('ticket=')[1]
        with self.assertRaises(NotFound):
            self.jobs.consume_export_ticket(job['id'], 'wrong')
        self.jobs.consume_export_ticket(job['id'], ticket)
        with self.assertRaises(NotFound):
            self.jobs.consume_export_ticket(job['id'], ticket)                                             # single use
        late = self.jobs.export_ticket(self.a, job['id'])['path'].split('ticket=')[1]
        self.now += 901
        with self.assertRaises(NotFound):
            self.jobs.consume_export_ticket(job['id'], late)                                               # and it expires

    def test_the_archive_follows_its_retention_row(self):
        job = self.jobs.request_export(self.a); self.run_jobs(2)
        self.now += 8 * 86400
        self.assertEqual(retention.sweep(self.store, now=self.now, storage=self.files)['exports'], 1)
        self.assertEqual(self.jobs.get(self.a, job['id'])['has_archive'], False)
        self.assertFalse((self.files.root / 'a' / 'exports' / (job['id'] + '.zip')).exists())

    def test_an_owner_exports_the_organization_and_a_member_only_their_own(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        with self.assertRaises(Exception):
            self.jobs.request_export(self.b, organization=True)                                            # a member cannot export the organization
        job = self.jobs.request_export(self.a, organization=True); self.run_jobs(2)
        archive, _ = self.archive(job['id'])
        self.assertEqual(json.loads(archive.read('members/b/conversations/messages.json'))[0]['content'], 'secret plans of b')
        self.assertEqual(json.loads(archive.read('members/a/conversations/messages.json'))[0]['content'], 'secret plans of a')
        mine = self.jobs.request_export(self.b); self.run_jobs(2)
        own, _ = self.archive(mine['id'], self.b)
        self.assertNotIn(b'secret plans of a', b''.join(own.read(n) for n in own.namelist()))

    def test_every_table_is_either_exported_named_as_left_out_or_holds_nothing_of_the_customers(self):
        exported = {table for _f, _k, table in EXPORT}
        with self.store.connect() as con:
            from agentai_platform.data_lifecycle import _tables_with_account
            unexplained = [t for t in _tables_with_account(con) if t not in exported and t not in NEVER_EXPORTED and retention.rule_of(t) in ('messages', 'memory', 'schedules', 'connections', 'vault')]
        allowed = {'card_images', 'gen_artifact_state', 'gen_artifact_events', 'browse_steps', 'browse_sessions', 'route_decisions', 'optimization_calls', 'optimization_activations', 'location_requests',
                   'plan_launches', 'memory_terms', 'watcher_notifications', 'objective_children', 'connector_freshness', 'connector_drafts', 'browser_profiles', 'telegram_links', 'telegram_outbox'}
        self.assertEqual(sorted(set(unexplained) - allowed), [])


class Deletion(Base):
    def test_a_deleted_account_leaves_nothing_but_what_is_stated(self):
        job = self.jobs.request_deletion('a', 'actor-a')
        self.run_jobs()
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM account_jobs WHERE id=?', (job,)).fetchone()
        report = json.loads(row['report_json'])
        self.assertEqual((row['state'], report['verification']['clean'], report['verification']['found']), ('completed', True, {}))
        self.assertEqual([s['step'] for s in json.loads(row['steps_json'])], ['stop_work', 'connections', 'custody', 'memory', 'model_key', 'cell', 'files', 'database', 'verification', 'confirmation', 'identity'])
        left = {}
        with self.store.connect() as con:
            from agentai_platform.data_lifecycle import _tables_with_account
            for table in _tables_with_account(con):
                count = con.execute(f'SELECT count(*) FROM "{table}" WHERE account_id=?', ('a',)).fetchone()[0]
                if count:
                    left[table] = count
        self.assertEqual(set(left) - set(KEPT_AT_DELETION), set())                                         # the scan of every table: only what stays by design
        self.assertEqual(self.rows("SELECT status FROM accounts WHERE id='a'")[0]['status'], 'deleted')    # the tombstone
        self.assertEqual(self.rows("SELECT action FROM audit_events WHERE account_id='a' AND action='account.deleted'")[0]['action'], 'account.deleted')
        self.assertEqual(self.rows("SELECT kind,amount_microusd FROM financial_records WHERE account_id='a'"), [{'kind': 'provider_receipt', 'amount_microusd': 4200}])
        self.assertFalse((self.files.root / 'a').exists())                                                 # the file store
        self.assertEqual((self.custody.count('a'), self.outside['memory'], self.outside['model_key']), (0, [], []))       # custody, the memory bank, the model key
        self.assertEqual(len(report['remains_by_design']), 4)
        # the other account is untouched
        self.assertEqual(self.rows("SELECT content FROM chat_messages")[0]['content'], 'secret plans of b')
        self.assertTrue((self.files.root / 'b' / 'artifacts' / 'art-b' / '1').exists())
        self.assertEqual(self.custody.count('b'), 1)
        with self.store.connect() as con:
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_a_failure_resumes_from_the_last_checkpoint_and_never_repeats_a_step(self):
        calls = {'memory': 0, 'custody': 0}
        def memory(account):
            calls['memory'] += 1
            if calls['memory'] < 3:
                raise RuntimeError('memory service is down')
            return self.outside['memory'].clear() or 'bank removed'
        counted = self.adapters['custody']
        self.adapters['custody'] = lambda account: calls.__setitem__('custody', calls['custody'] + 1) or counted(account)
        self.adapters['memory'] = memory
        job = self.jobs.request_deletion('a', 'actor-a')
        self.jobs.tick()
        row = self.rows('SELECT state,waiting_for FROM account_jobs WHERE id=?', (job,))[0]
        self.assertEqual((row['state'], row['waiting_for']), ('waiting', 'memory'))
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 1)       # nothing after the failed store was touched yet
        self.run_jobs()
        self.assertEqual(self.rows('SELECT state FROM account_jobs WHERE id=?', (job,))[0]['state'], 'completed')
        self.assertEqual(calls, {'memory': 3, 'custody': 1})                                               # the store that worked was handled once

    def test_the_scan_reports_what_it_finds_instead_of_calling_it_clean(self):
        self.adapters['scan'] = lambda account: {'memory': 2}
        job = self.jobs.request_deletion('a', 'actor-a'); self.run_jobs()
        row = self.rows('SELECT state,report_json FROM account_jobs WHERE id=?', (job,))[0]
        self.assertEqual(row['state'], 'failed')
        self.assertEqual(json.loads(row['report_json'])['verification']['found'], {'outside.memory': 2})

    def test_deletion_waits_for_running_work_to_stop(self):
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running' WHERE account_id='a'")
        job = self.jobs.request_deletion('a', 'actor-a'); self.jobs.tick()
        self.assertEqual(self.rows('SELECT waiting_for FROM account_jobs WHERE id=?', (job,))[0]['waiting_for'], 'running_tasks')
        self.assertEqual(self.rows("SELECT cancel_requested FROM customer_requests WHERE account_id='a'")[0]['cancel_requested'], 1)
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='cancelled' WHERE account_id='a'")
        self.run_jobs()
        self.assertEqual(self.rows('SELECT state FROM account_jobs WHERE id=?', (job,))[0]['state'], 'completed')

    def test_one_chat_can_be_deleted_and_files_it_made_keep_an_empty_record(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-empty','d-a')")
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','c-empty','customer','just talk')")
        gone = self.jobs.delete_conversation(self.a, 'c-empty')
        self.assertEqual((gone['removed']['messages'], gone['kept_empty_record']), (1, False))
        self.assertEqual(self.rows("SELECT count(*) AS n FROM conversations WHERE id='c-empty'")[0]['n'], 0)
        kept = self.jobs.delete_conversation(self.a, 'c-a')
        self.assertEqual((kept['files_kept'], kept['kept_empty_record']), (1, True))
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 0)
        self.assertEqual(self.rows("SELECT message FROM customer_requests WHERE account_id='a'")[0]['message'], '[deleted]')
        self.assertEqual(self.rows("SELECT count(*) AS n FROM actions WHERE account_id='a'")[0]['n'], 0)
        self.assertIsNotNone(self.rows("SELECT deleted_epoch FROM conversations WHERE id='c-a'")[0]['deleted_epoch'])
        with self.assertRaises(NotFound):
            self.jobs.delete_conversation(self.a, 'c-a')                                                   # it is gone for its customer
        with self.assertRaises(NotFound):
            self.jobs.delete_conversation(self.a, 'c-b')                                                   # and another account's chat was never theirs
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='b'")[0]['n'], 1)


class Offboarding(Base):
    def test_the_guided_flow_stop_export_choice_connections_subscription_cooling_off_delete_confirm(self):
        started = self.jobs.start_offboarding(self.a)
        self.assertEqual((started['state'], started['waiting_for']), ('waiting', 'export_choice'))
        self.assertEqual(self.rows("SELECT state FROM schedules WHERE account_id='a'")[0]['state'], 'paused')              # 1. work is stopped
        self.run_jobs()
        self.assertEqual(self.jobs.offboarding(self.a)['waiting_for'], 'export_choice')                                    # 2. it waits for the choice
        self.assertEqual(self.rows("SELECT state FROM connector_connections WHERE account_id='a'")[0]['state'], 'connected')
        self.jobs.choose_export(self.a, True)
        self.run_jobs()
        view = self.jobs.offboarding(self.a)
        self.assertEqual(view['waiting_for'], 'cooling_off')
        steps = {s['step']: s for s in view['steps']}
        self.assertEqual(steps['export']['detail']['state'], 'completed')                                                  # the export was made first
        self.assertEqual(self.rows("SELECT state FROM connector_connections WHERE account_id='a'")[0]['state'], 'revoked')  # 3. every connection ended
        self.assertEqual(self.rows("SELECT source FROM connector_revocations WHERE account_id='a'")[0]['source'], 'offboarding')
        self.assertEqual(steps['subscription']['detail'], {'cancelled': 1})                                                # 4. the subscription cancelled
        self.assertEqual(self.rows("SELECT status FROM accounts WHERE id='a'")[0]['status'], 'active')                     # nothing deleted during the cooling-off
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 1)
        self.now += 7 * 86400 + 1
        self.run_jobs(8)
        with self.store.connect() as con:
            job = con.execute("SELECT state,report_json FROM account_jobs WHERE account_id='a' AND kind='offboarding'").fetchone()
        self.assertEqual(job['state'], 'completed')                                                                        # 5. deleted
        self.assertTrue(json.loads(job['report_json'])['verification']['clean'])
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 0)
        self.assertEqual(len(self.outside['mail']), 1)                                                                     # 6. confirmed, with the report
        self.assertTrue(self.outside['mail'][0][1]['verification']['clean'])
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='b'")[0]['n'], 1)

    def test_the_customer_can_cancel_during_the_cooling_off_and_nothing_was_deleted(self):
        self.jobs.start_offboarding(self.a)
        with self.assertRaises(Conflict):
            self.jobs.start_offboarding(self.a)
        self.jobs.choose_export(self.a, False)
        self.run_jobs()
        self.now += 3 * 86400
        self.run_jobs()
        self.assertEqual(self.jobs.cancel_offboarding(self.a)['state'], 'cancelled')
        self.now += 30 * 86400
        self.run_jobs()
        self.assertEqual(self.rows("SELECT status FROM accounts WHERE id='a'")[0]['status'], 'active')
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 1)
        self.assertEqual(self.rows("SELECT state FROM schedules WHERE account_id='a'")[0]['state'], 'active')              # its schedule runs again
        with self.assertRaises(Conflict):
            self.jobs.cancel_offboarding(self.a)

    def test_once_the_deletion_has_started_it_cannot_be_cancelled(self):
        self.jobs = AccountJobs(self.store, storage=self.files, adapters={**self.adapters, 'cell': lambda account: 'waiting'}, signing_key=KEY, clock=lambda: self.now, cooling_off=0)
        self.jobs.start_offboarding(self.a); self.jobs.choose_export(self.a, False)
        self.run_jobs()
        self.assertEqual(self.rows("SELECT status FROM accounts WHERE id='a'")[0]['status'], 'deleting')

    def test_removing_a_member_offboards_that_members_data_and_nobody_elses(self):
        self.orgs.add_member(self.a, 'b', 'actor-b', 'member')
        with self.assertRaises(Exception):
            self.jobs.start_offboarding(self.b, for_account='a')                                           # a member cannot remove anyone
        self.jobs = AccountJobs(self.store, storage=self.files, adapters=self.adapters, signing_key=KEY, clock=lambda: self.now, cooling_off=0)
        self.orgs.remove_member(self.a, 'actor-b')
        job = self.jobs.start_offboarding_by_operator('b', 'owner-of-the-organization', cooling_off=0)
        self.run_jobs(8)
        self.assertEqual(self.rows('SELECT state FROM account_jobs WHERE id=?', (job,))[0]['state'], 'completed')
        self.assertEqual(self.rows("SELECT status FROM accounts WHERE id='b'")[0]['status'], 'deleted')
        self.assertEqual(self.rows("SELECT count(*) AS n FROM chat_messages WHERE account_id='a'")[0]['n'], 1)             # the organization and its other members are untouched
        self.assertEqual(self.rows("SELECT status FROM organizations WHERE id='a'")[0]['status'], 'active')

    def test_a_stranger_cannot_start_see_or_cancel_anothers_offboarding(self):
        self.jobs.start_offboarding(self.a)
        self.assertIsNone(self.jobs.offboarding(self.b))
        with self.assertRaises(Conflict):
            self.jobs.cancel_offboarding(self.b)
        with self.assertRaises(NotFound):
            self.jobs.start_offboarding(self.b, for_account='a')


if __name__ == '__main__':
    unittest.main()
