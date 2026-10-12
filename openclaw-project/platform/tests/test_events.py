import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.events import EventService, normalize, redact, RETENTION_DAYS
from agentai_platform.chat import ChatService, ChatDriver, FixedRoute, synthetic_gateway_factory
from agentai_platform.events import EventService as ES
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.budget import BudgetLedger
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.capacity import CapacityResult
from agentai_platform.store import Store

CAPACITY = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000,
          'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class RedactionChecks(unittest.TestCase):
    def test_secret_patterns_redacted_recursively(self):
        payload = {'summary': 'token sk-abcdefgh12345678 found', 'nested': {'cmd': 'ghp_' + 'a' * 30},
                   'list': ['eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9', 'safe'], 'n': 5}
        out = redact(payload)
        self.assertNotIn('sk-abcdefgh', out['summary'])
        self.assertNotIn('ghp_', out['nested']['cmd'])
        self.assertNotIn('eyJ', out['list'][0])
        self.assertEqual(out['list'][1], 'safe')
        self.assertEqual(out['n'], 5)

    def test_normalize_allowlists_keys_per_kind(self):
        self.assertEqual(normalize('error', {'summary': 'x', 'category': 'timeout'}), {'summary': 'x', 'category': 'timeout'})
        with self.assertRaises(ValueError):
            normalize('nope', {})
        with self.assertRaises(ValueError):
            normalize('progress', {'secret_key': 'x'})
        big = normalize('result', {'summary': 'x' * 50000})
        self.assertTrue(big['truncated'])


class EventChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite3');self.store.initialize()
        self.now = 2000000000
        self.events = EventService(self.store, clock=lambda:self.now)
        self.gateway = SyntheticGateway()
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10 ** 9, clock=lambda:self.now)
        self.chat = ChatService(self.store, queue=RequestQueue(self.store, clock=lambda:self.now),
                                ledger=self.ledger, pricer=FixedRoute(500), clock=lambda:self.now)
        self.a = Principal('a', 'actor-a', 'customer');self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (x, 'd-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)',
                            (x, 'p-' + x, 'c-' + x, 'd-' + x))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",
                            (x, 'e-' + x, json.dumps(LIMITS), self.now + 1000000))
        result = self.chat.send(self.a, conversation_id='c-a', message='go', key='r1')
        self.task_id = result['id']

    def driver(self):
        return ChatDriver(self.store, ledger=self.ledger,
                          gateway_factory=synthetic_gateway_factory(self.gateway),
                          clock=lambda:self.now, events=self.events)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def test_append_sequence_and_scoped_reads(self):
        self.events.append('a', self.task_id, 'task_started', {'summary': 'dispatched'})
        self.events.append('a', self.task_id, 'progress', {'summary': 'step', 'step': 1})
        page = self.events.events(self.a, self.task_id)
        self.assertEqual([e['sequence'] for e in page['events']], [1, 2])
        self.assertEqual(page['events'][0]['kind'], 'task_started')
        self.assertEqual(page['events'][0]['source'], 'system')
        with self.assertRaises(NotFound):
            self.events.events(self.b, self.task_id)

    def test_unknown_kind_bad_payload_and_missing_task(self):
        with self.assertRaises(ValueError):
            self.events.append('a', self.task_id, 'mystery')
        with self.assertRaises(ValueError):
            self.events.append('a', self.task_id, 'progress', {'token': 'x'})
        with self.assertRaises(NotFound):
            self.events.append('a', 'missing-task', 'progress')

    def test_cursor_replay_gap_free_and_dedup_by_sequence(self):
        for i in range(5):
            self.events.append('a', self.task_id, 'progress', {'summary': f'step {i}', 'step': i})
        page1 = self.events.events(self.a, self.task_id, after=0, limit=2)
        self.assertEqual([e['sequence'] for e in page1['events']], [1, 2])
        page2 = self.events.events(self.a, self.task_id, after=2, limit=100)
        self.assertEqual([e['sequence'] for e in page2['events']], [3, 4, 5])
        # Cursor at the tail: nothing new, nothing repeated.
        self.assertEqual(self.events.events(self.a, self.task_id, after=5)['events'], [])

    def test_payload_redacted_before_storage(self):
        self.events.append('a', self.task_id, 'error',
                           {'summary': 'leak sk-abcdefghijklmnop12 in message', 'category': 'runtime'})
        stored = self.events.events(self.a, self.task_id)['events'][0]
        self.assertNotIn('sk-abcdefghijklmnop12', stored['payload']['summary'])
        self.assertIn('[redacted]', stored['payload']['summary'])

    def test_stream_cap_and_revocation(self):
        opened = []
        for n in range(3):
            sid = f'stream-{n}'
            self.events.open_stream(self.a, self.task_id, sid)
            opened.append(sid)
        with self.assertRaises(Conflict):
            self.events.open_stream(self.a, self.task_id, 'stream-3')
        self.assertTrue(self.events.stream_alive(self.a, opened[0]))
        self.events.close_stream(opened[0])
        self.assertFalse(self.events.stream_alive(self.a, opened[0]))
        # Unlinked account cannot open a stream on someone else's task.
        with self.assertRaises(NotFound):
            self.events.open_stream(self.b, self.task_id, 'stream-b')

    def test_expiry_ends_stream(self):
        self.events.open_stream(self.a, self.task_id, 'sid')
        self.now += 901
        self.assertFalse(self.events.stream_alive(self.a, 'sid'))
        # Expired streams free their cap slot.
        self.events.open_stream(self.a, self.task_id, 'another')
        self.events.open_stream(self.a, self.task_id, 's2')
        self.events.open_stream(self.a, self.task_id, 's3')

    def test_retention_prune(self):
        self.events.append('a', self.task_id, 'task_started')
        self.now += (RETENTION_DAYS + 1) * 86400
        pruned = self.events.prune_expired()
        self.assertEqual(pruned, 1)
        self.assertEqual(self.events.events(self.a, self.task_id)['events'], [])

    def test_synthetic_timeline_survives_restart_without_rerun(self):
        # setUp already queued request r1 (self.task_id).
        claim = self.chat.queue.claim(owner='w', capacity=CAPACITY)
        self.assertEqual(claim.request_id, self.task_id)
        # "Departure": a fresh driver instance (app restart) completes the task.
        fresh_driver = self.driver()
        receipt = fresh_driver.execute(claim)
        self.assertTrue(self.chat.queue.finish(claim, receipt))
        # "Return": a brand-new service instance reads the same durable timeline.
        fresh = EventService(self.store, clock=lambda:self.now)
        page = fresh.events(self.a, self.task_id)
        kinds = [e['kind'] for e in page['events']]
        self.assertEqual(kinds[0], 'task_started')
        self.assertEqual(kinds[-1], 'result')
        self.assertIn('progress', kinds)
        # No repeated execution: exactly one send happened, one transcript row.
        self.assertEqual(sum(1 for call in self.gateway.calls if call[0] == 'send'), 1)
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE conversation_id='c-a'")), 2)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()


if __name__ == '__main__':
    unittest.main()
