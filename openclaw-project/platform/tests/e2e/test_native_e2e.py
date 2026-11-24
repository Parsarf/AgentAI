"""End to end against a real OpenClaw 2026.9.6 gateway per customer: what the migration must prove that unit tests with a double cannot.

Each test sends a message through ChatService, lets the production worker loop run it, and then looks at the runtime's own state (history, runs, goals) and at Lumina's
(requests, deliveries, ledger, events, artifacts). Skipped when node or the pinned OpenClaw package is not on this machine."""
import json
import threading
import time
import unittest

from agentai_platform.goals import GoalChain
from agentai_platform.request_worker import RequestWorker

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.gateway import NativeGateway
from tests.e2e.harness import Stack, openclaw_package, CAPACITY

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
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)
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
        payload = S.rows('SELECT payload FROM chat_deliveries WHERE request_id=? AND attempt=1', (first['id'],))[0]['payload']
        ack = gw.send(session, f'{first["id"]}-a1', payload)          # even a deliberate resend of the same key
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

    def test_parallel_streamed_progress_and_browser_use_runtime_proofs(self):
        S = self.S
        # Fresh sessions and repeated turns exercise both cold and warm MCP
        # catalogs. The stub deliberately supplies a forged transport nonce.
        for i in range(3):
            S.browse.calls = []
            S.hold_cell('a')
            sent = S.say('a', 'Inspect the shop. SCENARIO:ownership_parallel', 'parallel-' + str(i), conversation=S.new_conversation('a'))
            S.work(until=self.finished(sent['id']))
            self.assertEqual(len([c for c in S.browse.calls if c[0] == 'start']), 1)
            progress = S.rows("SELECT public_payload FROM events WHERE task_id=? AND kind='task_steps'", (sent['id'],))
            self.assertEqual(len(progress), 1)
            self.assertEqual(json.loads(progress[0]['public_payload'])['revision'], 1)
            directory = S.cells['a'].root / 'state/tool-origins'
            self.assertEqual([p for p in directory.glob('*.json') if p.name != 'protocol.json'], [])

    def test_an_old_session_cannot_borrow_a_new_tasks_browser_budget(self):
        S = self.S
        old, _ = self.run_to_end('a', 'Original task. SCENARIO:answer', 'origin-old')
        old_session = S.rows("SELECT native_session_ref FROM conversations WHERE id='c-a'")[0]['native_session_ref']
        S.browse.calls = []
        newer = S.say('a', 'New UI task. SCENARIO:answer', 'origin-new', conversation=S.new_conversation('a'))
        claim = S.queue.claim(owner='origin-test', capacity=CAPACITY)
        self.assertEqual(claim.request_id, newer['id'])
        gateway = NativeGateway(BridgeRpc('a', S.socket))
        run = gateway.send(old_session, 'unowned-old-resume', 'Resume old shopping task. SCENARIO:browse')
        S.wait_for(lambda: gateway.wait(run['run_id'], 0)['status'] != 'running', message='old run rejected')
        self.assertEqual(S.browse.calls, [])
        self.assertEqual(S.rows('SELECT * FROM browse_runs WHERE request_id=?', (newer['id'],)), [])
        page = gateway.history(old_session)
        self.assertIn('does not belong to an admitted live task', page['messages'][-1]['content'])
        S.queue.cancel(S.principals['a'], newer['id'])
        S.worker._run(claim)

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
        self.assertIn('notes/report.txt', listed)                                                  # the folder it was written in is kept
        self.assertTrue(any(e['kind'] == 'artifact' for e in S.events.events(S.principals['a'], sent['id'])['events']))
        self.assertEqual(S.rows("SELECT task_id FROM artifacts WHERE display_name='notes/report.txt'")[0]['task_id'], sent['id'])

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
    # -- what the customer sees while it works -------------------------------------------------------------------------------------------------
    def test_tool_use_reaches_the_timeline_as_it_happens_and_the_reply_can_be_read_while_it_is_written(self):
        """The runtime tells the relay when a tool call starts and ends, which ends the driver's wait slice early: the call is in Lumina's own (redacted) timeline long before
        the slice would have ended. The reply being written is readable as a draft, a piece at a time, and is the saved message in the end."""
        S = self.S
        S.driver.wait_ms = 6000                                    # a long slice: without the early wake the tool call could not be recorded before the reply
        self.addCleanup(setattr, S.driver, 'wait_ms', 1500)
        S.hold_cell('a')
        sent = S.say('a', 'Do it. SCENARIO:work_then_write', 'k-live-1')
        drafts, stop = [], threading.Event()

        def watch():
            seq = BridgeRpc('a', S.socket)('chat.draft', {'after': 0, 'waitMs': 0}).get('seq', 0)
            while not stop.is_set():
                got = BridgeRpc('a', S.socket)('chat.draft', {'after': seq, 'waitMs': 250})
                if got.get('seq', 0) > seq:
                    seq = got['seq']
                    if got.get('runId') == sent['id'] + '-a1':
                        drafts.append((got['text'], got['done'], bool(S.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],)))))
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        S.work(until=self.finished(sent['id']))
        stop.set(); watcher.join(5)
        self.assertEqual(S.request(sent['id'])['state'], 'completed')
        events = S.rows("SELECT kind,public_payload,created_at FROM events WHERE task_id=? ORDER BY sequence", (sent['id'],))
        stamp = lambda e: time.mktime(time.strptime(e['created_at'][:19], '%Y-%m-%dT%H:%M:%S')) + int(e['created_at'][20:23]) / 1000
        tool = next(e for e in events if e['kind'] == 'activity')
        result = next(e for e in events if e['kind'] == 'result')
        self.assertGreater(stamp(result) - stamp(tool), 1.5)        # recorded while the run was still going (the scripted model waits 2.5 s after the tool before it writes)
        texts = [text for text, _, _ in drafts]
        self.assertGreaterEqual(len(set(texts)), 2)                 # it grew
        self.assertTrue(all(b.startswith(a) for a, b in zip(texts, texts[1:])))
        self.assertTrue(any(not saved for _, _, saved in drafts))   # read before the message was saved
        self.assertTrue(drafts[-1][1])                              # and marked finished
        message = S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id DESC LIMIT 1", (sent['id'],))[0]['content']
        self.assertEqual(texts[-1], message)

    def test_the_push_gateway_streams_a_real_run_state_tool_rows_and_the_reply_as_it_is_written(self):
        """What an open tab receives, end to end: Lumina's push gateway reading the real database while the real runtime runs, with reply drafts read from the real relay."""
        from agentai_platform.live.push import PushGateway
        from agentai_platform.lifecycle.cell_bridge import BRIDGE_ERROR
        S = self.S
        S.hold_cell('a')
        sent = S.say('a', 'Do it. SCENARIO:work_then_write', 'k-push-1')

        def draft(account, after, wait_ms):
            got = BridgeRpc(account, S.socket)('chat.draft', {'after': after, 'waitMs': wait_ms})
            return None if BRIDGE_ERROR in got else got
        gateway = PushGateway(S.store, b's' * 40, draft=draft, window=40, tick=0.1)
        frames, done = [], threading.Event()

        def listen():
            for raw in gateway.stream(S.principals['a'], focus=sent['id']):
                for block in raw.decode().split('\n\n'):
                    lines = [l for l in block.split('\n') if l and not l.startswith(':')]
                    if lines:
                        frames.append((lines[0].removeprefix('event: '), json.loads(lines[1].removeprefix('data: ')), time.time()))
                if done.is_set() and frames and frames[-1][0] == 'task' and frames[-1][1]['task']['phase'] == 'ended':
                    return
        listener = threading.Thread(target=listen, daemon=True)
        listener.start()
        S.work(until=self.finished(sent['id']))
        done.set(); listener.join(8)
        tasks = [d for kind, d, _ in frames if kind == 'task']
        phases = [t['task']['phase'] for t in tasks]
        self.assertIn('working', phases)
        self.assertEqual(phases[-1], 'ended')
        self.assertEqual((tasks[-1]['task']['outcome'], tasks[-1]['task']['verification']), ('completed', 'verified'))      # a file it was asked to make exists: Lumina's own evidence
        rows = {}
        for t in tasks:
            for row in t['rows']:
                rows[row['key']] = row
        tool = next(r for r in rows.values() if r['kind'] == 'tool')
        self.assertEqual((tool['category'], tool['detail'], tool['status']), ('file', 'notes/plan.txt', 'done'))
        self.assertTrue(any(r['kind'] == 'tool' for t in tasks if t['task']['phase'] == 'working' for r in t['rows']) or tasks[0]['task']['phase'] != 'ended')   # the tool row arrived while the run was going
        drafts = [d for kind, d, _ in frames if kind == 'draft']
        text = ''
        for d in drafts:
            self.assertEqual(d['task'], sent['id'])
            text = d['add'] if d['at'] == 0 else text + d['add']
        message = S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id DESC LIMIT 1", (sent['id'],))[0]['content']
        self.assertGreaterEqual(len(drafts), 2)
        self.assertEqual(text, message)                              # the pieces add up to exactly the saved reply
        self.assertTrue(drafts[-1]['done'])
        self.assertNotIn('draft', [kind for kind, d, _ in frames if kind == 'draft' and d['task'] != sent['id']])

    def test_a_permission_decision_reaches_a_run_that_is_going_and_starts_a_turn_when_it_is_not(self):
        """The customer answers a permission prompt; Lumina tells the assistant by itself. On the real runtime: steered into the live run, or a follow-on turn afterwards.
        Either way the chat records a decision (provenance system), never a message in the customer's name."""
        S = self.S
        S.hold_cell('a')
        conversation = S.new_conversation('a')
        sent = S.say('a', 'Take your time. SCENARIO:slow', 'k-decide-1', conversation=conversation)
        thread, out = S.in_background(self.finished(sent['id']))
        S.wait_for(lambda: S.rows("SELECT 1 FROM chat_deliveries WHERE request_id=? AND state='acknowledged'", (sent['id'],)), message='the run to start')
        steered = S.chat.continue_after_decision(S.principals['a'], sent['id'], approved=True, tool='create_issue', service='Linear', key='approval-e2e-1')
        self.assertTrue(steered.get('steered'))
        thread.join(90)
        self.assertEqual(S.request(sent['id'])['state'], 'completed')
        kinds = [d['kind'] for d in S.rows('SELECT kind FROM chat_deliveries WHERE request_id=? ORDER BY attempt', (sent['id'],))]
        self.assertEqual(kinds, ['turn', 'steer'])
        self.assertEqual({d['state'] for d in S.rows('SELECT state FROM chat_deliveries WHERE request_id=?', (sent['id'],))}, {'completed'})
        record = S.rows("SELECT provenance,content FROM chat_messages WHERE conversation_id=? AND content LIKE 'You allowed%'", (conversation,))
        self.assertEqual([(r['provenance'], r['content']) for r in record], [('system', 'You allowed create issue on Linear.')])
        # afterwards: the same decision route starts a turn of its own, named after the task it continues
        S.hold_cell('a')
        later = S.chat.continue_after_decision(S.principals['a'], sent['id'], approved=False, tool='create_issue', service='Linear', key='approval-e2e-2')
        self.assertNotEqual(later['id'], sent['id'])
        S.work(until=self.finished(later['id']))
        self.assertEqual(S.request(later['id'])['state'], 'completed')
        from agentai_platform.work import WorkReader
        view = WorkReader(S.store).detail(S.principals['a'], later['id'])['task']
        self.assertEqual((view['title'], view['follows']), ('Take your time. SCENARIO:slow', sent['id']))
        self.assertFalse(S.rows("SELECT 1 FROM chat_messages WHERE conversation_id=? AND provenance='customer' AND content LIKE '%declined%'", (conversation,)))

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
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)             # one person's slow answer does not hold the slot
        self.assertEqual(S.rows('SELECT state FROM tasks WHERE id=?', (sent['id'],))[0]['state'], 'waiting_for_approval')
        time.sleep(1.5)
        self.assertEqual(S.request(sent['id'])['parked_reason'], 'browser_question')              # still waiting for them
        S.browse.script = [DONE]                                                                   # they answered; the browser finishes
        S.work(until=self.finished(sent['id']))
        done = S.request(sent['id'])
        self.assertEqual((done['state'], done['outcome'], done['parked_reason']), ('completed', 'completed', None))
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)
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
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)

    # -- a reply cut off at the model's output limit (roadmap #2) --------------------------------------------------------------------------------
    def test_a_reply_cut_off_at_the_output_limit_is_carried_on_in_the_same_task(self):
        S = self.S
        sent, row = self.run_to_end('a', 'Write the long report. SCENARIO:cutoff', 'k-cutoff')
        self.assertEqual((row['state'], row['outcome']), ('completed', 'completed'))
        deliveries = S.rows('SELECT attempt,kind,state,native_status FROM chat_deliveries WHERE request_id=? ORDER BY attempt', (sent['id'],))
        self.assertEqual([(d['kind'], d['state']) for d in deliveries], [('turn', 'completed'), ('turn', 'completed')])        # the second input is the automatic continuation
        texts = [m['content'] for m in S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent' ORDER BY id", (sent['id'],))]
        self.assertTrue(any('Part one' in t for t in texts) and any('Part two' in t for t in texts))
        notes = [e for e in S.rows("SELECT public_payload FROM events WHERE task_id=? AND kind='progress'", (sent['id'],)) if 'length limit' in (e['public_payload'] or '')]
        self.assertTrue(notes)                                                                                             # the customer's timeline says so
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)

    # -- parallel phases of one plan (roadmap #10) ----------------------------------------------------------------------------------------------------
    def test_two_independent_phases_run_at_the_same_time_in_two_sessions_of_one_cell_and_every_cent_is_charged_once(self):
        S = self.S
        S.hold_cell('a')
        def ph(i, deps=()):
            return {'id': i, 'title': i.upper(), 'description': 'SCENARIO:slow ' + i, 'enabled': True, 'optional': False, 'requiresApproval': False, 'dependsOn': list(deps)}
        diamond = {'schemaVersion': '1.0', 'type': 'task_plan', 'title': 'Parallel', 'phases': [ph('a'), ph('b'), {**ph('c', ('a', 'b')), 'description': 'join the results'}]}
        S.model.max_inflight = 0                                                       # counted from here: only this test's phases
        block = S.chat.blocks.create_plan('a', 'c-a', diamond, key='par-1')
        S.chat.launch_plan(S.principals['a'], block['id'], 1)
        S.worker = RequestWorker(S.queue, S.driver, lambda: CAPACITY, goals=GoalChain(S.chat), runner=lambda: S.chat.runner, max_parallel=4)
        done = lambda: S.rows("SELECT state FROM plan_phase_runs WHERE block_id=? AND phase_id='c'", (block['id'],))[0]['state'] == 'completed'
        S.work(until=lambda: done() and not S.worker._active, timeout=150)
        S.worker.wait_idle(30)
        self.assertEqual({r['phase_id']: r['state'] for r in S.rows('SELECT phase_id,state FROM plan_phase_runs WHERE block_id=?', (block['id'],))}, {'a': 'completed', 'b': 'completed', 'c': 'completed'})
        self.assertGreaterEqual(S.model.max_inflight, 2)                           # the model was asked by both phases at the same moment: one cell, two runs
        runs = S.rows("SELECT request_id,conversation_id FROM plan_phase_runs WHERE block_id=? AND phase_id IN ('a','b') ORDER BY phase_id", (block['id'],))
        self.assertEqual(len({r['conversation_id'] for r in runs}), 2)             # two conversations, therefore two native sessions
        sessions = {r['native_session_ref'] for r in S.rows('SELECT native_session_ref FROM conversations WHERE account_id=?', ('a',)) if r['native_session_ref']}
        self.assertGreaterEqual(len(sessions), 2)
        ids = [r['request_id'] for r in S.rows('SELECT request_id FROM plan_phase_runs WHERE block_id=?', (block['id'],))]
        receipts = {r['task_id']: r['amount_microusd'] for r in S.rows('SELECT task_id,amount_microusd FROM provider_receipts') if r['task_id'] in ids}
        marks = S.rows("SELECT request_id,kind,spend_microusd FROM spend_marks WHERE account_id='a' AND request_id IN (%s) ORDER BY id" % ','.join('?' * len(ids)), tuple(ids))
        stretch = max(m['spend_microusd'] for m in marks) - min(m['spend_microusd'] for m in marks)       # what the key spent from the first phase's start to the last phase's end
        self.assertLessEqual(abs(sum(receipts.values()) - stretch), 3000)               # every cent the key spent in that stretch is charged to some phase, once (rounding aside)
        self.assertTrue(all(v >= 0 for v in receipts.values()))
        self.assertEqual(S.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)
        self.assertEqual(S.worker._errors, [])

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
        self.assertIn('does not belong to an admitted live task', text)
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

    def test_a_tool_called_by_its_plain_name_with_the_arguments_assistants_guess_still_runs(self):
        """Production, 2026-11-22: every browser task began with a refused call. The assistant had not read the tool's schema (the runtime keeps schemas out of the prompt), so it
        sent `url` where the tool says `site`; and tools called by their plain name ("web_fetch") were answered "Tool web_fetch not found". Both now work."""
        S = self.S
        S.browse.script = [RUNNING, DONE]
        sent, row = self.run_to_end('a', 'Add the spiciest wings to my cart. SCENARIO:plainname', 'k-plainname')
        self.assertEqual(row['state'], 'completed')
        starts = [c[1] for c in S.browse.calls if c[0] == 'start' and c[1]['request_id'] == sent['id']]
        self.assertEqual(len(starts), 1)                                                            # the first call was taken: no refusal, no second try
        self.assertIn('Start at: https://ubereats.com/', starts[0]['goal']); self.assertIn('Done when: The wings are in the cart.', starts[0]['goal'])
        d = S.rows('SELECT tools_json FROM chat_deliveries WHERE request_id=?', (sent['id'],))[0]
        self.assertIn('lumina__lumina_browser', json.loads(d['tools_json']))
        events = [e['payload'] for e in S.events.events(S.principals['a'], sent['id'])['events']]
        self.assertFalse([p for p in events if 'not found' in str(p.get('output', '')) or 'could not be read' in str(p.get('output', ''))])

    def test_a_tool_call_lumina_refuses_shows_its_reason_on_the_step_whichever_way_it_was_called(self):
        """Reliability plan, Part 3. The tool relay records why a call did not do what was asked, under the runtime's own id for the call; the driver finds it by that id when
        it shows the step. That only holds if the id the cell's hook proves a call with is the id the runtime's history gives the same call, for both ways a tool is reached
        (its plain name, and the `tool_call` wrapper). Proven here on the real runtime. The step's output is the tool's own words: the runtime wraps them in a notice to
        the model, which used to be all a customer saw of a failed step."""
        S = self.S
        for scenario, key in (('SCENARIO:badsite_plain', 'k-badsite-plain'), ('SCENARIO:badsite', 'k-badsite')):
            with self.subTest(scenario=scenario):
                sent, row = self.run_to_end('a', f'What are the opening hours? {scenario}', key)
                self.assertEqual(row['state'], 'completed')                                         # the assistant read the refusal and answered: a failed step is not a failed task
                recorded = S.rows("SELECT reason,kind,actor,expected,detail_json FROM faults WHERE request_id=?", (sent['id'],))
                self.assertEqual([(r['reason'], r['kind'], r['actor'], r['expected'], json.loads(r['detail_json'])['tool']) for r in recorded],
                                 [('tool.bad_arguments', 'invalid', 'assistant', 0, 'lumina_browser')])
                steps = [e['payload'] for e in S.events.events(S.principals['a'], sent['id'])['events'] if e['kind'] == 'activity' and e['payload'].get('status') == 'failed']
                self.assertTrue(steps)
                self.assertEqual({p.get('reason') for p in steps}, {'tool.bad_arguments'})
                self.assertIn('The browser task could not be read (site', steps[-1]['output'])
                self.assertNotIn('SECURITY NOTICE', steps[-1]['output'])
                self.assertEqual([c for c in S.browse.calls if c[0] == 'start' and c[1]['request_id'] == sent['id']], [])      # nothing was opened

    def test_a_model_call_the_provider_refuses_gives_the_task_one_reason_and_the_runtimes_words_are_not_a_reply(self):
        """Reliability plan, Part 2. The real runtime writes its own words for a failed model call as the run's last assistant message, marked as ended by an error
        ("LLM request failed (..., HTTP 404)."). Lumina must not show that as the assistant's reply, and it takes the status number in it as the fact that decides the one
        sentence the customer reads. (In production the relay's own record of the call comes first; this stack's model is called directly, so the runtime's number decides.)"""
        from agentai_platform.faults_registry import REASONS
        S = self.S
        for status, reason in ((404, 'model.not_offered'), (500, 'model.provider_error')):
            with self.subTest(status=status):
                sent, row = self.run_to_end('a', f'please do it SCENARIO:refuse{status}', f'k-refuse-{status}')
                self.assertEqual((row['state'], row['outcome']), ('failed', 'failed'))
                self.assertEqual((row['outcome_note'], row['result']), (REASONS[reason].customer, REASONS[reason].customer))
                replies = [r['content'] for r in S.rows("SELECT content FROM chat_messages WHERE request_id=? AND provenance='agent'", (sent['id'],))]
                self.assertEqual(replies, [])
                fault, = S.rows('SELECT reason FROM faults WHERE request_id=?', (sent['id'],))
                self.assertEqual(fault['reason'], reason)
        _, after = self.run_to_end('a', 'an ordinary question', 'k-after-refusals')
        self.assertEqual(after['state'], 'completed', after['result'])                              # neither status makes the runtime disable the key

    def test_a_refused_model_call_does_not_disable_the_key_for_the_next_message(self):
        """What the runtime does with a refusal from its model provider decides the status Lumina's gateway may use (model_keys.RELAY_REFUSAL). With 403 the runtime disables
        the key and the customer's next message fails at once; with 409 only the refused call fails."""
        from agentai_platform.model_keys import RELAY_REFUSAL
        S = self.S
        _, refused = self.run_to_end('b', f'please do it SCENARIO:refuse{RELAY_REFUSAL}', 'k-refused')
        self.assertEqual(refused['state'], 'failed')                                               # the call that had no right to run did not run
        _, after = self.run_to_end('b', 'an ordinary question', 'k-after-refused')
        self.assertEqual(after['state'], 'completed', after['result']); self.assertIn('Plain answer', after['result'])
        _, poisoned = self.run_to_end('b', 'please do it SCENARIO:refuse403', 'k-refused-403')    # and this is why it must not be 403: the same two steps...
        _, after = self.run_to_end('b', 'another ordinary question', 'k-after-403')
        self.assertEqual((poisoned['state'], after['state']), ('failed', 'failed'))                # ...and the ordinary question fails too. (Last in the class: account b's key stays disabled for a minute.)

    def test_the_cell_config_lumina_provisions_is_accepted_by_the_runtime_and_enforced(self):
        S = self.S
        config = S.cells['a'].config
        self.assertEqual(sorted(config['tools']['deny']), ['ask_user', 'browser'])
        self.assertEqual(config['agents']['defaults']['timeoutSeconds'], 1200)
        self.assertEqual(config['tools']['toolSearch'], {'mode': 'directory'})                     # a tool's plain name is run as that tool
        self.assertEqual(config['skills']['workshop']['autonomous'], {'mode': 'off'})                # no background model call that no task pays for
        self.assertEqual(config['mcp']['servers']['lumina']['headers']['Authorization'], 'Bearer ' + S.cells['a'].key)
        self.assertIsNone(S.cells['a'].proc.poll())                                                 # the gateway started with exactly this config


if __name__ == '__main__':
    unittest.main()
