import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from agentai_platform.budget import BudgetLedger, BudgetDenied
from agentai_platform.chat import ChatService, FixedRoute, UnmeasuredRoute
from agentai_platform.chat_driver import ChatDriver, synthetic_gateway_factory
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.request_queue import Recover, RequestQueue
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.capacity import CapacityResult
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.store import Store

CAPACITY = CapacityResult(1, 1, 1, 1, 1, ())
LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000,
          'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class ChatChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3');self.store.initialize()
        self.now = 2000000000
        self.gateway = SyntheticGateway()
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10000000, clock=lambda:self.now)
        self.route = FixedRoute(500)
        self.service = ChatService(self.store, queue=RequestQueue(self.store, clock=lambda:self.now),
                                   ledger=self.ledger, pricer=self.route, clock=lambda:self.now)
        self.queue = self.service.queue
        self.a = Principal('a', 'actor-a', 'customer');self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for a in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (a, 'd-' + a))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (a, 'p-' + a, 'Project ' + a))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)', (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",
                            (a, 'e-' + a, json.dumps(LIMITS), self.now + 1000000))

    def send(self, principal=None, conversation=None, message='hello agent', key='k1'):
        actor = principal or self.a
        return self.service.send(actor, conversation_id=conversation or ('c-' + actor.account_id), message=message, key=key)

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def test_send_admits_task_and_transcript_once(self):
        result = self.send()
        self.assertEqual((result['admission'], result['execution_enabled']), ('reserved', True))
        self.assertTrue(self.rows("SELECT 1 FROM tasks WHERE account_id='a' AND id=? AND state='queued'", (result['id'],)))
        self.assertTrue(self.rows("SELECT 1 FROM task_reservations WHERE account_id='a' AND task_id=? AND state='active'", (result['id'],)))
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='customer'", (result['id'],))), 1)
        again = self.send(key='k1')
        self.assertEqual(again['id'], result['id'])
        self.assertEqual(len(self.rows('SELECT 1 FROM tasks WHERE account_id="a"')), 1)
        self.assertEqual(len(self.rows('SELECT 1 FROM chat_messages')), 1)

    def test_duplicate_payload_change_and_foreign_conversation(self):
        self.send(key='k1')
        with self.assertRaises(Conflict):
            self.send(key='k1', message='changed')
        with self.assertRaises(NotFound):
            self.service.send(self.b, conversation_id='c-a', message='x', key='k9')
        with self.assertRaises(ValueError):
            self.send(key='bad key!')
        with self.assertRaises(ValueError):
            self.send(message='')

    def test_unmeasured_route_leaves_request_waiting_unfunded(self):
        self.service.pricer = UnmeasuredRoute()
        result = self.send()
        self.assertEqual((result['admission'], result['execution_enabled']), ('route_unconfigured', False))
        self.assertFalse(self.rows('SELECT 1 FROM tasks'))
        self.assertTrue(self.rows("SELECT 1 FROM customer_requests WHERE state='waiting' AND id=?", (result['id'],)))

    def test_budget_denial_cancels_request_without_residue(self):
        with self.store.connect() as con:
            limits = dict(LIMITS, period_microusd=600)
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(limits),))
        self.send(key='first')
        with self.assertRaises(BudgetDenied) as caught:
            self.send(key='second')
        self.assertEqual(str(caught.exception), 'account allowance exhausted')
        self.assertEqual(self.rows("SELECT state FROM customer_requests WHERE idempotency_key='second'")[0][0], 'cancelled')

    def test_queue_ceiling_denial_cancels_request(self):
        with self.store.connect() as con:
            limits = dict(LIMITS, max_queued_tasks=1)
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(limits),))
        self.send(key='first')
        with self.assertRaises(BudgetDenied):
            self.send(key='second')
        self.assertFalse(self.rows("SELECT 1 FROM customer_requests WHERE state='waiting' AND idempotency_key='second'"))

    def test_conversation_scoping_and_cap(self):
        self.service.max_conversations_per_project = 3
        first = self.service.create_conversation(self.a, 'p-a')
        second = self.service.create_conversation(self.a, 'p-a')
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaises(Conflict):
            self.service.create_conversation(self.a, 'p-a')
        with self.assertRaises(NotFound):
            self.service.create_conversation(self.a, 'p-b')
        self.assertCountEqual([c['id'] for c in self.service.conversations(self.a, 'p-a')], ['c-a', first['id'], second['id']])
        project = self.service.create_project(self.a, 'Second project')
        self.assertTrue(self.service.projects(self.a)[1]['id'] == project['id'] != 'p-a')
        with self.assertRaises(Conflict):
            for i in range(10):
                self.service.create_project(self.a, 'project ' + str(i))

    def test_messages_pagination_and_cross_account(self):
        result = self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, ChatDriver(self.store, ledger=self.ledger,
                          gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda:self.now).execute(claim))
        page = self.service.messages(self.a, 'c-a')
        self.assertEqual([m['provenance'] for m in page['messages']], ['customer', 'agent'])
        self.assertEqual(page['messages'][0]['content'], 'hello agent')
        self.assertEqual([t['state'] for t in page['tasks']], ['completed'])
        after = page['messages'][0]['id']
        self.assertEqual([m['provenance'] for m in self.service.messages(self.a, 'c-a', after=after)['messages']], ['agent'])
        with self.assertRaises(NotFound):
            self.service.messages(self.b, 'c-a')
        with self.assertRaises(ValueError):
            self.service.messages(self.a, 'c-a', after=-1)
        with self.assertRaises(ValueError):
            self.service.messages(self.a, 'c-a', limit=101)

    def test_task_read_and_waiting_cancel(self):
        result = self.send()
        state = self.service.task(self.a, result['id'])
        self.assertEqual((state['state'], state['task_state'], state['reservation_state']), ('waiting', 'queued', 'active'))
        with self.assertRaises(NotFound):
            self.service.task(self.b, result['id'])
        self.assertEqual(self.service.cancel(self.a, result['id'])['state'], 'cancelled')
        self.assertIsNone(self.queue.claim(owner='w', capacity=CAPACITY))

    def test_retry_runs_a_cancelled_task_again_as_one_new_task(self):
        first = self.service.send(self.a, conversation_id='c-a', message='find paddles', key='k1', mode='text')
        with self.assertRaises(Conflict):
            self.service.retry(self.a, first['id'])                                       # it has not failed: nothing to retry
        self.service.cancel(self.a, first['id'])
        again = self.service.retry(self.a, first['id'])
        self.assertNotEqual(again['id'], first['id'])
        self.assertEqual((again['state'], again['retry_of'], again['admission']), ('waiting', first['id'], 'reserved'))
        self.assertEqual(self.rows('SELECT context_json,intent,conversation_id FROM customer_requests WHERE id=?', (again['id'],))[0][:], ('{"mode":"text"}', 'chat', 'c-a'))   # same mode, same conversation
        self.assertTrue(self.rows("SELECT 1 FROM task_reservations WHERE account_id='a' AND task_id=? AND state='active'", (again['id'],)))      # its own budget reservation
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE conversation_id='c-a' AND provenance='customer'")), 2)
        self.assertEqual(self.service.retry(self.a, first['id'])['id'], again['id'])      # pressing it twice gives the one retry
        self.assertEqual(len(self.rows("SELECT 1 FROM customer_requests WHERE retry_of=?", (first['id'],))), 1)
        with self.assertRaises(NotFound):
            self.service.retry(self.b, first['id'])
        self.service.cancel(self.a, again['id'])
        third = self.service.retry(self.a, again['id'])                                    # a retry can itself be retried
        self.assertEqual(third['retry_of'], again['id'])

    def test_a_retry_the_budget_refuses_leaves_nothing_behind_and_can_be_tried_again_later(self):
        first = self.send(key='k1'); self.service.cancel(self.a, first['id'])
        with self.store.connect() as con:
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(dict(LIMITS, period_microusd=100)),))
        with self.assertRaises(BudgetDenied):
            self.service.retry(self.a, first['id'])
        self.assertFalse(self.rows("SELECT 1 FROM customer_requests WHERE state='waiting' AND idempotency_key LIKE 'retry-%'"))
        with self.store.connect() as con:
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(LIMITS),))
        later = self.service.retry(self.a, first['id'])                                    # a new attempt, not the dead cancelled one
        self.assertEqual((later['state'], later['admission']), ('waiting', 'reserved'))

    def test_a_completed_task_and_an_archived_conversation_cannot_be_retried(self):
        done = self.send(key='k1')
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='completed' WHERE id=?", (done['id'],))
        with self.assertRaises(Conflict):
            self.service.retry(self.a, done['id'])
        gone = self.send(key='k2'); self.service.cancel(self.a, gone['id'])
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET archived_epoch=? WHERE id='c-a'", (self.now,))
        with self.assertRaises(Conflict):
            self.service.retry(self.a, gone['id'])

    def test_pause_and_resume_hold_a_waiting_task_through_the_service(self):
        item = self.send()
        self.assertTrue(self.service.pause(self.a, item['id'])['paused'])
        self.assertTrue(self.service.messages(self.a, 'c-a')['tasks'][0]['paused'])           # the chat page learns it too, so it does not show a working orb
        self.assertTrue(self.service.task(self.a, item['id'])['paused'])
        self.assertIsNone(self.queue.claim(owner='w', capacity=CAPACITY))
        self.assertFalse(self.service.resume(self.a, item['id'])['paused'])
        self.assertIsNotNone(self.queue.claim(owner='w', capacity=CAPACITY))
        with self.assertRaises(Conflict):
            self.service.pause(self.a, item['id'])                                         # it has started

    def metered_driver(self, gateway, **kw):
        return ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gateway),
                          clock=lambda: self.now, sleep=lambda s: None, **kw)

    def test_assistant_tool_use_becomes_activity_events_for_this_request_only(self):
        from agentai_platform.events import EventService
        other = {'ref': 'old1', 'tool': 'exec', 'category': 'command', 'label': 'Ran a command', 'detail': 'ls', 'output': '', 'status': 'done', 'run_id': 'an-earlier-run', 'after': 'an-earlier-request-a1'}
        class Tools(SyntheticGateway):
            def history(self, session, cursor=None):
                page = super().history(session, cursor)
                run = next(iter(self.runs), 'none')
                mine = {'ref': 'new1', 'tool': 'web_search', 'category': 'search', 'label': 'Searched the web', 'detail': 'pickleball', 'output': '', 'status': 'running', 'run_id': run, 'after': run}
                page['activity'] = [other, mine, {**mine, 'status': 'done'}]
                return page
        self.send()
        tools = Tools(polls=1)
        key, _, _ = tools.open_session('op', 'chat-x')                  # an existing session with an earlier turn's tool use
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET native_session_ref=? WHERE account_id='a' AND id='c-a'", (key,))
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        events = EventService(self.store, clock=lambda: self.now)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(tools),
                            clock=lambda: self.now, sleep=lambda s: None, events=events)
        self.queue.finish(claim, driver.execute(claim))
        rows = [e['payload'] for e in events.events(self.a, claim.request_id)['events'] if e['kind'] == 'activity']
        self.assertEqual([(r['ref'], r['status']) for r in rows], [('new1', 'running'), ('new1', 'done')])      # the earlier run's call is not this request's, and nothing is shown twice
        self.assertNotIn('run_id', rows[0]); self.assertNotIn('after', rows[0])

    def test_files_the_assistant_wrote_become_versioned_downloads(self):
        from agentai_platform.artifacts import ArtifactService
        from agentai_platform.events import EventService
        from agentai_platform.storage import RootStore
        storage = RootStore(Path(self.tmp.name) / 'storage')
        artifacts = ArtifactService(self.store, storage=storage, signing_key=b'k' * 32, clock=lambda: self.now)
        files = [[('slug.py', b'print(1)\n'), ('sub/page.html', b'<p>hi</p>'), ('evil.exe', b'MZ\x00\x00'), ('data.json', b'not json {')]]
        class Writes(SyntheticGateway):
            def workspace_files(self, since): return files[0]
        events = EventService(self.store, clock=lambda: self.now)
        gw = Writes()
        def run(key):
            self.send(key=key)
            claim = self.queue.claim(owner='w', capacity=CAPACITY)
            driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gw), clock=lambda: self.now,
                                sleep=lambda s: None, events=events, artifacts=artifacts)
            self.queue.finish(claim, driver.execute(claim))
            return claim
        run('f1')
        listed = {a['display_name']: a for a in artifacts.list_artifacts(self.a, 'p-a')}
        self.assertEqual(sorted(listed), ['slug.py', 'sub_page.html'])              # .exe and invalid json refused
        files[0] = [('slug.py', b'print(1)\n'), ('sub/page.html', b'<p>changed</p>')]
        claim = run('f2')
        rows = artifacts.list_artifacts(self.a, 'p-a')
        self.assertEqual(sorted((a['display_name'], a['version']) for a in rows), [('slug.py', 1), ('sub_page.html', 1), ('sub_page.html', 2)])
        self.assertEqual([e['payload']['name'] for e in events.events(self.a, claim.request_id)['events'] if e['kind'] == 'artifact'], ['sub_page.html'])

    def test_usage_is_reconciled_from_provider_spend_delta(self):
        class Metered(SyntheticGateway):
            spend = [1000, 1000, 1700, 1700, 1700]
            def usage_snapshot(self): return self.spend.pop(0) if len(self.spend) > 1 else self.spend[0]
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, self.metered_driver(Metered()).execute(claim))
        receipt = self.rows("SELECT amount_microusd,price_version FROM provider_receipts WHERE account_id='a'")
        self.assertEqual([tuple(r) for r in receipt], [(700, 'litellm-reported-v1')])
        self.assertEqual(self.rows("SELECT state FROM task_reservations WHERE account_id='a'")[0][0], 'settled')

    def test_unreadable_spend_charges_the_reserved_upper_bound(self):
        class Blind(SyntheticGateway):
            def usage_snapshot(self): raise RuntimeError('no spend')
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.finish(claim, self.metered_driver(Blind()).execute(claim))
        self.assertEqual([tuple(r) for r in self.rows("SELECT amount_microusd,price_version FROM provider_receipts")],
                         [(500, 'reservation-upper-bound-v1')])

    def test_run_that_never_ends_is_stopped_at_its_time_limit_and_failed(self):
        gateway = SyntheticGateway(polls=10**6)
        def advance(seconds): self.now += 300
        self.send()
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(gateway),
                            clock=lambda: self.now, sleep=advance, run_timeout=900)
        receipt = driver.execute(claim)
        self.assertEqual((receipt.state, receipt.outcome), ('failed', 'failed'))
        self.assertTrue([c for c in gateway.calls if c[0] == 'abort'])                      # the runtime was told to stop and confirmed it
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'aborted')

    def driver(self):
        return ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway), clock=lambda:self.now)

    def test_driver_completes_serial_handoff_without_duplicate_transcript(self):
        first = self.send(key='r1');self.send(self.b, key='r2')
        self.assertTrue(self.queue.run_once(self.driver(), owner='w', capacity=CAPACITY))
        self.assertEqual(self.queue.get(self.a, first['id'])['state'], 'completed')
        self.assertIn('ack ', self.queue.get(self.a, first['id'])['result'])
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE conversation_id='c-a'")), 2)
        self.assertEqual(self.rows("SELECT state FROM task_reservations WHERE account_id='a'")[0][0], 'settled')
        self.assertEqual(self.rows("SELECT state FROM tasks WHERE account_id='a'")[0][0], 'completed')
        self.assertTrue(self.queue.run_once(self.driver(), owner='w', capacity=CAPACITY))
        self.assertEqual(self.queue.get(self.b, self.queue.get(self.b)[0]['id'])['state'], 'completed')
        self.assertIsNone(self.queue.claim(owner='w', capacity=CAPACITY))
        self.assertEqual(sum(1 for call in self.gateway.calls if call[0] == 'send'), 2)

    def test_driver_cancel_before_send_sends_nothing(self):
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        # Claimed (starting): cancel records intent that the driver honours before any effect.
        self.service.cancel(self.a, result['id'])
        receipt = self.driver().execute(claim)
        self.assertEqual((receipt.state, receipt.outcome), ('cancelled', 'cancelled'))
        self.assertTrue(self.queue.finish(claim, receipt))
        self.assertFalse(self.rows('SELECT 1 FROM chat_deliveries'))                      # nothing was handed to the runtime, so there is nothing to abort
        self.assertEqual(self.rows('SELECT state FROM tasks')[0][0], 'cancelled')
        self.assertEqual(self.gateway.calls, [])

    def test_driver_cancel_during_run_aborts_and_waits_for_the_runtime_to_confirm(self):
        result = self.send(key='r1')
        request_id = result['id']

        def set_cancel(run):
            with self.store.connect() as con:
                con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (request_id,))
        self.gateway.polls = 5
        self.gateway.on_wait = set_cancel
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        receipt = self.driver().execute(claim)
        self.assertEqual((receipt.state, receipt.outcome), ('cancelled', 'cancelled'))
        self.assertTrue(self.queue.finish(claim, receipt))
        aborts = [c for c in self.gateway.calls if c[0] == 'abort']
        self.assertEqual(len(aborts), 1)
        self.assertEqual(self.rows('SELECT state,native_status FROM chat_deliveries')[0][:], ('aborted', 'aborted'))
        self.assertEqual(self.gateway.runs[self.rows('SELECT native_run_id FROM chat_deliveries')[0][0]]['error'], 'aborted')

    def test_unsupported_abort_stays_uncertain_with_intent(self):
        self.gateway.abort_supported = False
        result = self.send(key='r1')
        request_id = result['id']

        def set_cancel(run):
            with self.store.connect() as con:
                con.execute('UPDATE customer_requests SET cancel_requested=1 WHERE id=?', (request_id,))
        self.gateway.polls = 5
        self.gateway.on_wait = set_cancel
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(CapabilityUnavailable):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertEqual(self.queue.get(self.a, request_id)['state'], 'uncertain')
        self.assertEqual(self.rows('SELECT cancel_requested FROM customer_requests')[0][0], 1)
        self.assertFalse([c for c in self.gateway.calls if c[0] == 'abort'])

    def test_unknown_outcome_send_is_settled_by_sending_the_same_key_again(self):
        self.gateway.timeout_after_write = True
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(TimeoutError):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'uncertain')
        outcome = self.queue.reconcile(self.driver(), claim)
        self.assertIsInstance(outcome, Recover)                                    # the runtime is reachable: supervision carries on
        again = self.queue.recover(claim, owner='w')
        self.assertTrue(self.queue.finish(again, self.driver().execute(again)))
        self.assertEqual(self.queue.get(self.a, result['id'])['state'], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)                                # the repeat did not start a second run
        self.assertEqual(len([r for r in self.gateway.sessions[self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]]['rows'] if r['role'] == 'customer']), 1)
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE provenance='agent'")), 1)

    def test_fail_after_ack_is_recovered_without_a_second_run(self):
        self.gateway.fail_after_ack = True
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(RuntimeError):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        self.assertIsInstance(self.queue.reconcile(self.driver(), claim), Recover)
        again = self.queue.recover(claim, owner='w')
        self.queue.finish(again, self.driver().execute(again))
        self.assertIn('ack ', self.queue.get(self.a, result['id'])['result'])
        self.assertEqual(len(self.rows("SELECT 1 FROM chat_messages WHERE provenance='agent'")), 1)
        self.assertEqual(self.rows('SELECT state FROM chat_deliveries')[0][0], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)

    def test_a_request_that_never_reached_the_runtime_is_failed_without_charge_on_reconcile(self):
        self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        self.queue.uncertain(claim)
        self.assertTrue(self.queue.reconcile(self.driver(), claim))
        self.assertEqual(self.rows('SELECT state,outcome FROM customer_requests')[0][:], ('failed', 'failed'))

    def test_execute_requires_admission_and_probe(self):
        self.service.pricer = UnmeasuredRoute()
        result = self.send(key='r1')
        claim = self.queue.claim(owner='w', capacity=CAPACITY)
        with self.assertRaises(Conflict):
            self.driver().execute(claim)
        self.queue.uncertain(claim)
        broken = SyntheticGateway(protocol_version=99)
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(broken))
        with self.assertRaises(CapabilityUnavailable):
            driver.preflight()
        with self.assertRaises(ValueError):
            ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gateway)).execute(
                replace(claim, conversation_id=None))


if __name__ == '__main__':
    unittest.main()
