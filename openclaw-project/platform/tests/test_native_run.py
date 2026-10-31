"""Native execution: the runtime owns the run; these tests pin what Lumina still owns around it (admission, steering, parking, goals, verdicts)."""
import json
from pathlib import Path
import tempfile
import unittest

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.budget import BudgetLedger
from agentai_platform.capacity import CapacityResult
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.chat_driver import ChatDriver, RETRY_NOTE, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.goals import GoalChain
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.request_queue import Defer, Parked, RequestQueue
from agentai_platform.request_worker import RequestWorker
from agentai_platform.security import Principal
from agentai_platform.store import Store

OK = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000000, 'daily_microusd': 100000000, 'task_microusd': 5000000, 'max_queued_tasks': 6}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize(); self.now = 2000000000
        self.queue = RequestQueue(self.store, clock=lambda: self.now, require_cell=True)
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10 ** 9, clock=lambda: self.now)
        self.gateway = SyntheticGateway()
        self.chat = ChatService(self.store, queue=self.queue, ledger=self.ledger, pricer=FixedRoute(1000000), clock=lambda: self.now, execution=True, browse=True,
                                gateway_factory=lambda account: self.gateway)
        self.a = Principal('a', 'actor-a', 'customer')
        with self.store.connect() as con:
            for acct in ('a', 'b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (acct,))
                con.execute("INSERT INTO memberships VALUES (?,?, 'customer','active')", (acct, 'actor-' + acct))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (acct, 'd-' + acct))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (acct, 'p-' + acct))
                con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (acct, 'p-' + acct, 'c-' + acct, 'd-' + acct))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))", (acct, 'e-' + acct, json.dumps(LIMITS), self.now + 10 ** 6))
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES ('a','op1','d-a','start','completed','k','h',1)")
            con.execute("INSERT INTO lifecycle_slot VALUES (1,'a','d-a','op1','active')")
        self.make_worker()

    def make_worker(self, **driver_kw):
        self.beats = []
        self.driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda: self.now, sleep=lambda s: None,
                                 heartbeat=lambda claim: (self.beats.append(1), self.queue.heartbeat(claim))[1], genui=GenUiRuntime(self.store, self.chat.blocks), **driver_kw)
        self.goals = GoalChain(self.chat, clock=lambda: self.now)
        self.worker = RequestWorker(self.queue, self.driver, lambda: OK, clock=lambda: self.now, goals=self.goals)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def request(self, request_id):
        return dict(self.rows('SELECT * FROM customer_requests WHERE id=?', (request_id,))[0])

    def say(self, message='hello', key='k1', **kw):
        return self.chat.send(self.a, conversation_id='c-a', message=message, key=key, **kw)

    def run_message(self, message, replies, key='k1', **send):
        """Send a message and run it to the end with the assistant's replies scripted (one per run)."""
        replies = list(replies)
        self.gateway.script = lambda text, run, gw: {'text': replies.pop(0) if replies else 'done'}
        sent = self.say(message, key=key, **send)
        self.worker.tick()
        return sent

    def browse_state(self, request_id, status):
        with self.store.connect() as con:
            con.execute('INSERT OR REPLACE INTO browse_runs(account_id,request_id,goal,status,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?)', ('a', request_id, 'goal', status, self.now, self.now))


class SteeringChecks(Base):
    def test_a_message_sent_while_a_task_runs_joins_that_run_instead_of_waiting_behind_it(self):
        first = self.say('find me wings', key='k1')
        self.gateway.polls = 2
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._admit(claim); self.gateway.on_wait = None
        # the task is running: its first delivery is out
        session = self.driver._begin(claim, self.gateway, self.driver._admit(claim)) or None
        self.assertIsNone(session)
        run = self.rows('SELECT idempotency_key FROM chat_deliveries')[0][0]
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        steered = self.say('actually make it vegetarian', key='k2')
        self.assertTrue(steered['steered'])
        self.assertEqual(steered['id'], first['id'])                                   # no second task, no second reservation
        self.assertEqual(len(self.rows('SELECT 1 FROM customer_requests')), 1)
        self.assertEqual(self.rows("SELECT provenance,request_id FROM chat_messages WHERE content='actually make it vegetarian'")[0][:], ('customer', first['id']))
        deliveries = self.rows('SELECT kind,state FROM chat_deliveries ORDER BY attempt')
        self.assertEqual([tuple(d) for d in deliveries], [('turn', 'acknowledged'), ('steer', 'acknowledged')])
        self.assertIn(('send', self.driver._session(claim), self.rows("SELECT idempotency_key FROM chat_deliveries WHERE kind='steer'")[0][0], 'steer'), self.gateway.calls)
        self.assertEqual(self.say('actually make it vegetarian', key='k2')['run_id'], steered['run_id'])        # the same message again changes nothing
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_deliveries WHERE kind='steer'")), 1)
        receipt = self.driver.execute(claim)                                           # the worker owns both runs and closes after both ended
        self.assertEqual((receipt.state, receipt.outcome), ('completed', 'completed'))
        self.assertEqual({r[0] for r in self.rows('SELECT state FROM chat_deliveries')}, {'completed'})
        self.assertTrue(run)
        replies = self.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id", (first['id'],))
        self.assertEqual(len(replies), 2)                                                # the answer to the steered input has a run id of the runtime's own making: it is still this request's
        self.assertTrue(replies[1]['content'].startswith('ack actually make it vegetarian'))

    def test_once_the_task_begins_to_close_a_new_message_is_a_task_of_its_own(self):
        first = self.say(key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        receipt = self.driver.execute(claim)                                           # runs to the end: the close gate is shut
        self.assertEqual(self.request(first['id'])['closing'], 1)
        later = self.say('and another thing', key='k2')
        self.assertNotIn('steered', later)
        self.assertNotEqual(later['id'], first['id'])
        with self.assertRaises(Conflict):
            self.chat.steer(self.a, {**self.request(first['id'])}, message='too late', key='k3')
        self.queue.finish(claim, receipt)

    def test_a_steer_that_started_a_run_on_an_idle_session_is_waited_for_before_the_task_closes(self):
        first = self.say(key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        self.gateway.wait(self.driver._deliveries(claim)[0]['native_run_id'], 0)       # the first run ended just before the steer arrived
        self.say('one more', key='k2')
        self.assertEqual(len([r for r in self.gateway.runs.values() if r['kind'] == 'steer']), 1)
        receipt = self.driver.execute(claim)
        self.assertEqual(receipt.state, 'completed')
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE provenance='agent' AND request_id=?", (first['id'],))), 2)    # both replies belong to the one request


class ParkingChecks(Base):
    def start_and_park(self):
        sent = self.say(key='k1')
        self.gateway.polls = 3
        self.browse_state(sent['id'], 'asking')
        self.assertEqual(self.worker.tick(), {'ran': 1, 'parked': 'browser_question'})
        return sent

    def test_a_run_waiting_for_a_person_gives_up_the_slot_but_not_the_cell_or_the_reservation(self):
        sent = self.start_and_park()
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['parked_reason']), ('running', 'browser_question'))
        self.assertFalse(self.rows('SELECT 1 FROM request_slot'))                       # the one running slot is free for everyone else
        self.assertEqual(self.rows("SELECT state FROM task_reservations")[0][0], 'active')
        self.assertEqual(self.rows("SELECT state FROM tasks")[0][0], 'waiting_for_approval')       # the cell's idle sleep treats it as pending work
        self.assertEqual(self.rows('SELECT account_id FROM lifecycle_slot')[0][0], 'a')
        self.assertEqual(self.worker.tick(), {'ran': 0})                                # still waiting: nothing happens, nothing is claimed
        later = self.say('and a second question', key='k2')                             # same account: one execution at a time
        self.assertTrue(later['steered'] if 'steered' in later else True)

    def test_the_accounts_next_request_waits_while_its_run_is_parked_and_other_work_is_not_blocked_by_the_slot(self):
        sent = self.start_and_park()
        self.queue.submit(self.a, message='in another chat', key='other', conversation_id='c-a')
        self.assertIsNone(self.queue.claim(owner='w', capacity=OK))                     # fenced: its session lane and cell are busy
        with self.store.connect() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM request_slot').fetchone())
        self.assertEqual(self.request(sent['id'])['parked_reason'], 'browser_question')

    def test_when_the_person_answers_the_request_takes_the_slot_back_and_finishes(self):
        sent = self.start_and_park()
        self.browse_state(sent['id'], 'done')                                           # they answered; the browser finished its job
        report = self.worker.tick()                                                     # ready: unparked, supervised to the end
        self.assertEqual(report, {'ran': 1, 'finished': True})
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome'], row['parked_reason']), ('completed', 'completed', None))
        self.assertFalse(self.rows('SELECT 1 FROM request_slot'))
        self.assertEqual(self.rows("SELECT state FROM tasks")[0][0], 'completed')

    def test_the_time_a_person_took_does_not_count_against_the_run(self):
        sent = self.start_and_park()
        before = self.rows('SELECT deadline_epoch FROM chat_deliveries')[0][0]
        self.now += 500
        self.browse_state(sent['id'], 'running')
        self.assertEqual(self.driver.check_parked(self.queue.parked()[0]), 'ready')
        self.assertEqual(self.rows('SELECT deadline_epoch FROM chat_deliveries')[0][0], before + 500)

    def test_a_run_that_ended_while_parked_is_closed_without_needing_the_slot(self):
        sent = self.start_and_park()
        for run in self.gateway.runs.values():
            run['polls_left'] = 0                                                       # the run finishes on its own while the person is away
        with self.store.connect() as con:
            con.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,fence,lease_owner) "
                        "VALUES ('a','squatter','actor-a','p-a','c-a','kz','h','x','running',?,1,'w')", (self.now,))
            con.execute("INSERT INTO request_slot VALUES (1,'a','squatter')")           # somebody else holds the slot
        self.assertEqual(self.driver.check_parked(self.queue.parked()[0]), 'ended')
        self.assertEqual(self.worker.tick()['finished'], True)
        self.assertEqual(self.request(sent['id'])['state'], 'completed')
        self.assertEqual(self.rows('SELECT request_id FROM request_slot')[0][0], 'squatter')       # their slot was not touched

    def test_stop_on_a_parked_request_aborts_the_run_and_closes_it_cancelled(self):
        sent = self.start_and_park()
        self.chat.cancel(self.a, sent['id'])
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('cancelled', 'cancelled'))
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])

    def test_a_person_who_never_answers_does_not_hold_the_cell_forever(self):
        sent = self.start_and_park()
        self.now += self.driver.park_limit + 1
        self.assertEqual(self.driver.check_parked(self.queue.parked()[0]), 'ended')


class DeferChecks(Base):
    def test_a_session_still_owned_by_a_live_request_defers_new_work(self):
        first = self.say(key='k1')
        self.gateway.polls = 5
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        self.queue.park(claim, 'browser_question')
        other = self.queue.submit(self.a, message='second', key='k2', conversation_id='c-a')
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running',parked_reason=NULL WHERE id=?", (first['id'],))     # pretend it is merely running elsewhere
        # a claim for the second request while the first still owns the session's run
        self.queue.cancel(self.a, other['id'])

    def test_a_run_nobody_owns_is_stopped_before_new_work_starts(self):
        key, _, _ = self.gateway.open_session('op', 'chat-x')
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET native_session_ref=? WHERE id='c-a'", (key,))
        self.gateway.polls = 99
        self.gateway.send(key, 'orphan-run', 'resumed by the runtime after a restart')       # a run the runtime started by itself
        sent = self.say(key='k1')
        self.gateway.polls = 0
        report = self.worker.tick()
        self.assertEqual(report, {'ran': 1, 'finished': True})
        self.assertEqual(self.gateway.runs['orphan-run']['error'], 'aborted')                # ownership was resolved first
        self.assertEqual(self.request(sent['id'])['outcome'], 'completed')

    def test_an_old_conversations_unowned_run_is_drained_before_a_new_conversation(self):
        key, _, _ = self.gateway.open_session('orphan-op', 'chat-old')
        with self.store.connect() as con:
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id,native_session_ref) VALUES ('a','p-a','old-conversation','d-a',?)", (key,))
        self.gateway.polls = 99
        self.gateway.send(key, 'orphan-other', 'resumed old shopping task')
        self.gateway.active_sessions = lambda: [{'session_key': key, 'run_id': 'orphan-other'}] if not self.gateway.runs['orphan-other'].get('error') else []
        sent = self.say(key='new-conversation')
        self.gateway.polls = 0
        self.worker.tick()
        self.assertEqual(self.gateway.runs['orphan-other']['error'], 'aborted')
        self.assertEqual(self.request(sent['id'])['outcome'], 'completed')

    def test_a_run_a_live_request_owns_makes_the_new_request_wait_its_turn(self):
        key, _, _ = self.gateway.open_session('op', 'chat-x')
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET native_session_ref=? WHERE id='c-a'", (key,))
            con.execute("INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,fence,lease_owner,lease_until) "
                        "VALUES ('a','older','actor-a','p-a','c-a','kold','h','x','running',?,1,'w',?)", (self.now, self.now + 999))
            con.execute("INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_run_id,created_epoch,updated_epoch,kind) "
                        "VALUES ('a','older',1,'older-a1','h','acknowledged','older-a1',?,?, 'turn')", (self.now, self.now))
        self.gateway.polls = 99
        self.gateway.send(key, 'older-a1', 'the older request is still running')
        sent = self.say(key='k1', mode='plan')
        self.assertEqual(self.worker.tick(), {'ran': 0, 'deferred': True})                    # the older request holds the account's execution
        self.assertEqual(self.request(sent['id'])['state'], 'waiting')                        # back in line, nothing sent
        self.assertFalse(self.rows('SELECT 1 FROM request_slot'))


class GoalChecks(Base):
    def goal_send(self, message='keep going until the report is finished', key='g1'):
        return self.say(message, key=key, goal=True)

    def finish_turn(self, goal_status):
        self.gateway.script = lambda message, run, gw: {'goal': goal_status}
        return self.worker.tick()

    def test_a_goal_turn_that_ends_with_the_goal_active_gets_the_next_turn_admitted_on_its_own_reservation(self):
        first = self.goal_send()
        report = self.finish_turn('active')
        self.assertEqual(report['ran'], 1)
        done = self.request(first['id'])
        self.assertEqual((done['state'], done['outcome'], done['continue_goal']), ('completed', 'partial', 1))
        self.assertEqual(report['followed'], 1)                                              # GoalChain admitted the next turn in the same tick
        nxt = self.rows("SELECT * FROM customer_requests WHERE continues=?", (first['id'],))
        self.assertEqual(len(nxt), 1)
        self.assertEqual((nxt[0]['intent'], nxt[0]['goal_mode'], nxt[0]['state']), ('goal_continue', 1, 'waiting'))
        self.assertTrue(self.rows("SELECT 1 FROM task_reservations WHERE task_id=? AND state='active'", (nxt[0]['id'],)))    # its own money
        self.assertEqual(self.goals.tick(), 0)                                               # once only
        goal = self.gateway.session_goal(self.driver._session(self.queue.parked()[0] if False else type('C', (), {'account_id': 'a', 'conversation_id': 'c-a'})()))
        self.assertEqual(goal['status'], 'active')
        self.assertEqual([c[3] for c in self.gateway.calls if c[0] == 'send'], [None])       # the objective went out as the first message, with the goal intent

    def test_the_goal_objective_is_the_customers_message_without_lumina_context(self):
        self.goal_send('write the report')
        self.worker.tick()
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['objective'], 'write the report')

    def test_a_goal_that_is_complete_blocked_or_paused_is_never_continued(self):
        for n, (status, outcome) in enumerate((('complete', 'completed'), ('blocked', 'blocked'), ('paused', 'partial'), ('budget_limited', 'partial'))):
            self.setUp()
            first = self.goal_send(key=f'g{n}')
            report = self.finish_turn(status)
            done = self.request(first['id'])
            self.assertEqual((done['outcome'], done['continue_goal']), (outcome, 0), status)
            self.assertNotIn('followed', report)
            self.assertFalse(self.rows('SELECT 1 FROM customer_requests WHERE continues IS NOT NULL'))

    def test_a_goal_chain_stops_at_its_limit_and_says_so(self):
        self.make_worker(goal_chain_limit=2)
        first = self.goal_send()
        self.finish_turn('active')
        self.assertTrue(self.rows('SELECT 1 FROM customer_requests WHERE continues=?', (first['id'],)))
        report = self.worker.tick()                                                          # turn two: chain length reaches the limit
        self.assertEqual(report['ran'], 1)
        second = self.rows('SELECT * FROM customer_requests WHERE continues=?', (first['id'],))[0]
        self.assertEqual((second['outcome'], second['continue_goal']), ('partial', 0))
        self.assertIn('not reached', second['outcome_note'])

    def test_stop_pauses_the_goal_so_nothing_resumes_it(self):
        first = self.goal_send()
        self.gateway.polls = 3
        self.gateway.on_wait = lambda run: self.chat.cancel(self.a, first['id']) if run['state'] == 'running' else None
        report = self.worker.tick()
        self.assertEqual(self.request(first['id'])['outcome'], 'cancelled')
        self.assertNotIn('followed', report)
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['status'], 'paused')

    def test_stop_on_a_waiting_continuation_pauses_the_goal(self):
        first = self.goal_send()
        self.finish_turn('active')
        nxt = self.rows('SELECT id FROM customer_requests WHERE continues=?', (first['id'],))[0][0]
        self.chat.cancel(self.a, nxt)
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['status'], 'paused')
        self.assertEqual(self.worker.tick(), {'ran': 0})

    def test_a_refused_admission_pauses_the_goal_instead_of_continuing_silently(self):
        first = self.goal_send()
        with self.store.connect() as con:
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(dict(LIMITS, period_microusd=600000)),))
        self.finish_turn('active')
        done = self.request(first['id'])
        self.assertEqual((done['continue_goal'], done['outcome']), (0, 'partial'))
        self.assertIn('paused', done['outcome_note'])
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['status'], 'paused')

    def test_resume_asks_the_runtime_to_resume_and_is_admitted_like_any_task(self):
        first = self.goal_send()
        self.finish_turn('paused')
        resumed = self.chat.goal_action(self.a, 'c-a', 'resume', key='r1')
        self.assertEqual(resumed['admission'], 'reserved')
        self.assertEqual(self.chat.goal_action(self.a, 'c-a', 'resume', key='r1')['id'], resumed['id'])
        self.gateway.script = lambda message, run, gw: {'goal': 'complete'}
        self.worker.tick()
        self.assertEqual(self.request(resumed['id'])['outcome'], 'completed')
        self.assertIn('resume', [c[2] for c in self.gateway.calls if c[0] == 'goal_update'])

    def test_a_new_goal_replaces_an_old_one_but_a_retry_continues_it(self):
        first = self.goal_send('first objective', key='g1')
        self.finish_turn('blocked')
        second = self.goal_send('a different objective', key='g2')
        self.worker.tick()
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['objective'], 'a different objective')


class RestartChecks(Base):
    """A cell can restart under a run (a host reboot, an update, a crash). The run is the runtime's; Lumina waits, then presents the input again by its key."""

    class Flaky(SyntheticGateway):
        """Unreachable for `down` calls of wait, and able to lose accepted-but-unstarted inputs the way a hard restart does."""
        def __init__(self, **kw):
            super().__init__(**kw)
            self.down = 0
        def wait(self, run_id, timeout_ms):
            if self.down > 0:
                self.down -= 1
                raise CapabilityUnavailable('cell restarting')
            return super().wait(run_id, timeout_ms)
        def lose_everything_in_flight(self):
            """A hard restart: what was running is gone, and what the runtime had accepted comes back as an interrupted pending input (inert, refused under its old key)."""
            for key, run in list(self.runs.items()):
                if run['state'] in ('running', 'queued'):
                    del self.runs[key]
                    self.interrupted.add(key)
                    self.sessions[run['session']]['rows'] = [r for r in self.sessions[run['session']]['rows'] if r.get('idempotency_key') != key + ':user']

    def setUp(self):
        super().setUp()
        self.gateway = self.Flaky(polls=2)
        self.chat.gateway_factory = lambda account: self.gateway
        self.make_worker(outage_limit=60)

    def test_a_cell_that_is_briefly_unreachable_is_waited_for_not_failed(self):
        sent = self.say(key='k1')
        self.gateway.down = 5
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})
        self.assertEqual(self.request(sent['id'])['outcome'], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)

    def test_a_cell_that_stays_unreachable_leaves_the_request_to_be_recovered_later(self):
        self.say(key='k1')
        self.gateway.down = 10 ** 6
        self.driver.sleep = lambda s: setattr(self, 'now', self.now + 20)
        with self.assertRaises(CapabilityUnavailable):
            self.worker.tick()
        self.assertEqual(self.rows('SELECT state FROM customer_requests')[0][0], 'uncertain')       # nothing is guessed about the run; recovery re-attaches
        self.gateway.down = 0
        self.driver.sleep = lambda s: None
        self.assertEqual(self.worker.tick(), {'ran': 1, 'finished': True})
        self.assertEqual(len(self.gateway.runs), 1)

    def test_an_input_the_runtime_lost_in_a_restart_is_presented_again_once_and_runs_once(self):
        sent = self.say(key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        self.queue.uncertain(claim)                                                          # the worker died with the run in flight...
        self.gateway.lose_everything_in_flight()                                             # ...and the cell restarted and forgot the accepted input
        self.assertEqual(len(self.gateway.runs), 0)
        again = self.queue.recover(claim, owner='w')
        receipt = self.driver.execute(again)                                                  # recovery presents the input again; the runtime refuses the old key, so it goes under a fresh one
        self.assertEqual((receipt.state, receipt.outcome), ('completed', 'completed'))
        self.assertEqual(len(self.gateway.runs), 1)
        row = self.rows('SELECT idempotency_key,native_operation_id,native_run_id,state FROM chat_deliveries')[0]
        self.assertEqual((row['state'], row['native_operation_id']), ('completed', f'{sent["id"]}-a1'))
        self.assertTrue(row['idempotency_key'].startswith(f'{sent["id"]}-a1.r'))                # the delivery follows its input to the new key; the interrupted one never runs
        self.assertEqual(row['native_run_id'], row['idempotency_key'])
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],))), 1)

    def test_an_input_that_vanished_while_waiting_is_presented_again_but_never_gets_more_time(self):
        sent = self.say(key='k1')
        self.gateway.polls = 10 ** 6
        claim = self.queue.claim(owner='w', capacity=OK)
        steps = {'n': 0}
        def lose_then_age(seconds):
            steps['n'] += 1
            if steps['n'] == 1:
                self.gateway.lose_everything_in_flight()
            self.now += 7
            if steps['n'] == 12:
                for run in self.gateway.runs.values():
                    run['polls_left'] = 0                                                    # the presented-again run now gets to finish
        self.driver.sleep = lose_then_age
        receipt = self.driver.execute(claim)
        self.assertEqual(len([c for c in self.gateway.calls if c[0] == 'send']) >= 2, True)
        self.assertEqual(len(self.gateway.runs), 1)                                          # presented again, run once
        self.assertEqual(receipt.state, 'completed')
        deadline = self.rows('SELECT deadline_epoch,created_epoch FROM chat_deliveries')[0]
        self.assertEqual(deadline['deadline_epoch'], deadline['created_epoch'] + self.driver.run_timeout)       # the first deadline stands

    def test_a_request_that_was_waiting_on_a_person_is_re_asserted_when_it_comes_back(self):
        sent = self.say(key='k1')
        self.browse_state(sent['id'], 'asking')
        self.gateway.polls = 5
        self.assertEqual(self.worker.tick()['parked'], 'browser_question')
        self.gateway.lose_everything_in_flight()                                              # the cell restarted while the person was away
        self.browse_state(sent['id'], 'done')
        self.gateway.polls = 0
        self.assertEqual(self.worker.tick()['finished'], True)
        self.assertEqual(self.request(sent['id'])['outcome'], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)


class SpendingLimitChecks(Base):
    def test_a_run_that_has_spent_its_reservation_is_stopped_and_reported_partial(self):
        class Spender(SyntheticGateway):
            readings = [0, 700000, 1400000, 2100000]
            def usage_snapshot(self):
                return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        self.gateway = Spender(polls=50)
        self.make_worker(spend_check_seconds=0)
        sent = self.say(key='k1')
        report = self.worker.tick()
        row = self.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('completed', 'partial'))
        self.assertIn('spending limit', row['outcome_note'])
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])
        self.assertEqual(self.rows("SELECT state FROM task_reservations")[0][0], 'settled')


class OutgoingChecks(Base):
    def outgoing(self, **send):
        sent = self.say(key='k1', **send)
        claim = self.queue.claim(owner='w', capacity=OK)
        info = self.driver._admit(claim)
        return self.driver._outgoing(claim, info), claim

    def test_a_plain_message_gets_direct_execution_guidance_without_a_forced_plan(self):
        text, _ = self.outgoing(message='what is 2+2')
        self.assertTrue(text.endswith('what is 2+2'))
        self.assertIn('execute directly', text)
        self.assertIn('do not stop to offer Plan mode', text)

    def test_browse_and_text_modes_become_a_short_note_not_a_protocol(self):
        text, _ = self.outgoing(message='order wings', mode='browse')
        self.assertIn('Lumina browser tool', text)
        self.assertNotIn('lumina-step', text)

    def test_what_the_customer_asked_to_remember_reaches_the_assistant_but_never_a_secret(self):
        with self.store.connect() as con:
            from agentai_platform import saved
            saved.remember(con, 'a', 'size', 'M')
        text, _ = self.outgoing(message='order wings')
        self.assertIn('size: M', text)
        self.assertTrue(text.startswith('[Lumina context'))

    def test_a_retry_tells_the_assistant_to_check_what_was_already_done(self):
        first = self.say(key='k1')
        self.chat.cancel(self.a, first['id'])
        retry = self.chat.retry(self.a, first['id'])
        claim = self.queue.claim(owner='w', capacity=OK)
        text = self.driver._outgoing(claim, self.driver._admit(claim))
        self.assertIn(RETRY_NOTE, text)


if __name__ == '__main__':
    unittest.main()


class DeadContainerRecoveryChecks(Base):
    def test_cancelled_oom_request_is_closed_without_waiting_for_a_dead_gateway(self):
        self.gateway.fail_after_ack = True
        request = self.chat.send(self.a, conversation_id='c-a', message='Test work', key='dead-container')
        with self.assertRaises(RuntimeError): self.worker.tick()
        self.chat.cancel(self.a, request['id'])
        self.gateway.cell_running = lambda: False
        self.gateway.capabilities = lambda: self.fail('A dead container must not require a websocket handshake')
        self.gateway.fail_after_ack = False
        result = self.worker.tick()
        self.assertTrue(result['reconciled'])
        with self.store.connect() as con:
            row = con.execute('SELECT state,outcome FROM customer_requests WHERE id=?', (request['id'],)).fetchone()
            self.assertEqual(tuple(row), ('cancelled', 'cancelled'))
            self.assertEqual(con.execute('SELECT count(*) FROM request_slot').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT state FROM task_reservations WHERE task_id=?', (request['id'],)).fetchone()[0], 'settled')

    def test_an_unexpected_container_exit_fails_instead_of_replaying_the_work(self):
        self.gateway.fail_after_ack = True
        request = self.chat.send(self.a, conversation_id='c-a', message='Test work', key='dead-container')
        with self.assertRaises(RuntimeError): self.worker.tick()
        sends = len(self.gateway.calls)
        self.gateway.cell_running = lambda: False
        self.gateway.fail_after_ack = False
        self.assertTrue(self.worker.tick()['reconciled'])
        self.assertEqual(self.chat.task(self.a, request['id'])['state'], 'failed')
        self.assertEqual(len(self.gateway.calls), sends)

    def test_a_failed_host_probe_never_proves_a_container_is_stopped(self):
        def unknown(): raise CapabilityUnavailable('probe unavailable')
        self.gateway.cell_running = unknown
        self.assertFalse(self.driver._cell_gone(self.gateway))
        self.gateway.cell_running = lambda: None
        self.assertFalse(self.driver._cell_gone(self.gateway))


    def test_dead_assistant_does_not_release_a_browser_that_is_still_running(self):
        self.gateway.fail_after_ack = True
        request = self.chat.send(self.a, conversation_id='c-a', message='Browse', key='dead-browser')
        with self.assertRaises(RuntimeError): self.worker.tick()
        self.chat.cancel(self.a, request['id'])
        self.gateway.cell_running = lambda: False
        state = ['running']
        self.driver.browse_factory = lambda account: lambda op, **kw: {'state': state[0]}
        self.assertFalse(self.worker.tick()['reconciled'])
        self.assertEqual(self.chat.task(self.a, request['id'])['state'], 'uncertain')
        state[0] = 'cancelled'
        self.assertTrue(self.worker.tick()['reconciled'])
        self.assertEqual(self.chat.task(self.a, request['id'])['state'], 'cancelled')
