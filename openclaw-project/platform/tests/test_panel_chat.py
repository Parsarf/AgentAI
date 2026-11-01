"""ChatService changes for the side panel: the `surface` label on a message, and the compact view the panel reads."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.store import Store

LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000, 'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class PanelChatChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3'); self.store.initialize()
        self.now = 2000000000
        self.service = ChatService(self.store, queue=RequestQueue(self.store, clock=lambda: self.now), ledger=BudgetLedger(self.store, service_limit_microusd=10000000, clock=lambda: self.now),
                                   pricer=FixedRoute(500), clock=lambda: self.now)
        self.a, self.b = Principal('a', 'actor-a', 'customer'), Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for a in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (a, 'd-' + a))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (a, 'p-' + a, 'Project ' + a))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)', (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))", (a, 'e-' + a, json.dumps(LIMITS), self.now + 1000000))

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def test_surface_is_recorded_only_when_given_and_audited_apart(self):
        web = self.service.send(self.a, conversation_id='c-a', message='from the web', key='key-web-1')
        self.assertIsNone(self.rows('SELECT surface FROM chat_messages WHERE request_id=?', (web['id'],))[0][0])
        self.service.queue.cancel(self.a, web['id'])
        panel = self.service.send(self.a, conversation_id='c-a', message='from the panel', key='key-panel-1', surface='panel')
        self.assertEqual(self.rows('SELECT surface FROM chat_messages WHERE request_id=? AND provenance=?', (panel['id'], 'customer'))[0][0], 'panel')
        self.assertTrue(self.rows("SELECT 1 FROM audit_events WHERE object_id=? AND action LIKE '%chat.send.panel'", (panel['id'],)))
        self.assertTrue(self.rows("SELECT 1 FROM audit_events WHERE object_id=? AND action LIKE '%chat.send'", (web['id'],)))

    def test_an_unknown_surface_is_refused_and_nothing_is_written(self):
        for surface in ['telegram', '', 'PANEL', 5]:
            with self.assertRaises(ValueError):
                self.service.send(self.a, conversation_id='c-a', message='x', key='key-bad-1', surface=surface)
        self.assertEqual(self.rows('SELECT count(*) FROM chat_messages')[0][0], 0)

    def test_the_database_itself_refuses_other_labels(self):
        with self.store.connect() as con:
            with self.assertRaises(Exception):
                con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content,surface) VALUES ('a','c-a','customer','x','web')")

    def test_messages_listing_carries_the_surface(self):
        self.service.send(self.a, conversation_id='c-a', message='hello', key='key-panel-2', surface='panel')
        self.assertEqual(self.service.messages(self.a, 'c-a')['messages'][0]['surface'], 'panel')

    def test_panel_view_is_recent_oldest_first_and_reports_the_live_run(self):
        view = self.service.panel_view(self.a, 'c-a')
        self.assertEqual((view['messages'], view['request'], view['live'], view['live_request_id']), ([], None, False, None))
        first = self.service.send(self.a, conversation_id='c-a', message='first', key='key-view-1')
        self.service.queue.cancel(self.a, first['id'])
        second = self.service.send(self.a, conversation_id='c-a', message='second', key='key-view-2')
        view = self.service.panel_view(self.a, 'c-a')
        self.assertEqual([m['content'] for m in view['messages'] if m['provenance'] == 'customer'], ['first', 'second'])       # cancelling the first left a system note between them
        self.assertEqual([m['id'] for m in view['messages']], sorted(m['id'] for m in view['messages']))
        self.assertEqual(view['request']['id'], second['id'])
        self.assertFalse(view['live'])                                   # waiting is not a run that takes a steer
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running' WHERE account_id='a' AND id=?", (second['id'],))
        view = self.service.panel_view(self.a, 'c-a')
        self.assertEqual((view['live'], view['live_request_id']), (True, second['id']))
        self.assertEqual([m['content'] for m in self.service.panel_view(self.a, 'c-a', limit=1)['messages']], ['second'])

    def test_panel_view_is_scoped_and_validates_its_limit(self):
        self.service.send(self.a, conversation_id='c-a', message='private to a', key='key-view-3')
        with self.assertRaises(NotFound):
            self.service.panel_view(self.b, 'c-a')
        for limit in [0, 51, '5', True]:
            with self.assertRaises(ValueError):
                self.service.panel_view(self.a, 'c-a', limit=limit)
        self.assertEqual(self.service.panel_view(self.b, 'c-b')['messages'], [])


if __name__ == '__main__':
    unittest.main()
