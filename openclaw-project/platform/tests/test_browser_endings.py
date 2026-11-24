"""Why a browser job ended (reliability plan, Part 3, browser): the reason is a registered code, given where the ending is decided (the loop, the service, the tool that
follows the job), carried with the job's last status, and used as it is by the tool's reply, the task's reason and the task's sentence. A Python exception's name is a
fact for the owner beside the reason, never part of what a customer reads."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from agentai_platform import faults, outcome
from agentai_platform.browse import job_states, service as svc
from agentai_platform.browse.adapter import BrowserTool, is_refused, is_wall
from agentai_platform.browse.loop import REFUSED_REASON, WALL_REASON
from agentai_platform.faults_registry import REASONS
from tests.test_browse_service import RID, FakeTransport, ScriptedService, llm_for, wait
from tests.test_browser_tool import FakeBrowse
from tests.test_native_run import OK, Base

BROWSE = Path(svc.__file__).parent


class Registered(unittest.TestCase):
    def test_every_code_the_browser_gives_is_registered_and_is_the_browser_s(self):
        given = set(job_states.END_CODES.values())
        for module in ('loop.py', 'service.py'):
            given |= set(re.findall(r"code='(browser\.[a-z_]+)'", (BROWSE / module).read_text())) | set(re.findall(r"'(browser\.[a-z_]+)'", (BROWSE / module).read_text()))
        self.assertGreaterEqual(len(given), 16)
        self.assertEqual(sorted(given - set(REASONS)), [])
        self.assertEqual(set(job_states.END_CODES), set(job_states.FINAL) - {'done'} | {'failed'})      # every ending but `done` has a code when nothing more exact is known

    def test_no_reason_a_customer_reads_carries_an_exception_s_name(self):
        for module in ('loop.py', 'service.py', 'adapter.py'):
            source = (BROWSE / module).read_text()
            self.assertEqual(re.findall(r"reason\s*=[^\n]*__name__|job\.reason[^\n]*__name__", source), [], module)
        for code, spec in REASONS.items():
            if code.startswith('browser.'):
                self.assertNotRegex(spec.customer, r'Error\b|Exception')

    def test_a_named_stop_that_is_the_site_s_or_the_customer_s_is_not_an_error(self):
        for code in ('browser.site_refused', 'browser.human_check', 'browser.needs_customer', 'browser.question_unanswered', 'browser.spending_limit', 'browser.site_not_allowed',
                     'browser.stopped_with_task'):
            self.assertTrue(REASONS[code].expected, code)
        for code in ('browser.page_timeout', 'browser.page_would_not_open', 'browser.runner_crashed', 'browser.stuck', 'browser.deadline', 'browser.max_steps', 'browser.failed'):
            self.assertFalse(REASONS[code].expected, code)
        self.assertEqual((REASONS['browser.runner_crashed'].actor, REASONS['browser.runner_crashed'].alert), ('owner', True))
        self.assertFalse(REASONS['browser.page_timeout'].alert)                               # a slow site is not Lumina's to fix


class Service(unittest.TestCase):
    """The browse service itself, with a scripted stage: what a poll and the job's last status say when it ends."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def make(self, script=(), spawn=None, **kw):
        stage = kw.pop('transport_kw', {})
        return ScriptedService(spawn=spawn or (lambda job, out: FakeTransport(out, **stage)), llm_for=llm_for(list(script)), root=self.tmp.name, jev_mode='off',
                               takeover_seconds=kw.pop('takeover_seconds', 5), **kw)

    def ended(self, service, goal='goal at https://shop.example/', states=svc.FINAL):
        service.start('acct', RID, goal)
        polled = wait(service, states)
        last = [e for e in polled['events'] if e['kind'] == 'status' and e.get('state') == polled['state']][-1]
        return polled, last

    def test_a_crash_is_named_for_the_customer_and_its_type_and_place_are_facts_beside_it(self):
        def spawn(job, out):
            raise KeyError('Dear Parsa, order 7781 at shop.example/account?token=abc')
        polled, last = self.ended(self.make(spawn=spawn))
        self.assertEqual((polled['state'], polled['reason'], polled['code']), ('error', 'the browser run failed', 'browser.runner_crashed'))
        self.assertEqual(polled['exception'], 'KeyError'); self.assertRegex(polled['where'], r'^[a-z_]+\.py:\d+$')
        self.assertEqual({k: last[k] for k in ('state', 'reason', 'code', 'exception')}, {'state': 'error', 'reason': 'the browser run failed', 'code': 'browser.runner_crashed', 'exception': 'KeyError'})
        self.assertNotIn('7781', json.dumps(polled)); self.assertNotIn('token', json.dumps(polled))
        fault = faults.of_browser_job(polled['state'], polled['reason'], polled['code'], exception=polled['exception'], where=polled['where'])
        self.assertEqual((fault.reason, fault.detail), ('browser.runner_crashed', {'state': 'error', 'exception': 'KeyError', 'where': polled['where']}))

    def test_a_browser_that_did_not_answer_in_time_is_the_page_s_timeout_not_a_crash(self):
        def spawn(job, out):
            raise TimeoutError('runner did not answer in time')
        polled, last = self.ended(self.make(spawn=spawn))
        self.assertEqual((polled['state'], polled['code'], polled['exception']), ('error', 'browser.page_timeout', 'TimeoutError'))
        self.assertEqual(polled['reason'], 'the page did not answer in time, so the browser stopped')
        self.assertEqual(last['code'], 'browser.page_timeout')

    def test_a_stage_that_never_answers_ends_with_a_reason_of_its_own(self):
        polled, last = self.ended(self.make(transport_kw={'hang': True}), states=('error',))
        self.assertIn(polled['code'], ('browser.page_would_not_open', 'browser.page_timeout'))
        self.assertEqual(last['code'], polled['code']); self.assertNotIn('TimeoutError', polled['reason'])

    def test_a_busy_server_a_missing_address_and_a_site_that_is_not_allowed(self):
        busy, _ = self.ended(self.make(free_memory=lambda: 0, sleep=lambda s: None), states=('error',))
        self.assertEqual(busy['code'], 'browser.server_busy')
        nowhere, last = self.ended(self.make(), goal='find the opening hours', states=('error',))
        self.assertEqual((nowhere['code'], last['code']), ('browser.no_start_page', 'browser.no_start_page')); self.assertNotIn('exception', nowhere)
        denied, _ = self.ended(self.make(), goal='log in at https://www.paypal.com/ please', states=svc.FINAL)
        self.assertEqual((denied['state'], denied['code']), ('blocked', 'browser.site_not_allowed'))

    def test_a_job_that_needs_the_customer_and_one_that_was_stopped(self):
        handed, last = self.ended(self.make(['{"action":"click","ref":2}', '{"action":"click","ref":1}']), states=('handoff',))
        self.assertEqual((handed['code'], last['code']), ('browser.needs_customer', 'browser.needs_customer'))
        gate = __import__('threading').Event()
        stopped = ScriptedService(spawn=lambda job, out: FakeTransport(out), llm_for=llm_for(['{"action":"click","ref":2}']), gate=gate, root=self.tmp.name, jev_mode='off')
        stopped.start('acct', 'b' * 32, 'goal at https://shop.example/')
        wait(stopped, ('running',), rid='b' * 32); stopped.cancel('acct', 'b' * 32); gate.set()
        self.assertEqual(wait(stopped, ('cancelled',), rid='b' * 32)['code'], 'browser.stopped_with_task')


class Platform(Base):
    """What Lumina's side does with the code: the tool's reply, the task's reason and the task's sentence."""
    ARGS = {'task': 'Add the spiciest chicken wings to the cart on Uber Eats', 'site': 'ubereats.com'}

    def setUp(self):
        super().setUp()
        self.request = self.chat.send(self.a, conversation_id='c-a', message='Do some work', key='p1')
        self.claim = self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='running' WHERE id=?", (self.request['id'],))
        self.rpc = FakeBrowse()
        self.tool = BrowserTool(self.store, browse_factory=lambda account: self.rpc, clock=lambda: self.now, sleep=lambda s: None, poll_interval=0)

    def call(self, final):
        with self.store.connect() as con:                         # each case is a browser call of its own: one request may not try the browser again after two failures
            for table in ('browse_steps', 'browse_sessions', 'browse_runs'):
                con.execute(f'DELETE FROM {table} WHERE account_id=? AND request_id=?', ('a', self.request['id']))
        self.rpc.script = [{'answer': None, 'url': 'https://x/', 'cost_microusd': 0, 'events': [{'n': 1, 'kind': 'status', **{k: final[k] for k in ('state', 'reason', 'code', 'exception', 'where') if k in final}}], **final}]
        return self.tool.call('a', self.ARGS, request_id=self.request['id'])

    def test_each_ending_reaches_the_assistant_with_its_reason_and_only_a_failure_as_an_error(self):
        endings = (
            ({'state': 'error', 'reason': 'the browser run failed', 'code': 'browser.runner_crashed', 'exception': 'KeyError', 'where': 'session.py:96'}, 'browser.runner_crashed', True),
            ({'state': 'error', 'reason': 'the page did not answer in time, so the browser stopped', 'code': 'browser.page_timeout', 'exception': 'TimeoutError'}, 'browser.page_timeout', True),
            ({'state': 'error', 'reason': 'could not open the page (action_failed)', 'code': 'browser.page_would_not_open'}, 'browser.page_would_not_open', True),
            ({'state': 'stuck', 'reason': 'the page did not finish loading', 'code': 'browser.page_timeout'}, 'browser.page_timeout', True),
            ({'state': 'stuck', 'reason': 'repeating the same step', 'code': 'browser.stuck'}, 'browser.stuck', True),
            ({'state': 'max_steps', 'reason': 'step limit reached', 'code': 'browser.max_steps'}, 'browser.max_steps', True),
            ({'state': 'deadline', 'reason': 'time limit reached', 'code': 'browser.deadline'}, 'browser.deadline', True),
            ({'state': 'blocked', 'reason': REFUSED_REASON, 'code': 'browser.site_refused'}, 'browser.site_refused', False),
            ({'state': 'blocked', 'reason': 'that site is not allowed', 'code': 'browser.site_not_allowed'}, 'browser.site_not_allowed', False),
            ({'state': 'handoff', 'reason': WALL_REASON, 'code': 'browser.human_check'}, 'browser.human_check', False),
            ({'state': 'handoff', 'reason': 'reached a payment step; you take it from here', 'code': 'browser.needs_customer', 'pending_action': {'label': 'Pay'}}, 'browser.needs_customer', False),
            ({'state': 'stopped', 'reason': 'no answer to the question', 'code': 'browser.question_unanswered'}, 'browser.question_unanswered', False),
            ({'state': 'budget', 'reason': 'stopped: the spending limit was reached', 'code': 'browser.spending_limit'}, 'browser.spending_limit', False),
            ({'state': 'cancelled', 'reason': 'stopped by you', 'code': 'browser.stopped_with_task'}, 'browser.stopped_with_task', False),
        )
        for final, reason, error in endings:
            with self.subTest(reason=reason, state=final['state']):
                text, why = self.call(final)
                self.assertEqual((why.reason, faults.is_error(why)), (reason, error))
                self.assertIn('Status: did not finish', text)
                self.assertNotIn('KeyError', text); self.assertNotIn('TimeoutError', text)
        self.assertEqual(why.detail, {'state': 'cancelled'})
        text, why = self.call({'state': 'done', 'reason': '', 'code': '', 'answer': 'The wings are in the cart.'})
        self.assertIs(why, False); self.assertIn('Status: completed', text)
        text, why = self.call({'state': 'cancelled', 'reason': job_states.RELEASED_REASON, 'code': 'browser.stopped_with_task'})
        self.assertIs(why, False)                                                             # a page the assistant went on without is not a failure of anything

    def test_a_crash_keeps_its_type_and_place_as_facts_with_the_task_s_reason(self):
        self.call({'state': 'error', 'reason': 'the browser run failed', 'code': 'browser.runner_crashed', 'exception': 'KeyError', 'where': 'session.py:96'})
        jobs, _ = self.driver._browser_evidence(self.claim)
        self.assertEqual(jobs[-1], {'state': 'error', 'url': 'https://x/', 'reason': 'the browser run failed', 'code': 'browser.runner_crashed', 'exception': 'KeyError', 'where': 'session.py:96'})
        fault = faults.of_finished_run('partial', jobs=jobs)
        self.assertEqual((fault.reason, fault.kind, fault.actor, fault.alert), ('browser.runner_crashed', 'internal', 'owner', True))
        self.assertEqual(fault.detail, {'state': 'error', 'exception': 'KeyError', 'where': 'session.py:96'})

    def test_the_task_s_sentence_is_the_reason_s_and_the_same_one_the_step_shows(self):
        self.call({'state': 'stuck', 'reason': 'the page did not finish loading', 'code': 'browser.page_timeout'})
        jobs, steps = self.driver._browser_evidence(self.claim)
        verdict = outcome.judge(native={'status': 'ok'}, jobs=jobs, steps=steps)
        self.assertEqual((verdict.outcome, verdict.note), ('partial', REASONS['browser.page_timeout'].customer))
        self.assertEqual(verdict.line, 'Stopped: the page did not answer in time, so the browser stopped. What it had done up to then is kept.')
        refused = outcome.judge(native={'status': 'ok'}, jobs=[{'state': 'blocked', 'reason': REFUSED_REASON, 'code': 'browser.site_refused'}])
        self.assertEqual((refused.outcome, refused.note), ('blocked', REASONS['browser.site_refused'].customer))
        wall = outcome.judge(native={'status': 'ok'}, jobs=[{'state': 'handoff', 'reason': 'anything', 'code': 'browser.human_check'}])
        self.assertEqual(wall.outcome, 'blocked')                                             # by the code, whatever the sentence says

    def test_a_record_from_before_the_browser_gave_codes_reads_as_it_did(self):
        old = outcome.judge(native={'status': 'ok'}, jobs=[{'state': 'stuck', 'reason': 'repeating the same step'}])
        self.assertEqual((old.note, old.line), ('The browser got stuck repeating the same step.', 'Stopped: the browser got stuck repeating the same step.'))
        self.assertEqual(faults.of_browser_job('error', 'the browser run failed (TimeoutError)').detail, {'state': 'error', 'exception': 'TimeoutError'})
        self.assertEqual(faults.of_browser_job('stuck', 'x', 'not.a.code').reason, 'browser.stuck')       # a code nobody registered is not trusted
        self.assertEqual(faults.of_browser_job('stuck', 'x', 'model.rate_limited').reason, 'browser.stuck')  # nor one that is not the browser's
        for state, words in outcome.BROWSER_WORDS.items():                                    # the two tables say the same thing for every state
            self.assertEqual(REASONS[job_states.END_CODES[state]].customer, words[0].upper() + words[1:] + '.')

    def test_a_wall_and_a_refusal_are_known_by_their_code(self):
        self.assertTrue(is_wall({'state': 'handoff', 'reason': 'reworded later', 'code': 'browser.human_check'}))
        self.assertTrue(is_refused({'state': 'blocked', 'reason': 'reworded later', 'code': 'browser.site_refused'}))
        self.assertTrue(is_wall({'state': 'handoff', 'reason': WALL_REASON}))                 # and still by the sentence, for a job that has no code
        self.assertFalse(is_wall({'state': 'handoff', 'reason': 'reached a payment step', 'code': 'browser.needs_customer'}))

    def test_a_job_the_tool_gave_up_on_keeps_its_code_in_the_record(self):
        from agentai_platform.browse.client import BrowseJobUnknown
        self.rpc.script = [BrowseJobUnknown('gone')]
        text, why = self.tool.call('a', self.ARGS, request_id=self.request['id'])
        self.assertEqual((why.reason, why.alert), ('browser.interrupted', True))
        jobs, _ = self.driver._browser_evidence(self.claim)
        self.assertEqual((jobs[-1]['state'], jobs[-1]['code']), ('interrupted', 'browser.interrupted'))


if __name__ == '__main__':
    unittest.main()
