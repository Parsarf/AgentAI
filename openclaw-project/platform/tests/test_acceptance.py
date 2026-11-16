"""Tier A acceptance cases (roadmap #3, #4): the workflows customers already use, run through the real chat service, queue, worker and driver against the synthetic runtime.

Each case has an id (`CASE`), states what a customer does, and asserts only on FACTS the platform holds: rows in customer_requests, chat_deliveries, provider_receipts,
task_reservations and events, and calls the runtime received. Never on the assistant's wording. `deploy/acceptance.py` runs these, writes one result per case and
compares it with the previous release's results, so a workflow that worked before and does not now refuses the change. A new customer-visible behaviour adds a case here.
"""
import json
import unittest

from agentai_platform import spend_limits
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.chat import FixedRoute
from agentai_platform.chat_driver import BUSY_FAILURE
from agentai_platform.gateway import SyntheticGateway
from agentai_platform.security import NotFound, Principal

from tests.test_native_run import OK, Base


def case(case_id):
    def mark(fn):
        fn.CASE = case_id
        return fn
    return mark


class Acceptance(Base):
    def facts(self, request_id):
        return {'request': self.request(request_id),
                'deliveries': [dict(r) for r in self.rows('SELECT * FROM chat_deliveries WHERE request_id=? ORDER BY attempt', (request_id,))],
                'receipts': [dict(r) for r in self.rows('SELECT * FROM provider_receipts WHERE task_id=?', (request_id,))],
                'reservation': [dict(r) for r in self.rows('SELECT * FROM task_reservations WHERE task_id=?', (request_id,))],
                'events': [r['kind'] for r in self.rows('SELECT kind FROM events WHERE task_id=? ORDER BY sequence', (request_id,))],
                'replies': len(self.rows("SELECT 1 FROM chat_messages WHERE request_id=? AND provenance='agent'", (request_id,)))}

    @case('A-PLAIN-ANSWER')
    def test_a_message_is_answered_once_and_settled(self):
        sent = self.run_message('what is the capital of France', ['Paris.'])
        f = self.facts(sent['id'])
        self.assertEqual((f['request']['state'], f['request']['outcome']), ('completed', 'completed'))
        self.assertEqual([d['state'] for d in f['deliveries']], ['completed'])
        self.assertEqual(f['replies'], 1)
        self.assertEqual(f['reservation'][0]['state'], 'settled')
        self.assertEqual(len(self.gateway.runs), 1)
        self.assertEqual(self.rows('SELECT state FROM tasks WHERE id=?', (sent['id'],))[0][0], 'completed')
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 0)               # the running slot was handed back

    @case('A-VERSION-STAMP')
    def test_every_request_records_which_code_rules_tools_and_runtime_served_it(self):
        sent = self.run_message('hello', ['hi'])
        stamp = json.loads(self.request(sent['id'])['versions_json'])
        self.assertEqual(set(stamp), {'release', 'rules', 'tools', 'runtime', 'model'})
        self.assertEqual(stamp['runtime'], 'synthetic-2026.9.6')
        self.assertTrue(all(isinstance(v, str) and v for v in stamp.values()))

    @case('A-QUEUE-ORDER')
    def test_a_second_task_waits_for_the_first_and_then_runs(self):
        first = self.say('first', key='k1')
        with self.store.connect() as con:
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-a2','d-a')")
        second = self.chat.send(self.a, conversation_id='c-a2', message='second', key='k2')
        self.assertEqual(self.chat.queue.get(self.a, second['id'])['ahead'], 1)
        self.worker.tick()
        self.assertEqual((self.request(first['id'])['state'], self.request(second['id'])['state']), ('completed', 'waiting'))
        self.worker.tick()
        self.assertEqual(self.request(second['id'])['state'], 'completed')
        self.assertEqual(len(self.gateway.runs), 2)

    @case('A-STEER')
    def test_a_message_sent_during_a_run_joins_it_instead_of_starting_a_second_task(self):
        first = self.say('find wings', key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        steered = self.say('make it vegetarian', key='k2')
        self.assertEqual((steered['steered'], steered['id']), (True, first['id']))
        self.assertEqual(self.rows('SELECT count(*) FROM customer_requests')[0][0], 1)
        self.assertEqual(self.rows('SELECT count(*) FROM task_reservations')[0][0], 1)
        receipt = self.driver.execute(claim)
        self.assertEqual(receipt.state, 'completed')
        self.assertEqual({d['kind'] for d in self.facts(first['id'])['deliveries']}, {'turn', 'steer'})

    @case('A-STOP')
    def test_stop_during_a_run_aborts_it_and_nothing_arrives_afterwards(self):
        sent = self.say('long task', key='k1')
        self.gateway.polls = 50
        self.gateway.on_wait = lambda run: self.chat.cancel(self.a, sent['id'])
        self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual((f['request']['state'], f['request']['outcome']), ('cancelled', 'cancelled'))
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])
        self.assertEqual(f['reservation'][0]['state'], 'settled')
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 0)

    @case('A-GOAL-CHAIN')
    def test_keep_working_until_complete_runs_as_a_chain_of_admitted_turns(self):
        states = ['active', 'active', 'complete']
        def script(text, run, gw):
            session = gw.sessions[run['session']]
            if session.get('goal'):
                session['goal']['status'] = states.pop(0) if states else 'complete'
            return {'text': 'working'}
        self.gateway.script = script
        first = self.chat.send(self.a, conversation_id='c-a', message='build the report', key='g1', goal=True)
        for _ in range(8):
            self.worker.tick()
        chain = self.rows("SELECT id,state,continue_goal,continues FROM customer_requests ORDER BY sequence")
        self.assertEqual(len(chain), 3)                                                          # three turns, each a request of its own with its own reservation
        self.assertEqual([r['state'] for r in chain], ['completed'] * 3)
        self.assertEqual([r['continue_goal'] for r in chain], [1, 1, 0])
        self.assertEqual(chain[1]['continues'], first['id'])
        self.assertEqual(self.rows('SELECT count(*) FROM task_reservations')[0][0], 3)

    @case('A-RECOVER-WORKER')
    def test_a_worker_that_dies_mid_run_is_recovered_onto_the_same_run(self):
        sent = self.say('work', key='k1')
        self.gateway.fail_after_ack = True
        with self.assertRaises(RuntimeError):
            self.worker.tick()
        self.assertEqual(self.request(sent['id'])['state'], 'uncertain')
        self.gateway.fail_after_ack = False
        self.now += 130                                                                           # its lease has run out; the next tick reconciles it first
        self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual(f['request']['state'], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)                                               # one run, never a second
        self.assertEqual(f['reservation'][0]['state'], 'settled')                                 # settled once
        self.assertLessEqual(len(f['receipts']), 1)                                               # never charged twice

    @case('A-RECOVER-CELL')
    def test_an_input_the_cell_lost_in_a_restart_runs_exactly_once(self):
        class Restarting(SyntheticGateway):
            def lose(self):
                for key, run in list(self.runs.items()):
                    if run['state'] in ('running', 'queued'):
                        del self.runs[key]; self.interrupted.add(key)
                        self.sessions[run['session']]['rows'] = [r for r in self.sessions[run['session']]['rows'] if r.get('idempotency_key') != key + ':user']
        self.gateway = Restarting(polls=2)
        self.chat.gateway_factory = lambda account: self.gateway
        self.make_worker()
        sent = self.say('work', key='k1')
        claim = self.queue.claim(owner='w', capacity=OK)
        self.driver._begin(claim, self.gateway, self.driver._admit(claim))
        self.driver._deliver(claim, self.gateway, self.driver._session(claim), self.driver._deliveries(claim)[0])
        self.queue.uncertain(claim)
        self.gateway.lose()
        receipt = self.driver.execute(self.queue.recover(claim, owner='w'))
        self.assertEqual(receipt.state, 'completed')
        self.assertEqual(len(self.gateway.runs), 1)
        self.assertEqual(self.facts(sent['id'])['replies'], 1)

    @case('A-CELL-UNREACHABLE')
    def test_a_cell_that_cannot_be_reached_leaves_the_request_recoverable_not_failed(self):
        class Down(SyntheticGateway):
            down = 0
            def wait(self, run_id, timeout_ms):
                if self.down:
                    self.down -= 1; raise CapabilityUnavailable('gateway call unavailable')
                return super().wait(run_id, timeout_ms)
        self.gateway = Down(polls=2); self.chat.gateway_factory = lambda account: self.gateway
        self.make_worker(outage_limit=60)
        sent = self.say('work', key='k1')
        self.gateway.down = 5
        self.worker.tick()
        self.assertEqual(self.request(sent['id'])['outcome'], 'completed')
        self.assertEqual(len(self.gateway.runs), 1)

    @case('A-BUSY-PROVIDER')
    def test_a_task_that_failed_on_a_busy_provider_says_so_and_charges_only_what_was_spent(self):
        self.gateway.script = lambda text, run, gw: {'error': 'The model request was rate-limited. Please try again in a few minutes'}
        sent = self.say('work', key='k1')
        self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual((f['request']['state'], f['request']['result']), ('failed', BUSY_FAILURE))
        self.assertEqual(f['reservation'][0]['state'], 'settled')
        self.assertTrue(all(r['amount_microusd'] < 1000000 for r in f['receipts']))             # never the reservation

    @case('A-NO-LIMIT')
    def test_with_no_limit_set_a_costly_task_runs_to_the_end(self):
        class Spender(SyntheticGateway):
            readings = [0, 700000, 5000000, 90000000, 90000000]
            def usage_snapshot(self): return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        self.gateway = Spender(polls=3); self.chat.gateway_factory = lambda account: self.gateway
        self.make_worker(spend_check_seconds=0)
        self.chat.pricer = FixedRoute(spend_limits.NO_LIMIT, 'no-limit-v1')
        sent = self.say('expensive', key='k1')
        self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual(f['request']['outcome'], 'completed')
        self.assertFalse([c for c in self.gateway.calls if c[0] == 'abort'])
        self.assertEqual(f['receipts'][0]['amount_microusd'], 90000000)

    @case('A-CUSTOMER-LIMIT')
    def test_the_customers_own_task_limit_stops_a_run_as_partial(self):
        class Spender(SyntheticGateway):
            readings = [0, 700000, 1400000, 2100000]
            def usage_snapshot(self): return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        self.gateway = Spender(polls=50); self.chat.gateway_factory = lambda account: self.gateway
        self.make_worker(spend_check_seconds=0)
        with self.store.connect() as con:
            spend_limits.put(con, 'a', {'task': 1000000, 'daily': None, 'period': None}, now=self.now)
        sent = self.say('expensive', key='k1')
        self.assertEqual(self.facts(sent['id'])['reservation'][0]['amount_microusd'], 1000000)
        self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual((f['request']['state'], f['request']['outcome']), ('completed', 'partial'))
        self.assertTrue([c for c in self.gateway.calls if c[0] == 'abort'])

    @case('A-ISOLATION')
    def test_one_account_cannot_read_stop_or_steer_another_accounts_work(self):
        sent = self.say('private', key='k1')
        b = Principal('b', 'actor-b', 'customer')
        for attempt in (lambda: self.chat.queue.get(b, sent['id']), lambda: self.chat.cancel(b, sent['id']),
                        lambda: self.chat.messages(b, 'c-a'), lambda: self.chat.send(b, conversation_id='c-a', message='x', key='kb')):
            with self.assertRaises(NotFound):
                attempt()
        self.assertEqual(self.request(sent['id'])['cancel_requested'], 0)
        self.assertEqual(self.chat.queue.get(b), [])                                             # b's own list shows nothing of a's
        impostor = Principal('a', 'actor-b', 'customer')                                         # the right account id with someone else's identity
        with self.assertRaises(Exception):
            self.chat.queue.get(impostor, sent['id'])

    @case('A-OUTPUT-CUTOFF')
    def test_a_reply_cut_off_at_the_models_output_limit_is_carried_on_in_the_same_task(self):
        from agentai_platform.chat_driver import CUTOFF_TEXT
        self.gateway.script = lambda text, run, gw: ({'text': 'Part one. ', 'stop_reason': 'length'} if text != CUTOFF_TEXT else {'text': 'Part two.'})
        sent = self.say('write the long report', key='k-cut')
        for _ in range(4):
            self.worker.tick()
        f = self.facts(sent['id'])
        self.assertEqual((f['request']['state'], f['request']['outcome']), ('completed', 'completed'))
        self.assertEqual([d['payload'] == CUTOFF_TEXT for d in f['deliveries']], [False, True])      # one automatic continuation, in the same task
        self.assertEqual(f['replies'], 2)
        self.assertEqual(f['reservation'][0]['state'], 'settled')

    @case('A-PARALLEL-ACCOUNTS')
    def test_two_accounts_hold_a_running_slot_at_the_same_time_and_one_without_a_cell_waits(self):
        with self.store.connect() as con:                                                            # account b exists (no cell yet); give it one, and add c without a cell
            con.execute("INSERT INTO operations(account_id,id,deployment_id,kind,state,idempotency_key,request_hash,generation) VALUES ('b','op-b','d-b','start','completed','k','h',1)")
            con.execute("INSERT INTO cell_slots(account_id,deployment_id,operation_id,state) VALUES ('b','d-b','op-b','active')")
            con.execute("INSERT INTO accounts(id,status) VALUES ('c','active')")
            con.execute("INSERT INTO memberships VALUES ('c','actor-c','customer','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('c','d-c',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('c','p-c','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('c','p-c','c-c','d-c')")
            con.execute("INSERT INTO entitlements VALUES ('c','e-c','test-v1','trial',?,datetime(?,'unixepoch'))", (json.dumps({'period_start_epoch': self.now - 100000, 'period_microusd': 10**9, 'daily_microusd': 10**9, 'task_microusd': 5000000, 'max_queued_tasks': 3}), self.now + 10**6))
        self.say('from a', key='k-a')
        self.chat.send(Principal('b', 'actor-b', 'customer'), conversation_id='c-b', message='from b', key='k-b')
        third = self.chat.send(Principal('c', 'actor-c', 'customer'), conversation_id='c-c', message='from c', key='k-c')     # c has no cell up
        one, two = self.queue.claim(owner='w', capacity=OK), self.queue.claim(owner='w', capacity=OK)
        self.assertEqual({one.account_id, two.account_id}, {'a', 'b'})                              # both run at the same moment
        self.assertEqual(self.rows('SELECT count(*) FROM request_slots')[0][0], 2)
        self.assertIsNone(self.queue.claim(owner='w', capacity=OK))                                  # c waits for its own cell, nothing fails
        self.assertEqual(self.request(third['id'])['state'], 'waiting')

    @case('A-PLAN-REVISION')
    def test_a_revision_of_a_running_plan_never_rewrites_a_finished_phase_and_may_replace_a_failed_one(self):
        from agentai_platform.genui import replan, schema
        from tests.test_replan import BASE, revised
        old = schema.validate_plan(BASE)
        runs = {'a': {'state': 'completed'}, 'b': {'state': 'failed'}, 'c': {'state': 'pending'}}
        replan.check_against_runs(runs, old, schema.validate_plan(revised()))                        # the failed phase is switched off and replaced: allowed
        edited = json.loads(json.dumps(BASE)); edited['phases'][0]['description'] = 'rewritten'
        with self.assertRaises(replan.ReplanRefused):
            replan.check_against_runs(runs, old, schema.validate_plan(edited))                       # a finished phase is never changed

    @case('A-OWN-KEY-WAIT')
    def test_the_customers_own_provider_limit_is_waited_for_and_attributed_to_their_provider(self):
        from tests.test_rate_limits import OwnKey
        for name in ('test_their_per_minute_limit_is_waited_for_and_said_to_be_theirs', 'test_their_exhausted_quota_is_passed_on_at_once_and_not_waited_for'):
            check = OwnKey(name)
            check.setUp()
            try:
                getattr(check, name)()
            finally:
                check.doCleanups()


    # -- roadmap Phase 2 and 3: permissions, connected services, the action pipeline, leaving ------------------------------------------------------------
    def _helper(self, cls):
        """A second fixture (its own database) for the cases that need connected services or account jobs."""
        helper = cls('setUp'); helper.setUp(); self.addCleanup(helper.doCleanups)
        return helper

    def _connected(self):
        from tests.connector_fixture import ConnectorBase
        h = self._helper(ConnectorBase)
        return h, h.connect()

    @case('A-GRANT-BOUNDARY')
    def test_a_connection_reaches_only_what_its_customer_chose(self):
        from agentai_platform.connector_kit import ConnectorFault
        h, connection = self._connected()
        h.bench.seed('a', 'inbox', 2); h.bench.seed('a', 'archive', 2, prefix='Hidden')
        self.assertEqual(len(h.client.list(h.a, connection, 'folder', 'inbox')[0]), 2)
        with self.assertRaises(ConnectorFault):
            h.client.list(h.a, connection, 'folder', 'archive')
        self.assertEqual([r for r in h.client.search(h.a, connection, 'Hidden')[0]], [])
        with self.assertRaises(ConnectorFault):
            h.client.list(h.b, connection, 'folder', 'inbox')                                      # and never another account's

    @case('A-PARTIAL-IS-SAID')
    def test_a_partial_result_is_never_presented_as_complete(self):
        from agentai_platform.connector_tools import ConnectorTools
        h, connection = self._connected()
        h.bench.seed('a', 'inbox', 70)
        tools = ConnectorTools(h.store, h.connectors, h.client, h.actions, h.workflows, clock=lambda: h.now, enabled=lambda a: True)
        text, error = tools.call('a', {'connection': connection, 'resource_kind': 'folder', 'resource_id': 'inbox'}, name='lumina_connector_list', request_id='req-a')
        result = json.loads(text)
        self.assertEqual((error, result['complete'], result['count'], result['total_estimate']), (False, False, 50, 70))
        self.assertIn('PARTIAL RESULT', result['result'])

    @case('A-ACTION-EXACT-ONCE')
    def test_an_approved_change_is_sent_once_as_approved_and_checked_even_when_its_answer_is_lost(self):
        h, connection = self._connected()
        payload = {'folder': 'inbox', 'title': 'Plan', 'body': 'Draft'}
        action = h.actions.propose(h.a, connection, 'note.create', payload, request_id='req-a')
        self.assertEqual(h.bench.rows('a'), [])                                                    # preparing sends nothing
        h.actions.approve(h.a, action['id'], action['payload_hash'])
        h.bench.fault('a', 'write', 'silent')                                                      # the write happens and its answer never arrives
        h.runner.tick(); h.runner.tick(); h.runner.tick()
        done = h.actions.get(h.a, action['id'])
        notes = [(r['title'], r['body']) for r in h.bench.rows('a')]
        self.assertEqual((done['state'], done['verified'], notes), ('done', True, [('Plan', 'Draft')]))      # one effect, exactly what was approved, read back

    @case('A-ACTION-CHANGED-PAYLOAD')
    def test_a_change_that_is_no_longer_the_one_approved_is_not_made(self):
        h, connection = self._connected()
        action = h.actions.propose(h.a, connection, 'note.create', {'folder': 'inbox', 'title': 'Plan', 'body': 'Draft'}, request_id='req-a')
        h.actions.approve(h.a, action['id'], action['payload_hash'])
        with h.store.connect() as con:
            con.execute('UPDATE actions SET payload_json=? WHERE id=?', (json.dumps({'folder': 'inbox', 'title': 'Plan', 'body': 'Something else'}), action['id']))
        h.runner.tick()
        self.assertEqual((h.actions.get(h.a, action['id'])['ended_reason'], h.bench.rows('a')), ('payload_changed', []))

    @case('A-ACTION-UNDO')
    def test_a_change_can_be_undone_and_the_undo_is_approved_like_any_change(self):
        h, connection = self._connected()
        done = h.do(connection, 'note.create', {'folder': 'inbox', 'title': 'Plan', 'body': 'Draft'})
        undo = h.actions.undo(h.a, done['id'])
        h.runner.tick()
        self.assertEqual([r['deleted'] for r in h.bench.rows('a')], [0])                           # nothing until the undo itself is approved
        h.actions.approve(h.a, undo['id'], undo['payload_hash']); h.runner.tick()
        self.assertEqual(([r['deleted'] for r in h.bench.rows('a')], h.actions.get(h.a, done['id'])['state']), ([1], 'undone'))

    @case('A-WORKFLOW-WALKBACK')
    def test_a_workflow_that_fails_at_its_last_step_leaves_the_earlier_steps_reversed(self):
        h, connection = self._connected()
        h.bench.seed('a', 'inbox', 1)
        steps = [{'connection_id': connection, 'kind': 'note.create', 'payload': {'folder': 'inbox', 'title': t, 'body': ''}} for t in ('One', 'Two')]
        steps.append({'connection_id': connection, 'kind': 'note.update', 'payload': {'id': 'inbox-0000', 'body': 'x'}})
        workflow = h.workflows.propose(h.a, 'Three steps', steps, request_id='req-a')
        h.workflows.approve(h.a, workflow['id'], workflow['steps_hash'])
        h.bench.edit_elsewhere('a', 'inbox-0000', body='changed by someone else')
        h.runner.tick()
        after = h.workflows.get(h.a, workflow['id'])
        live = [r['title'] for r in h.bench.rows('a') if r['title'] in ('One', 'Two') and not r['deleted']]
        self.assertEqual((after['state'], [r['step'] for r in after['report']['reversed']], live), ('reversed', [2, 1], []))

    @case('A-ROLE-VIEWER')
    def test_a_viewer_cannot_make_the_assistant_act(self):
        from agentai_platform import permissions
        from agentai_platform.tool_relay import ToolPermit
        h, connection = self._connected()
        h.orgs.add_member(h.a, 'b', 'actor-b', 'viewer')
        with h.store.connect() as con:
            self.assertEqual((permissions.may(con, 'b', 'actor-b', 'task.run'), permissions.may(con, 'b', 'actor-b', 'conversation.read')), (False, True))
        self.assertIn('not allowed', ToolPermit(h.store).refusal('b', 'req-b', 'lumina_browser'))

    @case('A-OFFBOARD-CLEAN')
    def test_a_closed_account_leaves_only_what_stays_by_design(self):
        from agentai_platform.data_lifecycle import KEPT_AT_DELETION, _tables_with_account
        from tests.test_data_lifecycle import Base as LifecycleBase
        h = self._helper(LifecycleBase)
        h.jobs.cooling_off = 0
        h.jobs.start_offboarding(h.a); h.jobs.choose_export(h.a, False)
        for _ in range(8):
            h.jobs.tick()
        with h.store.connect() as con:
            left = {t for t in _tables_with_account(con) if con.execute(f'SELECT 1 FROM "{t}" WHERE account_id=?', ('a',)).fetchone()}
            job = con.execute("SELECT state,report_json FROM account_jobs WHERE account_id='a' AND kind='deletion'").fetchone()
            other = con.execute("SELECT count(*) FROM chat_messages WHERE account_id='b'").fetchone()[0]
        self.assertEqual((job['state'], json.loads(job['report_json'])['verification']['clean'], left - set(KEPT_AT_DELETION), other), ('completed', True, set(), 1))


class RunnerChecks(unittest.TestCase):
    """deploy/acceptance.py: what makes a deploy refuse."""
    def runner(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('acceptance_runner', Path(__file__).resolve().parents[1] / 'deploy' / 'acceptance.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_a_case_that_passed_before_and_fails_now_is_a_regression_and_a_missing_case_is_lost(self):
        compare = self.runner().compare
        before = {'cases': {'A-ONE': {'passed': True}, 'A-TWO': {'passed': True}, 'A-OLD-FAIL': {'passed': False}, 'A-GONE': {'passed': True}}}
        now = {'A-ONE': {'passed': True}, 'A-TWO': {'passed': False}, 'A-OLD-FAIL': {'passed': False}, 'A-NEW': {'passed': False}}
        self.assertEqual(compare(now, before), (['A-TWO'], ['A-GONE']))          # a new failing case and a long-failing one are failures, not regressions
        self.assertEqual(compare(now, {}), ([], []))

    def test_the_committed_baseline_lists_exactly_the_cases_that_exist(self):
        from pathlib import Path
        baseline = json.loads((Path(__file__).resolve().parent / 'acceptance_baseline.json').read_text())
        self.assertEqual(sorted(baseline['cases']), sorted(CASES), 'run: python deploy/acceptance.py run --write-baseline tests/acceptance_baseline.json')


CASES = {getattr(Acceptance, name).CASE: name for name in dir(Acceptance) if hasattr(getattr(Acceptance, name), 'CASE')}

if __name__ == '__main__':
    unittest.main()
