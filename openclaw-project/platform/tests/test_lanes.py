"""Roadmap #10: phases of a plan that do not depend on each other run at the same time, each in its own lane (a hidden child conversation with its own runtime session), under the
account's background slots, with exact accounting and without changing what the customer sees of their chats."""
import json
import threading
import unittest

from agentai_platform.chat_driver import ChatDriver, synthetic_gateway_factory
from agentai_platform.genui import runner as runner_mod
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.request_queue import BACKGROUND_PER_ACCOUNT
from agentai_platform.request_worker import RequestWorker
from tests import test_genui as G
from tests.test_genui import OK, phase, plan

DIAMOND = plan(phase('a'), phase('b'), phase('c', deps=['a', 'b']))
FOUR = plan(phase('a'), phase('b'), phase('c'), phase('d'), phase('e', deps=['a', 'b', 'c', 'd']))


class Lanes(unittest.TestCase):
    setUp, rows, make_plan_block, phases = G.FlowChecks.setUp, G.FlowChecks.rows, G.FlowChecks.make_plan_block, G.FlowChecks.phases

    def worker(self, parallel=4, **kw):
        self.gw.script = lambda message, run, gw: {'text': 'done'}
        driver = ChatDriver(self.store, ledger=self.ledger, gateway_factory=synthetic_gateway_factory(self.gw), clock=lambda: self.now, genui=GenUiRuntime(self.store, self.chat.blocks),
                            heartbeat=self.queue.heartbeat, **kw)
        return RequestWorker(self.queue, driver, lambda: OK, clock=lambda: self.now, runner=self.chat.runner, max_parallel=parallel)

    def settle(self, worker, rounds=12):
        for _ in range(rounds):
            worker.tick(); worker.wait_idle(15)

    def test_independent_phases_start_together_the_first_in_the_plans_chat_and_the_rest_in_lanes(self):
        block = self.make_plan_block(DIAMOND)
        self.chat.launch_plan(self.a, block['id'], 1)
        self.assertEqual(self.phases(block['id']), {'a': 'running', 'b': 'running', 'c': 'pending'})
        where = {r['phase_id']: r['conversation_id'] for r in self.rows('SELECT phase_id,conversation_id FROM plan_phase_runs WHERE block_id=?', (block['id'],))}
        self.assertEqual(where['a'], 'c-a')
        lane = where['b']
        self.assertNotEqual(lane, 'c-a')
        self.assertEqual(self.rows('SELECT parent_id FROM conversations WHERE id=?', (lane,))[0]['parent_id'], 'c-a')
        self.assertEqual(self.chat.blocks.get(self.a, block['id'])['why_waiting'], {'c': {'reason': 'prerequisites', 'on': ['a', 'b']}})

    def test_both_run_at_the_same_moment_on_separate_sessions_then_the_join_runs_and_the_plan_completes(self):
        block = self.make_plan_block(DIAMOND)
        self.chat.launch_plan(self.a, block['id'], 1)
        meeting = threading.Barrier(2, timeout=10)
        seen = set()
        def at_wait(run):
            if run['id'] in seen:
                return
            seen.add(run['id']); meeting.wait()                  # both phases must be inside wait() together
        self.gw.on_wait = at_wait
        worker = self.worker()
        report = worker.tick()
        self.assertEqual(report.get('started'), 2)
        self.assertEqual(sorted(r['kind'] for r in self.rows('SELECT kind FROM request_slots')), ['background', 'interactive'])
        self.assertTrue(worker.wait_idle(20))
        self.gw.on_wait = None
        self.settle(worker)
        self.assertEqual(self.phases(block['id']), {'a': 'completed', 'b': 'completed', 'c': 'completed'})
        self.assertEqual(self.chat.blocks.get(self.a, block['id'])['run_status'], 'completed')
        self.assertEqual(len({s['native_session_ref'] for s in self.rows('SELECT native_session_ref FROM conversations WHERE account_id=?', ('a',)) if s['native_session_ref']}), 2)
        self.assertEqual(self.rows('SELECT count(*) AS n FROM request_slots')[0]['n'], 0)
        self.assertEqual(worker._errors, [])

    def test_lanes_stay_hidden_and_a_phase_shows_in_the_chat_it_belongs_to(self):
        block = self.make_plan_block(DIAMOND)
        self.chat.launch_plan(self.a, block['id'], 1)
        listed = [c['id'] for c in self.chat.conversations(self.a)]
        self.assertEqual(listed, ['c-a'])                                                    # the lane is not a chat the customer has
        from agentai_platform.work import WorkReader
        tasks = WorkReader(self.store).listing(self.a)['tasks']
        self.assertEqual(len(tasks), 2)
        self.assertEqual({t['conversation_id'] for t in tasks}, {'c-a'})                       # both phases belong, for the customer, to the plan's own chat

    def test_no_more_than_three_phases_run_at_once_and_the_join_waits_for_all_of_them(self):
        block = self.make_plan_block(FOUR)
        self.chat.launch_plan(self.a, block['id'], 1)
        running = sorted(k for k, v in self.phases(block['id']).items() if v == 'running')
        self.assertEqual(len(running), runner_mod.MAX_PARALLEL_PHASES)
        self.assertEqual(self.phases(block['id'])['e'], 'pending')
        worker = self.worker(); self.settle(worker, 20)
        self.assertEqual(set(self.phases(block['id']).values()), {'completed'})
        lanes = self.rows('SELECT id FROM conversations WHERE parent_id=?', ('c-a',))
        self.assertLessEqual(len(lanes), runner_mod.MAX_LANES)                                 # lanes are reused, never piled up

    def test_background_slots_are_capped_per_account(self):
        self.assertEqual(BACKGROUND_PER_ACCOUNT, 2)
        block = self.make_plan_block(FOUR)
        self.chat.launch_plan(self.a, block['id'], 1)
        claims = [self.queue.claim(owner='w', capacity=OK) for _ in range(5)]
        self.assertEqual(sum(c is not None for c in claims), 3)                                # one interactive + two background
        self.assertEqual(sorted(r['kind'] for r in self.rows('SELECT kind FROM request_slots')), ['background', 'background', 'interactive'])

    def test_a_plan_without_dependencies_still_runs_one_phase_at_a_time_in_order(self):
        block = self.make_plan_block(plan(phase('a'), phase('b'), phase('c')))
        self.chat.launch_plan(self.a, block['id'], 1)
        self.assertEqual(self.phases(block['id']), {'a': 'running', 'b': 'pending', 'c': 'pending'})
        self.assertEqual(self.rows('SELECT count(*) AS n FROM conversations WHERE parent_id IS NOT NULL')[0]['n'], 0)

    def test_the_customer_can_still_chat_while_phases_run_in_lanes(self):
        block = self.make_plan_block(DIAMOND)
        self.chat.launch_plan(self.a, block['id'], 1)
        with self.store.connect() as con:                                                       # the plan's chat is busy (phase a); the customer asks something in a second chat
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p-a','c-other','d-a')")
        asked = self.chat.send(self.a, conversation_id='c-other', message='what time is it', key='k-other')
        first = self.queue.claim(owner='w', capacity=OK); second = self.queue.claim(owner='w', capacity=OK); third = self.queue.claim(owner='w', capacity=OK)
        got = {c.conversation_id for c in (first, second, third) if c}
        self.assertIn('c-a', got)
        self.assertEqual(len([c for c in (first, second, third) if c]), 2)                      # the plan's chat is one interactive slot, so the customer's chat waits; the lane runs
        self.assertEqual(self.rows('SELECT state FROM customer_requests WHERE id=?', (asked['request']['id'] if 'request' in asked else asked['id'],))[0]['state'], 'waiting')

    def test_stopping_the_plan_stops_every_running_phase_including_those_in_lanes(self):
        block = self.make_plan_block(DIAMOND)
        self.chat.launch_plan(self.a, block['id'], 1)
        self.chat.runner.stop(self.a, block['id'])
        states = {r['phase_id']: self.rows('SELECT cancel_requested FROM customer_requests WHERE id=?', (r['request_id'],))[0]['cancel_requested']
                  for r in self.rows("SELECT phase_id,request_id FROM plan_phase_runs WHERE block_id=? AND request_id IS NOT NULL", (block['id'],))}
        self.assertEqual(states, {'a': 1, 'b': 1})


if __name__ == '__main__':
    unittest.main()
