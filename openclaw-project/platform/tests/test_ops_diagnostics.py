import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.ops.diagnostics import collect, label
from agentai_platform.store import Store


class DiagnosticsChecks(unittest.TestCase):
    def test_support_sees_states_and_hashes_but_never_content_or_references(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / 'db.sqlite3'; Store(db).initialize(); store = Store(db)
            with store.connect() as con:
                con.execute("INSERT INTO accounts(id,status) VALUES ('acct-secret-name','active')")
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('acct-secret-name','d1',1,'stopped')")
                con.execute("INSERT INTO projects(account_id,id,name) VALUES ('acct-secret-name','p1','CANARY-PROJECT-NAME')")
                con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('acct-secret-name','p1','c1','d1')")
                con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('acct-secret-name','c1','customer','CANARY-PRIVATE-MESSAGE sk_test_abcdefghijkl')")
                con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('acct-secret-name','p1','c1','t1','failed',5)")
                con.execute("CREATE TABLE accounts_audit(account_id TEXT,action TEXT,created_at TEXT)")
                con.execute("INSERT INTO accounts_audit VALUES ('acct-secret-name','genui.save_failed.network',datetime(2000000000,'unixepoch'))")
                con.execute("INSERT INTO accounts_audit VALUES ('acct-secret-name','genui.CANARY-private-message',datetime(2000000000,'unixepoch'))")
                con.execute("INSERT INTO entitlements VALUES ('acct-secret-name','open','plan','active','{}','2099-01-01T00:00:00Z')")
            report = collect(db, clock=lambda: 2_000_000_000, monitor_status={'overall': 'warn', 'checks': [{'check': 'disk', 'status': 'warn'}, {'check': 'x', 'status': 'ok'}]},
                             backup_status={'last_success_epoch': 5, 'last_complete': True, 'offsite_copy': False, 'failures': [{'error': 'private'}]})
            text = json.dumps(report)
            for secret in ('CANARY', 'acct-secret-name', 'sk_test', 'private'): self.assertNotIn(secret, text)
            entry = report['accounts'][0]
            self.assertEqual(entry['account'], label('acct-secret-name')); self.assertEqual(entry['tasks'], {'failed': 1}); self.assertEqual(entry['entitlement']['status'], 'active')
            self.assertEqual(entry['ui_failures_24h'], {'genui.save_failed.network': 1})
            self.assertEqual(report['monitor']['failing'], ['disk']); self.assertEqual(report['backup']['offsite_copy'], False)
if __name__ == '__main__': unittest.main()
