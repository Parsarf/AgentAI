"""Real queue/task events behind the agent's scoped progress tool."""
import copy
from agentai_platform.task_progress import TaskProgressTool, TOOL_NAME
from agentai_platform.tool_relay import Relay
from agentai_platform.genui.prompts import progress_prompt, phase_prompt
from .test_native_run import Base, OK


def step(sid, status='running', **kw):
    return {'id': sid, 'title': sid.title(), 'status': status, **kw}


class ProgressChecks(Base):
    def setUp(self):
        super().setUp()
        self.request = self.chat.send(self.a, conversation_id='c-a', message='Do some work', key='p1')
        self.claim = self.queue.claim(owner='w', capacity=OK)
        self.tool = TaskProgressTool(self.store)

    def update(self, steps, revision=0, key='u1', mode='direct', account='a', task=None):
        return self.tool.call(account, {'task_id': task or self.request['id'], 'revision': revision, 'update_id': key, 'mode': mode, 'steps': steps})

    def snapshots(self):
        return self.tool.events.events(self.a, self.request['id'])['events']

    def test_direct_execution_adds_actual_steps_without_a_plan_and_is_durable(self):
        self.assertFalse(self.update([step('read')])[1])
        self.assertFalse(self.update([step('read', 'done'), step('write')], 1, 'u2')[1])
        self.assertFalse(self.update([step('read', 'done'), step('write', 'done')], 2, 'u3')[1])
        saved = self.snapshots()[-1]['payload']
        self.assertEqual((saved['mode'], saved['revision']), ('direct', 3))
        self.assertEqual([s['status'] for s in saved['steps']], ['done', 'done'])
        # Display updates neither create plan approval nor settle the running request.
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT state FROM customer_requests WHERE id=?', (self.request['id'],)).fetchone()[0], 'starting')
            self.assertEqual(con.execute('SELECT count(*) FROM plan_phase_runs').fetchone()[0], 0)

    def test_plan_requires_concrete_checkpoints_and_explicit_results_before_advancing(self):
        steps = [step('inspect', checkpoint='Requirements confirmed'), step('build', 'pending', checkpoint='Checks pass')]
        reply, error = self.update(steps, mode='plan')
        self.assertFalse(error); self.assertIn('- [running] inspect', reply); self.assertIn('Checkpoint: Checks pass', reply)
        bad = copy.deepcopy(steps); bad[0]['status'] = 'done'; bad[1]['status'] = 'running'
        self.assertTrue(self.update(bad, 1, 'u2', 'plan')[1])
        bad[0]['result'] = 'Confirmed the requested behavior'
        self.assertFalse(self.update(bad, 1, 'u2', 'plan')[1])
        bad[1].update(status='done', result='Required checks passed')
        self.assertFalse(self.update(bad, 2, 'u3', 'plan')[1])
        missing = [step('inspect')]
        self.assertTrue(self.update(missing, 2, 'u3', 'plan')[1])

    def test_failures_are_not_completion_and_retries_preserve_history(self):
        self.update([step('check')])
        self.assertFalse(self.update([step('check', 'failed', result='Test failed')], 1, 'u2')[1])
        self.assertTrue(self.update([step('check', 'done')], 2, 'u3')[1])
        self.assertFalse(self.update([step('check', result='Retrying test')], 2, 'u3')[1])
        self.assertFalse(self.update([step('check', 'done', result='Test passed')], 3, 'u4')[1])
        self.assertTrue(self.update([step('check')], 4, 'u5')[1])

    def test_stale_duplicate_foreign_cancelled_and_unknown_updates(self):
        initial = [step('read')]; self.update(initial)
        self.assertFalse(self.update(initial)[1])
        self.assertEqual(len([e for e in self.snapshots() if e['kind'] == 'task_steps']), 1)
        self.assertTrue(self.update([step('write')])[1])
        self.assertTrue(self.update(initial, 0, 'new')[1])
        self.assertTrue(self.update(initial, 1, 'u2', account='b')[1])
        self.assertTrue(self.update(initial, 1, 'u2', task='other')[1])
        self.queue.cancel(self.a, self.request['id'])
        self.assertTrue(self.update(initial, 1, 'u2')[1])

    def test_invalid_sequential_updates_and_payload_bounds(self):
        for steps in ([step('a'), step('b')], [step('a', 'pending')], [step('a', 'done')], [step('a', status=[])], [step('a', title='x'*101)]):
            self.assertTrue(self.update(steps)[1], steps)
        self.assertTrue(self.update([step('a', 'pending', checkpoint='A'), step('b', checkpoint='B')], mode='plan')[1])
        self.assertTrue(self.tool.call('a', {'task_id': self.request['id'], 'account': 'b'})[1])

    def test_native_goal_can_discover_its_task_without_rewriting_the_objective(self):
        current, error = self.tool.call('a', {})
        self.assertFalse(error); self.assertIn(self.request['id'], current)
        self.assertIn('"revision": 0', current)
        self.assertTrue(self.tool.call('b', {})[1])
        self.update([step('read')])
        self.assertIn('"revision": 1', self.tool.call('a', {})[0])

    def test_relay_discovers_and_dispatches_progress_independently_of_browser(self):
        browser = type('Browser', (), {'call': lambda *_a, **_k: self.fail('Browser must not run')})()
        relay = Relay(browser, progress=self.tool)
        listed = relay.handle('a', {'id': 1, 'method': 'tools/list'})['result']['tools']
        self.assertIn(TOOL_NAME, [t['name'] for t in listed])
        out = relay.handle('a', {'id': 2, 'method': 'tools/call', 'params': {'name': TOOL_NAME, 'arguments': {
            'task_id': self.request['id'], 'revision': 0, 'update_id': 'u1', 'mode': 'direct', 'steps': [step('read')]}}})
        self.assertFalse(out['result']['isError'])

    def test_driver_prompts_runtime_to_choose_execution_or_checkpoints(self):
        info = self.driver._admit(self.claim)
        outgoing = self.driver._outgoing(self.claim, info)
        self.assertIn(self.request['id'], outgoing)
        self.assertIn('do not stop to offer Plan mode', outgoing)
        self.assertIn('checkpoint', outgoing)
        from agentai_platform.genui.schema import validate_plan
        plan = validate_plan({'schemaVersion': '1.0', 'type': 'task_plan', 'title': 'Fix', 'phases': [dict(id='fix', title='Fix', description='Make the change', checkpoint='Tests pass')]})
        text = phase_prompt(plan, None, [], plan['phases'][0], 1, 1)
        self.assertIn('- fix: Fix — Checkpoint: Tests pass', text)
        self.assertIn('Checkpoint for this phase: Tests pass', text)
