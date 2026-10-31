import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from agentai_platform.ops.restore import RestoreError, SCOPE, check_classified, restore_account
from agentai_platform.store import Store

A, B = 'a', 'b'


def put(con, sql, *args): con.execute(sql, args)


class RestoreChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.live = self.root / 'live.sqlite3'
        Store(self.live).initialize()
        con = self.connect(self.live)
        for acct in (A, B):
            put(con, "INSERT INTO accounts(id,status) VALUES (?,'active')", acct)
            put(con, "INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", acct, 'd-' + acct)
            put(con, "INSERT INTO projects(account_id,id,name) VALUES (?,?,?)", acct, 'p-' + acct, 'Project ' + acct)
            put(con, "INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", acct, 'p-' + acct, 'c-' + acct, 'd-' + acct)
            put(con, "INSERT INTO entitlements VALUES (?,?,'plan','active','{}','2099-01-01T00:00:00Z')", acct, 'paid')
        put(con, "INSERT INTO chat_messages(account_id,conversation_id,id,provenance,content,created_at) VALUES ('a','c-a',7,'customer','a-hello','2026-01-01T00:00:00Z')")
        put(con, "INSERT INTO chat_messages(account_id,conversation_id,id,provenance,content,created_at) VALUES ('b','c-b',8,'customer','b-secret','2026-01-01T00:00:00Z')")
        put(con, "INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p-a','c-a','t-done','completed',10)")
        put(con, "INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','p-a','c-a','t-run','running',10)")
        put(con, "INSERT INTO task_reservations VALUES ('a','t-run','k1','h1','paid',10,'active',1)")
        put(con, "INSERT INTO schedules(account_id,project_id,id,name,timezone,hour_local,minute_local,timeout_seconds,task_budget_microusd,state,created_epoch) VALUES ('a','p-a','s1','daily','UTC',9,0,60,10,'active',1)")
        put(con, "INSERT INTO browser_profiles(account_id,id,label,allowed_hosts,credential_ref,session_ref,state,created_epoch) VALUES ('a','bp1','bank','[]','cred-1','sess-1','active',1)")
        con.commit(); con.close()
        self.backup = self.root / 'backup.sqlite3'
        src = sqlite3.connect(self.live); dst = sqlite3.connect(self.backup); src.backup(dst); dst.close(); src.close()
        # ---- what happens after the backup (the reason for the restore)
        con = self.connect(self.live)
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("DELETE FROM chat_messages WHERE account_id='a'")                     # A's content was lost
        con.execute("DELETE FROM schedules WHERE account_id='a'"); con.execute("DELETE FROM browser_profiles WHERE account_id='a'")
        con.execute("UPDATE tasks SET state='completed' WHERE id='t-run'"); con.execute("UPDATE task_reservations SET state='settled'")
        put(con, "INSERT INTO chat_messages(account_id,conversation_id,id,provenance,content,created_at) VALUES ('a','c-a',9,'customer','a-after-backup','2026-02-01T00:00:00Z')")
        put(con, "INSERT INTO chat_messages(account_id,conversation_id,id,provenance,content,created_at) VALUES ('b','c-b',7,'customer','b-reused-id','2026-02-01T00:00:00Z')")  # id 7 now belongs to B
        put(con, "INSERT INTO usage_entries(account_id,task_id,id,provider,provider_request_id,kind,amount_microusd,currency,price_version) VALUES ('a','t-done','u1','p','r1','reported',500,'USD','v')")
        put(con, "UPDATE entitlements SET status='expired' WHERE account_id='a'")      # billing moved on since the backup
        put(con, "INSERT INTO projects(account_id,id,name) VALUES ('a','p-new','Created after backup')")
        con.commit(); con.close()
        self.out = self.root / 'restored.sqlite3'

    @staticmethod
    def connect(path):
        con = sqlite3.connect(path); con.execute('PRAGMA foreign_keys=ON'); return con

    def q(self, sql, *args, db=None):
        con = sqlite3.connect(db or self.out)
        try: return con.execute(sql, args).fetchall()
        finally: con.close()

    def digest(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_account_a_content_returns_while_b_and_the_ledger_are_untouched(self):
        live_before = self.digest(self.live)
        report = restore_account(self.backup, self.live, A, self.out)
        self.assertEqual(self.digest(self.live), live_before)                              # the live database is never written
        self.assertTrue(report['other_accounts_unchanged'] and report['ledger_intact'] and report['billing_requires_reconcile'])
        contents = {r[0] for r in self.q("SELECT content FROM chat_messages WHERE account_id='a'")}
        self.assertEqual(contents, {'a-hello', 'a-after-backup'})                          # lost message back, newer one kept
        self.assertEqual(set(self.q("SELECT id,content FROM chat_messages WHERE account_id='b'")), {(8, 'b-secret'), (7, 'b-reused-id')})
        ids = [r[0] for r in self.q("SELECT id FROM chat_messages WHERE account_id='a' AND content='a-hello'")]
        self.assertNotIn(7, ids)                                                           # global ids never carried over (B owns 7 live)
        self.assertEqual(len(self.q("SELECT 1 FROM projects WHERE account_id='a'")), 2)    # backup project restored, post-backup project kept
        self.assertEqual(self.q("SELECT amount_microusd FROM usage_entries"), [(500,)])    # spend history not rolled back
        self.assertEqual(self.q("SELECT status FROM entitlements WHERE account_id='a'"), [('expired',)])   # old access not reinstated

    def test_nothing_restored_can_act_by_itself(self):
        report = restore_account(self.backup, self.live, A, self.out)
        self.assertEqual(self.q("SELECT state FROM schedules WHERE id='s1'"), [('paused',)])
        self.assertEqual(self.q("SELECT state,credential_ref,session_ref FROM browser_profiles WHERE id='bp1'"), [('revoked', None, None)])
        self.assertEqual(self.q("SELECT state FROM tasks WHERE id='t-run'"), [('completed',)])        # live (newer) state wins
        self.assertEqual(self.q("SELECT state FROM task_reservations WHERE task_id='t-run'"), [('settled',)])
        self.assertGreaterEqual(report['neutralized']['schedules_paused'], 1)

    def test_a_run_restored_mid_flight_is_stopped_with_its_goal_and_its_sessions_come_back(self):
        con = self.connect(self.live)
        put(con, "INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch,conversation_id,parked_reason,continue_goal,goal_mode) "
                 "VALUES ('a','r1','x','p-a','k','h','m','running',1,'c-a','browser_question',1,1)")
        put(con, "INSERT INTO customer_requests(account_id,id,actor_id,project_id,idempotency_key,payload_hash,message,state,created_epoch,conversation_id,continue_goal,goal_mode) "
                 "VALUES ('a','r0','x','p-a','k0','h','m','completed',1,'c-a',1,1)")
        put(con, "INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_run_id,created_epoch,updated_epoch,kind) VALUES ('a','r1',1,'r1-a1','h','acknowledged','r1-a1',5,5,'turn')")
        put(con, "INSERT INTO browse_sessions(account_id,request_id,session,job_id,n_offset,created_epoch) VALUES ('a','r1',2,?,3,5)", 'f' * 32)
        con.commit(); con.close()
        backup = self.root / 'with-run.sqlite3'
        src = sqlite3.connect(self.live); dst = sqlite3.connect(backup); src.backup(dst); dst.close(); src.close()
        con = self.connect(self.live); con.execute('PRAGMA foreign_keys=OFF')
        for table in ('chat_deliveries', 'browse_sessions', 'customer_requests'):
            con.execute(f"DELETE FROM {table} WHERE account_id='a'")
        con.commit(); con.close()
        report = restore_account(backup, self.live, A, self.out)
        self.assertEqual(self.q("SELECT state,outcome,parked_reason,continue_goal FROM customer_requests WHERE id='r1'"), [('cancelled', 'cancelled', None, 0)])        # nothing resumes by itself
        self.assertEqual(self.q("SELECT state,continue_goal FROM customer_requests WHERE id='r0'"), [('completed', 0)])                                         # a goal waiting for its next turn does not get one
        self.assertEqual(self.q("SELECT state FROM chat_deliveries WHERE request_id='r1'"), [('aborted',)])                                                  # the runtime's run is not in the restored cell
        self.assertEqual(self.q("SELECT session,job_id,n_offset FROM browse_sessions WHERE request_id='r1'"), [(2, 'f' * 32, 3)])
        self.assertEqual(report['neutralized']['goals_stopped'], 1)

    def test_missing_in_flight_work_comes_back_blocked_with_no_open_reservation(self):
        con = self.connect(self.live); con.execute("DELETE FROM task_reservations"); con.execute("DELETE FROM tasks WHERE id='t-run'"); con.commit(); con.close()
        restore_account(self.backup, self.live, A, self.out)
        self.assertEqual(self.q("SELECT state FROM tasks WHERE id='t-run'"), [('blocked',)])
        self.assertEqual(self.q("SELECT state FROM task_reservations WHERE task_id='t-run'"), [('settled',)])

    def test_preconditions_and_failures_leave_no_output(self):
        con = self.connect(self.live); con.execute("UPDATE tasks SET state='running' WHERE id='t-run'"); con.commit(); con.close()
        with self.assertRaises(RestoreError): restore_account(self.backup, self.live, A, self.out)
        self.assertFalse(self.out.exists())
        con = self.connect(self.live); con.execute("UPDATE tasks SET state='completed' WHERE id='t-run'"); con.commit(); con.close()
        with self.assertRaises(RestoreError): restore_account(self.backup, self.live, 'ghost', self.out)
        self.out.write_text('keep')
        with self.assertRaises(RestoreError): restore_account(self.backup, self.live, A, self.out)
        self.assertEqual(self.out.read_text(), 'keep')

    def test_a_table_nobody_classified_stops_the_restore(self):
        con = self.connect(self.live); con.execute('CREATE TABLE brand_new_feature(account_id TEXT, x TEXT)'); con.commit(); con.close()
        with self.assertRaises(RestoreError) as caught: restore_account(self.backup, self.live, A, self.out)
        self.assertIn('brand_new_feature', str(caught.exception)); self.assertFalse(self.out.exists())

    def test_every_table_in_the_shipped_schema_is_classified(self):
        con = sqlite3.connect(self.live); check_classified(con); con.close()
        self.assertTrue({'usage_entries', 'provider_receipts', 'entitlements', 'billing_subscriptions', 'telegram_outbox'} <= set(SCOPE))
        self.assertEqual(SCOPE['entitlements'], 'live'); self.assertEqual(SCOPE['usage_entries'], 'ledger')

    def test_tombstoned_conversations_are_not_resurrected(self):
        con = self.connect(self.live)
        con.execute('CREATE TABLE accounts_tombstone(id INTEGER PRIMARY KEY, account_id TEXT, object_id TEXT, kind TEXT)')
        con.execute("INSERT INTO accounts_tombstone(account_id,object_id,kind) VALUES ('a','c-a','conversation')"); con.commit(); con.close()
        bk = sqlite3.connect(self.backup); bk.execute('CREATE TABLE accounts_tombstone(id INTEGER PRIMARY KEY, account_id TEXT, object_id TEXT, kind TEXT)'); bk.commit(); bk.close()
        report = restore_account(self.backup, self.live, A, self.out)
        self.assertEqual(report['skipped_tombstoned_conversations'], 1)
        self.assertNotIn('a-hello', {r[0] for r in self.q("SELECT content FROM chat_messages WHERE account_id='a'")})
if __name__ == '__main__': unittest.main()
