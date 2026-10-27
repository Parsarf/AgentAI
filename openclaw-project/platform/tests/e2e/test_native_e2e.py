"""End to end against a real OpenClaw 2026.9.6 gateway per customer: what the migration must prove that unit tests with a double cannot.

Each test sends a message through ChatService, lets the production worker loop run it, and then looks at the runtime's own state (history, runs, goals) and at Lumina's
(requests, deliveries, ledger, events, artifacts). Skipped when node or the pinned OpenClaw package is not on this machine."""
import json
import threading
import time
import unittest

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.gateway import NativeGateway
from tests.e2e.harness import Stack, openclaw_package

PACKAGE = openclaw_package()
STEP = {'n': 2, 'kind': 'step', 'by': 'haiku', 'action': 'click', 'label': 'Add to cart', 'result': 'ok', 'url': 'https://ubereats.com/cart', 'changed': True}
RUNNING = {'state': 'running', 'events': [{'n': 1, 'kind': 'opened', 'url': 'https://ubereats.com/', 'title': 'U'}, STEP], 'cost_microusd': 3000, 'url': 'https://ubereats.com/cart'}
HANDOFF = {'state': 'handoff', 'reason': 'reached a payment step', 'answer': None, 'url': 'https://ubereats.com/checkout', 'takeover': True, 'cost_microusd': 6000,
           'pending_action': {'label': 'Checkout'}, 'events': [{'n': 3, 'kind': 'screenshot', 'file': 'shot-001.jpg', 'by': 'lumina'}], 'jev': {'jev_asked': 2, 'jev_agree': 1}}
DONE = {'state': 'done', 'answer': 'The wings are in the cart.', 'url': 'https://ubereats.com/cart', 'reason': '', 'cost_microusd': 4000, 'events': [], 'pending_action': None}


@unittest.skipUnless(PACKAGE, 'needs node and the pinned OpenClaw package (OPENCLAW_PACKAGE)')
class NativeEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = Stack(PACKAGE)
        try:
            cls.S.start()
        except BaseException:
            cls.S.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.S.stop()

    def setUp(self):
        self.S.browse.script, self.S.browse.calls = [DONE], []
        self.S.driver.heartbeat = self.S.queue.heartbeat

    def tearDown(self):
        # A test must leave nothing queued behind it: the queue is first come, first served, so one customer's leftover would hold up the next test.
        S = self.S
        for row in S.rows("SELECT account_id,id FROM customer_requests WHERE state IN ('waiting','starting','running','uncertain')"):
            try:
                S.chat.cancel(S.principals[row['account_id']], row['id'])
            except Exception:
                pass
        if S.rows("SELECT 1 FROM customer_requests WHERE state IN ('starting','running','uncertain')"):
            try:
                S.work(timeout=30)
            except AssertionError:
                pass

    def finished(self, request_id):
        return lambda: self.S.request(request_id)['state'] in ('completed', 'failed', 'cancelled')

    def run_to_end(self, account, message, key, **kw):
        S = self.S
        S.hold_cell(account)
        sent = S.say(account, message, key, **kw)
        S.work(until=self.finished(sent['id']))
        return sent, S.request(sent['id'])

    # -- ordinary answer, identity, charges ----------------------------------------------------------------------------------------------------
    def test_an_ordinary_answer_has_one_run_one_owner_one_charge_and_a_verdict(self):
        S = self.S
        sent, row = self.run_to_end('a', 'What is the capital of France? SCENARIO:answer', 'k-answer')
        self.assertEqual((row['state'], row['outcome'], row['verification']), ('completed', 'completed', 'not_applicable'))
        deliveries = S.rows('SELECT * FROM chat_deliveries WHERE request_id=?', (sent['id'],))
        self.assertEqual(len(deliveries), 1)
        d = deliveries[0]
        self.assertEqual((d['kind'], d['state'], d['native_status'], d['native_run_id']), ('turn', 'completed', 'ok', f'{sent["id"]}-a1'))     # the run id is derived from the request: stable identity
        messages = S.rows("SELECT provenance,content,request_id FROM chat_messages WHERE conversation_id='c-a' AND request_id=? ORDER BY id", (sent['id'],))
        self.assertEqual([m['provenance'] for m in messages], ['customer', 'agent'])
        self.assertIn('Plain answer to:', messages[1]['content'])
        receipts = S.rows("SELECT amount_microusd,price_version FROM provider_receipts WHERE task_id=?", (sent['id'],))
        self.assertEqual([r['price_version'] for r in receipts], ['litellm-reported-v1'])
        self.assertGreater(receipts[0]['amount_microusd'], 0)
        self.assertEqual(S.rows("SELECT state FROM task_reservations WHERE task_id=?", (sent['id'],))[0]['state'], 'settled')
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slot')[0]['n'], 0)
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        page = NativeGateway(BridgeRpc('a', S.socket)).history(session)
        self.assertFalse(page['active_run'])
        self.assertEqual([r['idempotency_key'] for r in page['messages'] if r['role'] == 'customer' and r['idempotency_key'].startswith(sent['id'])], [f'{sent["id"]}-a1:user'])

    def test_a_repeated_send_is_the_same_task_and_the_runtime_never_runs_it_twice(self):
        S = self.S
        S.hold_cell('a')
        first = S.say('a', 'Say hello once. SCENARIO:answer', 'k-twice')
        again = S.say('a', 'Say hello once. SCENARIO:answer', 'k-twice')
        self.assertEqual(first['id'], again['id'])
        S.work(until=self.finished(first['id']))
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        gw = NativeGateway(BridgeRpc('a', S.socket))
        before = len([r for r in gw.history(session)['messages'] if r['role'] == 'agent'])
        ack = gw.send(session, f'{first["id"]}-a1', 'Say hello once. SCENARIO:answer')          # even a deliberate resend of the same key
        self.assertEqual((ack['duplicate'], ack['status']), (True, 'ok'))
        time.sleep(1.5)
        self.assertEqual(len([r for r in gw.history(session)['messages'] if r['role'] == 'agent']), before)

    # -- the browser as a native tool --------------------------------------------------------------------------------------------------------
    def test_the_assistant_calls_the_browser_as_a_native_tool_and_the_result_comes_back_to_it(self):
        S = self.S
        S.browse.script = [RUNNING, HANDOFF]
        sent, row = self.run_to_end('a', 'Add the spiciest wings to my cart. SCENARIO:browse', 'k-browse')
        self.assertEqual(row['state'], 'completed')
        self.assertEqual((row['outcome'], row['verification']), ('partial', 'unverified'))        # the browser stopped where it needs the customer: never worded as done
        self.assertIn('needs you', row['outcome_note'])
        start = [c for c in S.browse.calls if c[0] == 'start'][0][1]
        self.assertEqual(start['request_id'], sent['id'])
        self.assertEqual(start['max_cost_microusd'], 600000)                                       # the browsing share of this request's reservation
        self.assertIn('Stop before: payment', start['goal'])
        d = S.rows('SELECT tools_json FROM chat_deliveries WHERE request_id=?', (sent['id'],))[0]
        self.assertIn('lumina__lumina_browser', json.loads(d['tools_json']))                       # the runtime's own receipt says the tool ran
        run = S.rows('SELECT * FROM browse_runs WHERE request_id=?', (sent['id'],))[0]
        self.assertEqual((run['account_id'], run['status']), ('a', 'handoff'))
        self.assertEqual([r['kind'] for r in S.rows('SELECT kind FROM browse_steps WHERE request_id=? ORDER BY n', (sent['id'],))], ['opened', 'step', 'screenshot'])
        reply = S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id DESC", (sent['id'],))[0]['content']
        self.assertIn('nothing was purchased', reply)                                              # the tool result reached the model
        events = [e['payload'] for e in S.events.events(S.principals['a'], sent['id'])['events']]
        self.assertTrue(any('Add to cart' in str(p.get('summary', '')) for p in events))
        self.assertTrue(any(p.get('tool') == 'browser' or p.get('label') == 'Used the browser' for p in events))

    def test_a_browser_job_that_finishes_is_completed_and_the_cart_page_is_checked(self):
        S = self.S
        S.browse.script = [RUNNING, DONE]
        sent, row = self.run_to_end('a', 'Add the spiciest wings to my cart. SCENARIO:browse', 'k-browse-done')
        self.assertEqual((row['outcome'], row['verification']), ('completed', 'verified'))        # a cart page and a click that added to it: evidence Lumina holds itself

    def test_a_page_the_browser_hands_over_is_answered_by_the_assistant_with_a_step_and_the_task_finishes(self):
        S = self.S
        handed = {'state': 'running', 'events': [], 'cost_microusd': 30, 'url': 'https://ubereats.com/', 'observation': {'n': 1, 'text': 'Handed to you because: the planner found this too complex.\nCurrent page: https://ubereats.com/', 'image': 'QUJD'}}
        S.browse.script = [handed, DONE]
        sent, row = self.run_to_end('a', 'Add the spiciest wings to my cart. SCENARIO:browse', 'k-handover')
        self.assertEqual((row['state'], row['outcome']), ('completed', 'completed'))
        step = [c for c in S.browse.calls if c[0] == 'agent_step']
        self.assertEqual([(c[1]['request_id'], c[1]['step']) for c in step], [(sent['id'], {'action': 'done', 'answer': 'The wings are in the cart.'})])      # a real tool call from the runtime, through the relay
        d = S.rows('SELECT tools_json FROM chat_deliveries WHERE request_id=?', (sent['id'],))[0]
        self.assertIn('lumina__lumina_browser_step', json.loads(d['tools_json']))
        reply = S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id DESC", (sent['id'],))[0]['content']
        self.assertIn('wings are in the cart', reply)
        self.assertIn(sent['id'], [c[1]['request_id'] for c in S.browse.calls if c[0] == 'agent_release'])         # when the run ended, a job still waiting for a step would be let go

    def test_the_runtimes_own_browser_and_ask_user_are_not_offered_to_a_cell(self):
        S = self.S
        S.hold_cell('a')
        for scenario, key in (('SCENARIO:nativebrowser', 'k-nb'), ('SCENARIO:ask', 'k-ask')):
            sent = S.say('a', 'Try it. ' + scenario, key)
            S.work(until=self.finished(sent['id']))
            reply = S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id DESC", (sent['id'],))[0]['content']
            self.assertTrue('TOOL-RESULT' in reply and ('not found' in reply.lower() or 'unknown' in reply.lower() or 'no tool' in reply.lower() or 'denied' in reply.lower() or 'not available' in reply.lower()), reply)
            self.assertFalse(S.rows('SELECT 1 FROM chat_deliveries WHERE request_id=? AND tools_json LIKE ?', (sent['id'], '%ask_user%')))

    # -- files ---------------------------------------------------------------------------------------------------------------------------------
    def test_a_file_the_assistant_writes_is_delivered_as_a_download_for_this_task(self):
        S = self.S
        sent, row = self.run_to_end('a', 'Write the report to a file. SCENARIO:file', 'k-file')
        self.assertEqual(row['outcome'], 'completed')
        self.assertEqual(row['verification'], 'verified')                                          # a saved file is evidence Lumina holds
        listed = {a['display_name']: a for a in S.artifacts.list_artifacts(S.principals['a'], 'p-a')}
        self.assertIn('notes_report.txt', listed)
        self.assertTrue(any(e['kind'] == 'artifact' for e in S.events.events(S.principals['a'], sent['id'])['events']))
        self.assertEqual(S.rows("SELECT task_id FROM artifacts WHERE display_name='notes_report.txt'")[0]['task_id'], sent['id'])

    # -- plan mode and phases ------------------------------------------------------------------------------------------------------------------
    def test_plan_mode_drafts_a_plan_and_each_approved_phase_runs_as_its_own_native_run(self):
        S = self.S
        S.hold_cell('a')
        drafted = S.say('a', 'Plan a small online shop', 'k-plan', mode='plan')
        S.work(until=self.finished(drafted['id']))
        block = [b for b in S.chat.blocks.list(S.principals['a'], 'c-a') if b['kind'] == 'task_plan'][-1]
        self.assertEqual(block['status'], 'draft')
        out = S.chat.launch_plan(S.principals['a'], block['id'], block['version'])
        S.work(until=lambda: all(r['state'] == 'completed' for r in S.rows('SELECT state FROM plan_phase_runs WHERE block_id=?', (block['id'],))) and
              len(S.rows('SELECT 1 FROM plan_phase_runs WHERE block_id=?', (block['id'],))) == 2, timeout=150)
        phases = S.rows('SELECT phase_id,state,request_id FROM plan_phase_runs WHERE block_id=? ORDER BY position', (block['id'],))
        self.assertEqual([p['state'] for p in phases], ['completed', 'completed'])
        self.assertEqual(len({p['request_id'] for p in phases}), 2)                                # a request, a reservation and a run per phase
        for p in phases:
            self.assertEqual(S.rows('SELECT count(*) AS n FROM chat_deliveries WHERE request_id=?', (p['request_id'],))[0]['n'], 1)

    # -- steering, stop, interruption -----------------------------------------------------------------------------------------------------------
    def test_a_message_sent_while_the_task_runs_is_steered_into_that_run(self):
        S = self.S
        S.hold_cell('a')
        sent = S.say('a', 'Take your time. SCENARIO:slow', 'k-slow')
        thread, out = S.in_background(self.finished(sent['id']))
        S.wait_for(lambda: S.rows("SELECT 1 FROM chat_deliveries WHERE request_id=? AND state='acknowledged'", (sent['id'],)), message='the run to start')
        steered = S.say('a', 'Also mention the weather.', 'k-steer')
        self.assertTrue(steered['steered'])
        self.assertEqual(steered['id'], sent['id'])
        thread.join(90)
        row = S.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('completed', 'completed'))
        deliveries = S.rows('SELECT kind,state,native_status FROM chat_deliveries WHERE request_id=? ORDER BY attempt', (sent['id'],))
        self.assertEqual([(d['kind'], d['state']) for d in deliveries], [('turn', 'completed'), ('steer', 'completed')])
        self.assertEqual(len(S.rows('SELECT 1 FROM customer_requests WHERE conversation_id="c-a" AND message LIKE "Also mention%"')), 0)       # no second task
        agent = [m['content'] for m in S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id", (sent['id'],))]
        self.assertTrue(any('weather' in a for a in agent), agent)                                  # the steered input was answered inside the run
        self.assertEqual(len(S.rows("SELECT 1 FROM task_reservations WHERE task_id=?", (sent['id'],))), 1)

    def test_stop_aborts_the_run_waits_for_the_runtime_and_nothing_arrives_afterwards(self):
        S = self.S
        S.hold_cell('a')
        sent = S.say('a', 'Take a long time. SCENARIO:slow', 'k-stop')
        thread, out = S.in_background(self.finished(sent['id']))
        S.wait_for(lambda: S.rows("SELECT 1 FROM chat_deliveries WHERE request_id=? AND state='acknowledged'", (sent['id'],)), message='the run to start')
        S.chat.cancel(S.principals['a'], sent['id'])
        thread.join(60)
        row = S.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('cancelled', 'cancelled'))
        self.assertEqual(S.rows('SELECT state,native_status FROM chat_deliveries WHERE request_id=?', (sent['id'],))[0]['native_status'], 'aborted')
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        self.assertEqual(NativeGateway(BridgeRpc('a', S.socket)).wait(f'{sent["id"]}-a1', 0)['aborted'], True)
        time.sleep(7)                                                                              # longer than the model's delay: a run that was not really stopped would reply now
        self.assertFalse(S.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],)))
        self.assertFalse(NativeGateway(BridgeRpc('a', S.socket)).history(session)['active_run'])
        self.assertEqual(S.rows("SELECT state FROM task_reservations WHERE task_id=?", (sent['id'],))[0]['state'], 'settled')

    def test_a_worker_that_dies_mid_run_is_recovered_onto_the_same_run_without_a_second_one(self):
        S = self.S
        S.hold_cell('a')
        sent = S.say('a', 'Take your time. SCENARIO:slow', 'k-crash')
        beats = {'n': 0}
        def dying(claim):
            beats['n'] += 1
            if beats['n'] == 3:
                raise RuntimeError('worker died')
            return S.queue.heartbeat(claim)
        S.driver.heartbeat = dying
        with self.assertRaises(RuntimeError):
            S.work(until=self.finished(sent['id']))
        self.assertEqual(S.request(sent['id'])['state'], 'uncertain')
        S.driver.heartbeat = S.queue.heartbeat
        S.work(until=self.finished(sent['id']))                                                    # a fresh worker settles it from the runtime's own state
        row = S.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('completed', 'completed'))
        self.assertEqual(len(S.rows('SELECT 1 FROM chat_deliveries WHERE request_id=?', (sent['id'],))), 1)
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        page = NativeGateway(BridgeRpc('a', S.socket)).history(session)
        self.assertEqual(len([r for r in page['messages'] if r['idempotency_key'] == f'{sent["id"]}-a1:user']), 1)       # sent once
        self.assertEqual(len(S.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],))), 1)
        self.assertEqual(len(S.rows("SELECT 1 FROM provider_receipts WHERE task_id=?", (sent['id'],))), 1)                # charged once

    def test_a_cell_that_is_killed_mid_run_and_restarted_finishes_the_request_with_one_run_and_one_charge(self):
        S = self.S
        S.hold_cell('a')
        sent = S.say('a', 'Take your time. SCENARIO:slow', 'k-restart')
        thread, out = S.in_background(self.finished(sent['id']), timeout=150, survive=True)
        S.wait_for(lambda: S.rows("SELECT 1 FROM chat_deliveries WHERE request_id=? AND state='acknowledged'", (sent['id'],)), message='the run to start')
        cell = S.cells['a']
        cell.kill()                                                                                  # no drain, no goodbye
        time.sleep(3)
        self.assertNotEqual(S.request(sent['id'])['state'], 'completed')                             # the supervisor waits for the cell; it does not invent an end
        cell.start(); cell.wait_ready()
        S.bridge.close_all()                                                                         # the host's relay to the dead cell is gone with it
        thread.join(140)
        row = S.request(sent['id'])
        self.assertEqual((row['state'], row['outcome']), ('completed', 'completed'), S.errors)
        self.assertEqual(len(S.rows('SELECT 1 FROM chat_deliveries WHERE request_id=?', (sent['id'],))), 1)
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        page = NativeGateway(BridgeRpc('a', S.socket)).history(session)
        mine = [r for r in page['messages'] if r['role'] == 'customer' and (r['idempotency_key'] or '').startswith(f'{sent["id"]}-a1')]
        self.assertEqual(len(mine), 1)                                                              # the runtime ran the input once: the restart left the original inert and it went again under a fresh key
        # Depending on when the kill lands, the runtime resumes the turn itself (original key) or the input was inert and went again under a fresh key (.r<epoch>): both are one run.
        delivery = S.rows('SELECT idempotency_key,native_operation_id,native_run_id,state FROM chat_deliveries WHERE request_id=?', (sent['id'],))[0]
        self.assertEqual((delivery['state'], delivery['native_operation_id'], delivery['native_run_id'] == delivery['idempotency_key']), ('completed', f'{sent["id"]}-a1', True))
        self.assertTrue(delivery['idempotency_key'].startswith(f'{sent["id"]}-a1'))
        self.assertEqual(len(S.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],))), 1)
        self.assertEqual(len(S.rows("SELECT 1 FROM provider_receipts WHERE task_id=?", (sent['id'],))), 1)                # charged once
        self.assertEqual(S.rows("SELECT state FROM task_reservations WHERE task_id=?", (sent['id'],))[0]['state'], 'settled')

    # -- people ----------------------------------------------------------------------------------------------------------------------------------
    def test_a_browser_question_parks_the_request_without_the_slot_and_the_run_carries_on_when_answered(self):
        S = self.S
        S.hold_cell('a')
        asking = {'state': 'asking', 'events': [], 'cost_microusd': 0, 'url': 'https://ubereats.com/', 'question': {'id': 'q1', 'title': 'Which size?'}}
        S.browse.script = [asking]
        sent = S.say('a', 'Add the spiciest wings to my cart. SCENARIO:browse', 'k-park')
        S.work(until=lambda: S.request(sent['id'])['parked_reason'])
        row = S.request(sent['id'])
        self.assertEqual((row['state'], row['parked_reason']), ('running', 'browser_question'))
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slot')[0]['n'], 0)             # one person's slow answer does not hold the slot
        self.assertEqual(S.rows('SELECT state FROM tasks WHERE id=?', (sent['id'],))[0]['state'], 'waiting_for_approval')
        time.sleep(1.5)
        self.assertEqual(S.request(sent['id'])['parked_reason'], 'browser_question')              # still waiting for them
        S.browse.script = [DONE]                                                                   # they answered; the browser finishes
        S.work(until=self.finished(sent['id']))
        done = S.request(sent['id'])
        self.assertEqual((done['state'], done['outcome'], done['parked_reason']), ('completed', 'completed', None))
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slot')[0]['n'], 0)
        self.assertEqual(len(S.rows('SELECT 1 FROM chat_deliveries WHERE request_id=?', (sent['id'],))), 1)         # the same single run all along

    # -- goals ----------------------------------------------------------------------------------------------------------------------------------
    def test_keep_working_until_complete_is_a_chain_of_admitted_turns_on_the_runtimes_own_goal(self):
        S = self.S
        S.hold_cell('a')
        conv = S.new_conversation('a')
        first = S.say('a', 'Write the quarterly report. SCENARIO:goal', 'k-goal', conversation=conv, goal=True)
        S.work(until=lambda: S.rows('SELECT 1 FROM customer_requests WHERE continues=? AND state="completed"', (first['id'],)), timeout=150)
        one = S.request(first['id'])
        self.assertEqual((one['state'], one['outcome'], one['goal_mode']), ('completed', 'partial', 1))
        self.assertEqual(one['continue_goal'], 1)
        two = S.rows('SELECT * FROM customer_requests WHERE continues=?', (first['id'],))[0]
        self.assertEqual((two['intent'], two['outcome']), ('goal_continue', 'completed'))          # the model completed the goal natively
        self.assertEqual(two['verification'], 'unverified')                                         # its own claim: nothing Lumina can check confirms it
        session = S.rows("SELECT native_session_ref FROM conversations WHERE id=?", (conv,))[0]['native_session_ref']
        goal = NativeGateway(BridgeRpc('a', S.socket)).session_goal(session)
        self.assertEqual((goal['status'], goal['objective']), ('complete', 'Write the quarterly report. SCENARIO:goal'))
        for r in (first['id'], two['id']):
            self.assertEqual(S.rows('SELECT state FROM task_reservations WHERE task_id=?', (r,))[0]['state'], 'settled')   # each turn paid for itself
        self.assertEqual(S.rows('SELECT count(*) AS n FROM customer_requests WHERE continues IS NOT NULL AND continues=?', (two['id'],))[0]['n'], 0)     # complete: no third turn
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slot')[0]['n'], 0)

    # -- isolation ------------------------------------------------------------------------------------------------------------------------------
    def test_two_customers_never_see_each_others_runs_sessions_files_charges_or_browser(self):
        S = self.S
        sent_a, row_a = self.run_to_end('a', 'Say something. SCENARIO:answer', 'k-iso-a')
        sent_b, row_b = self.run_to_end('b', 'Say something else. SCENARIO:answer', 'k-iso-b')
        sess_a = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        sess_b = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-b'")[0]['native_session_ref']
        self.assertNotEqual(sess_a, sess_b)
        gw_b = NativeGateway(BridgeRpc('b', S.socket))
        self.assertEqual(gw_b.history(sess_a)['messages'], [])                                      # b's cell is a different runtime: it holds nothing of a's session
        self.assertEqual(gw_b.wait(f'{sent_a["id"]}-a1', 0)['status'], 'running')                  # and does not know a's run (an unknown run id reads as not over)
        self.assertIn(f'{sent_a["id"]}-a1:user', [r['idempotency_key'] for r in NativeGateway(BridgeRpc('a', S.socket)).history(sess_a)['messages']])       # while a's own cell has it
        for table, column in (('chat_deliveries', 'request_id'), ('provider_receipts', 'task_id')):
            self.assertEqual({r['account_id'] for r in S.rows(f'SELECT account_id FROM {table} WHERE {column} IN (?,?)', (sent_a['id'], sent_b['id']))}, {'a', 'b'})
            self.assertEqual(S.rows(f'SELECT account_id FROM {table} WHERE {column}=?', (sent_a['id'],))[0]['account_id'], 'a')
        spend_a, spend_b = S.model.calls(S.cells['a'].key), S.model.calls(S.cells['b'].key)
        self.assertGreater(spend_a, 0); self.assertGreater(spend_b, 0)
        # the browser door: b's credential only ever serves b's own running request (it has none), whatever a is doing
        S.hold_cell('a')
        S.browse.script = [RUNNING, HANDOFF]
        before = len(S.browse.calls)
        text, error = self._call_tool_as('b')
        self.assertTrue(error)
        self.assertIn('no running task', text)
        self.assertEqual(len(S.browse.calls), before)

    def _call_tool_as(self, account):
        import urllib.request
        S = self.S
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'lumina_browser', 'arguments': {'task': 'Add wings to the cart on Uber Eats', 'site': 'ubereats.com'}}}).encode()
        request = urllib.request.Request(f'http://127.0.0.1:{S.relay_port}/mcp', data=body, headers={'Authorization': 'Bearer ' + S.cells[account].key, 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read())['result']
        return result['content'][0]['text'], result['isError']

    def test_a_credential_that_belongs_to_no_cell_cannot_use_the_browser_door(self):
        import urllib.error, urllib.request
        request = urllib.request.Request(f'http://127.0.0.1:{self.S.relay_port}/mcp', data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                                         headers={'Authorization': 'Bearer sk-not-a-cell-key', 'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 401)

    def test_the_cell_config_lumina_provisions_is_accepted_by_the_runtime_and_enforced(self):
        S = self.S
        config = S.cells['a'].config
        self.assertEqual(sorted(config['tools']['deny']), ['ask_user', 'browser'])
        self.assertEqual(config['agents']['defaults']['timeoutSeconds'], 1200)
        self.assertEqual(config['mcp']['servers']['lumina']['headers']['Authorization'], 'Bearer ' + S.cells['a'].key)
        self.assertIsNone(S.cells['a'].proc.poll())                                                 # the gateway started with exactly this config


if __name__ == '__main__':
    unittest.main()
