"""Approvals in place (reliability plan, Part 6; owner switch `approve_in_place`): a change the assistant prepared, or a connected app's call that needs permission,
holds its tool call while the customer decides. Decided in time, the change is made and the same run gets what happened; no second turn is started and nothing is
steered into the run. Not decided in time, the approval stays open and resumes as a new turn when it is decided, as before. Nothing is ever sent without approval."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from agentai_platform import in_place
from agentai_platform.connector_tools import ConnectorTools
from agentai_platform.handoff import IN_PLACE_SECONDS, SEEN_SECONDS
from agentai_platform.hub_tools import HubTools
from agentai_platform.mcp_connections.service import ConnectionService, namespaced
from agentai_platform.model_keys import ModelKeyring
from agentai_platform.security import Principal
from agentai_platform.store import Store
from tests.connector_fixture import ConnectorBase
from tests.mcp_fixture import Fixture, URL

NOTE = {'folder': 'inbox', 'title': 'Plan', 'body': 'First draft'}
FAST = lambda s: time.sleep(0.005)


def in_thread(fn):
    out = []
    thread = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    thread.start()
    return thread, out


def until(check, seconds=5):
    deadline = time.time() + seconds
    while not check() and time.time() < deadline:
        time.sleep(0.005)
    return check()


class ChangesInPlace(ConnectorBase):
    def setUp(self):
        super().setUp()
        self.connection = self.connect()
        self.spawned, self.switch = [], True
        test = self

        class Chat:
            def _spawn(self, principal, conversation_id, **kw):
                test.spawned.append(kw)
                return {'id': 'resumed-' + str(len(test.spawned))}
        self.runner.chat = Chat()
        self.tools = ConnectorTools(self.store, self.connectors, self.client, self.actions, self.workflows, clock=lambda: self.now, enabled=lambda a: True,
                                    writes_on=lambda a, s=None: True, approve_in_place=lambda a: self.switch, sleep=FAST, poll_seconds=0)

    def notes(self):
        return [r['title'] for r in self.bench.rows('a') if r['kind'] == 'note']

    def propose(self):
        return in_thread(lambda: self.tools.call('a', {'connection': self.connection, 'kind': 'note.create', 'payload': NOTE}, name='lumina_connector_propose', request_id='req-a'))

    def waiting_for(self):
        with self.store.connect() as con:
            return in_place.waiting(con, 'a', 'req-a', self.now)

    def action(self):
        return self.rows("SELECT * FROM actions WHERE account_id='a'")[0]

    def test_a_change_approved_while_the_task_waits_is_made_and_its_outcome_goes_to_the_same_run(self):
        thread, out = self.propose()
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))                    # the driver parks the run on this
        action = self.action()
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.assertEqual(self.waiting_for(), 'customer_approval')                                    # approved, not made yet: the run still waits for what happened
        self.runner.tick()                                                                         # Lumina makes the change (once), and starts no turn for it
        thread.join(5)
        text, problem = out[0]
        self.assertFalse(problem)
        self.assertIn('Lumina carried it out once', text)
        self.assertEqual(self.notes(), ['Plan'])
        self.runner.tick()
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.rows("SELECT state,resumed_request_id FROM handoffs WHERE account_id='a'")[0]['resumed_request_id'], 'req-a')
        self.assertIsNone(self.waiting_for())

    def test_a_declined_change_is_said_to_the_same_run_and_nothing_is_changed(self):
        thread, out = self.propose()
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.actions.decline(self.a, self.action()['id'])
        thread.join(5)
        self.assertIn('DECLINED', out[0][0])
        self.assertEqual((self.notes(), self.spawned), ([], []))

    def test_when_nobody_decides_in_time_the_approval_stays_open_and_resumes_as_a_new_turn(self):
        thread, out = self.propose()
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.now += IN_PLACE_SECONDS
        thread.join(5)
        self.assertIn('END YOUR TURN', out[0][0]); self.assertIn('has not decided', out[0][0])
        self.assertIsNone(self.waiting_for())
        action = self.action()
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.runner.tick(); self.runner.tick()
        self.assertEqual(self.notes(), ['Plan'])
        self.assertEqual(len(self.spawned), 1)
        self.assertIn('carried it out once', self.spawned[0]['message'])

    def test_a_change_decided_but_not_yet_made_when_the_window_ends_is_resumed_once_by_the_runner(self):
        thread, out = self.propose()
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        action = self.action()
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.now += IN_PLACE_SECONDS
        thread.join(5)
        self.assertIn('carrying it out now', out[0][0])
        self.runner.tick(); self.runner.tick()
        self.assertEqual((self.notes(), len(self.spawned)), (['Plan'], 1))

    def test_with_the_switch_off_the_change_ends_the_turn_as_before(self):
        self.switch = False
        text, problem = self.tools.call('a', {'connection': self.connection, 'kind': 'note.create', 'payload': NOTE}, name='lumina_connector_propose', request_id='req-a')
        self.assertIn('NOT SENT', text)
        self.assertIsNone(self.waiting_for())

    def test_several_changes_approved_together_while_the_task_waits(self):
        steps = [{'connection': self.connection, 'kind': 'note.create', 'payload': {**NOTE, 'title': t}} for t in ('One', 'Two')]
        thread, out = in_thread(lambda: self.tools.call('a', {'title': 'Set up', 'steps': steps}, name='lumina_connector_workflow', request_id='req-a'))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        workflow = self.rows("SELECT * FROM workflows WHERE account_id='a'")[0]
        self.workflows.approve(self.a, workflow['id'], workflow['steps_hash'])
        for _ in range(4):
            self.runner.tick()
        thread.join(5)
        self.assertIn('was approved and run by Lumina', out[0][0])
        self.assertEqual((sorted(self.notes()), self.spawned), (['One', 'Two'], []))

    def test_the_mail_and_calendar_tools_wait_the_same_way(self):
        hub = HubTools(self.store, None, clock=lambda: self.now, actions=self.actions, approve_in_place=lambda a: True, sleep=FAST, poll_seconds=0)
        action = self.actions.propose(self.a, self.connection, 'note.create', NOTE, request_id='req-a')
        thread, out = in_thread(lambda: hub._held(self.a, 'req-a', lambda: False, action))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.actions.approve(self.a, action['id'], action['payload_hash'])
        self.runner.tick()
        thread.join(5)
        self.assertIn('carried it out once', out[0][0])
        self.assertEqual(self.spawned, [])

    def test_a_stopped_task_leaves_the_approval_waiting_and_sends_nothing(self):
        thread, out = self.propose()
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET cancel_requested=1 WHERE account_id='a' AND id='req-a'")
        thread.join(5)
        self.assertEqual(out[0][1].reason, 'tool.stopped_with_task')
        self.assertEqual((self.action()['state'], self.notes()), ('proposed', []))


class ConnectedAppCallsInPlace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3'); self.store.initialize()
        self.fixture = Fixture(); self.addCleanup(self.fixture.close)
        self.now, self.switch = 2000000000, True
        with self.store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')")
            con.execute("INSERT INTO memberships(account_id,actor_id,role,status) VALUES ('a','a','customer','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','d',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p','c','d')")
            con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                VALUES ('a','r1','a','p','c','k','h','m','running',1)''')
        self.a = Principal('a', 'a', 'customer')
        self.service = ConnectionService(self.store, ModelKeyring.derived('s' * 64), callback_url='https://lumina.mcp-demo.net/v1/account/mcp/callback', remote=self.fixture.remote(),
                                         approve_in_place=lambda a: self.switch, sleep=FAST, poll_seconds=0)
        cid = self.service.create(self.a, name='Fixture', url=URL, auth_method='none', token='')
        self.assertTrue(self.service.test(self.a, cid)['connected'])
        self.service.update(self.a, cid, tools={'echo': True})
        self.name = namespaced(cid, 'echo')
        self.service.clock = lambda: self.now

    def waiting_for(self):
        with self.store.connect() as con:
            return in_place.waiting(con, 'a', 'r1', self.now)

    def pending(self):
        return self.service.listing(self.a)['pending_calls']

    def test_a_call_allowed_while_the_task_waits_runs_in_the_same_call_and_is_not_steered_again(self):
        thread, out = in_thread(lambda: self.service.call('a', self.name, {'text': 'hello'}, 'r1'))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.assertEqual(self.fixture.calls, [])                                                    # nothing runs before the customer allows it
        decided = self.service.approve(self.a, self.pending()[0]['id'], True)
        self.assertTrue(decided['in_place'])                                                         # the route then steers nothing into the run
        thread.join(5)
        self.assertEqual(out[0]['structuredContent'], {'text': 'hello'})
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertIsNone(self.waiting_for())

    def test_a_declined_call_says_so_and_runs_nothing(self):
        thread, out = in_thread(lambda: self.service.call('a', self.name, {'text': 'hello'}, 'r1'))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.service.approve(self.a, self.pending()[0]['id'], False)
        thread.join(5)
        self.assertEqual(out[0]['_fault'].reason, 'tool.approval_declined')
        self.assertEqual(self.fixture.calls, [])

    def test_a_call_the_runtime_gave_up_on_leaves_the_decision_to_reach_the_assistant_as_before(self):
        """(A connected app's approval lasts as long as the window, 10 minutes, so the window cannot end with the approval still open: what can is the runtime dropping
        the call.)"""
        dropped = threading.Event()
        thread, out = in_thread(lambda: self.service.call('a', self.name, {'text': 'hello'}, 'r1', closed=dropped.is_set))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        dropped.set()
        thread.join(5)
        self.assertEqual(out[0]['_fault'].reason, 'tool.approval_needed')
        self.assertIsNone(self.waiting_for())
        self.assertFalse(self.service.approve(self.a, self.pending()[0]['id'], True)['in_place'])       # the route steers it into the run, or starts a turn
        self.assertEqual(self.fixture.calls, [])

    def test_the_window_ends_when_the_approval_does(self):
        thread, out = in_thread(lambda: self.service.call('a', self.name, {'text': 'hello'}, 'r1'))
        self.assertTrue(until(lambda: self.waiting_for() == 'customer_approval'))
        self.now += IN_PLACE_SECONDS
        thread.join(5)
        self.assertEqual(out[0]['_fault'].reason, 'tool.approval_needed')
        self.assertEqual((self.pending(), self.fixture.calls), ([], []))

    def test_a_wait_whose_call_was_lost_is_not_taken_for_one(self):
        self.switch = False
        self.service.call('a', self.name, {'text': 'hello'}, 'r1')
        with self.store.connect() as con:
            con.execute("UPDATE mcp_calls SET wait_until=?,wait_seen=?", (self.now + 300, self.now - SEEN_SECONDS - 1))
        self.assertIsNone(self.waiting_for())
        self.assertFalse(self.service.approve(self.a, self.pending()[0]['id'], True)['in_place'])

    def test_with_the_switch_off_or_outside_a_task_the_call_asks_and_returns_as_before(self):
        self.switch = False
        self.assertEqual(self.service.call('a', self.name, {'text': 'hello'}, 'r1')['_fault'].reason, 'tool.approval_needed')
        self.switch = True
        self.assertEqual(self.service.call('a', self.name, {'text': 'other'}, 'not-a-task')['_fault'].reason, 'tool.approval_needed')
        self.assertIsNone(self.waiting_for())


if __name__ == '__main__':
    unittest.main()
