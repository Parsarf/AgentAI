"""When only the customer can do the next thing (a sign-in, a password, a human check), the run waits for them and carries on afterwards.
Before: the run ended in a final 'handoff' state, the Live view only offered 'End browser session', and nothing ever went back to the agent."""
import tempfile
import threading
import time
import unittest

from agentai_platform.browse import service as svc
from agentai_platform.browse.ladder import Ladder
from agentai_platform.browse.loop import BrowseRunner, MAX_HANDOFFS, Policy
from tests.test_browse import FakeSession, scripted_llm
from tests.test_browse_service import FakeTransport, RID, ScriptedService, llm_for, wait

LOGIN = {'start': {'url': 'https://shop.example/signin', 'snap': '[1] <input type=text> "Email"\n[2] <input type=password> "Password"\n[3] <button> "Continue"', 'text': 'Sign in', 'go': {}},
         'home': {'url': 'https://shop.example/orders', 'snap': '[1] <a> "Order 1001"', 'text': 'Your orders'}}
WALL = {'start': {'url': 'https://food.example/', 'snap': '', 'text': 'Just a moment...'},
        'home': {'url': 'https://food.example/menu', 'snap': '[1] <a> "Burger"', 'text': 'Menu'}}


class Gate:
    """A stand-in for the service's hand gate: records why the run is waiting, optionally lets the customer 'do it' (move the page on), and answers with `outcome`."""
    def __init__(self, session, outcome='resumed', moves_on=True):
        self.session, self.outcome, self.moves_on, self.calls = session, outcome, moves_on, []

    def __call__(self, reason, probe=None, still_blocked=None):
        self.calls.append((reason, still_blocked is not None))
        if self.moves_on:
            self.session.at = 'home'
        return self.outcome, 7


def run(pages, gate_for, llm=None, **kw):
    s = FakeSession(pages)
    gate = gate_for(s)
    llm = llm or scripted_llm(['{"action":"done","answer":"all set"}'])
    r = BrowseRunner(s, Ladder(agent=llm), max_steps=6, wait=lambda n: None, hand_gate=gate, **kw).run('check my orders', pages['start']['url'])
    return r, gate, llm, s


class LoopWaitsForTheCustomer(unittest.TestCase):
    def test_a_sign_in_page_waits_and_the_run_carries_on_with_the_page_after_it(self):
        r, gate, llm, s = run(LOGIN, Gate)
        self.assertEqual((r.status, r.answer), ('done', 'all set'))
        self.assertEqual(len(gate.calls), 1); self.assertIn('sign in', gate.calls[0][0].lower()); self.assertTrue(gate.calls[0][1])     # waits, and can tell by itself when the page moved on
        self.assertEqual(llm.calls, ['agent'])                                                                                         # only the page after sign-in reached the assistant
        self.assertIn(('handoff', 'the customer did it in the browser'), [(h['action'], h['note']) for h in r.steps])

    def test_a_human_check_waits_the_same_way(self):
        r, gate, llm, s = run(WALL, Gate)
        self.assertEqual(r.status, 'done'); self.assertIn('verify you are human', gate.calls[0][0]); self.assertEqual(llm.calls, ['agent'])

    def test_a_wait_that_runs_out_ends_the_run_as_before(self):
        r, gate, llm, s = run(LOGIN, lambda s: Gate(s, outcome='timeout', moves_on=False))
        self.assertEqual(r.status, 'handoff'); self.assertIn('sign in', r.reason); self.assertEqual(llm.calls, [])

    def test_stopping_the_task_during_the_wait_ends_it_as_cancelled(self):
        s = FakeSession(LOGIN); stop = []
        def cancelled_gate(reason, probe=None, still_blocked=None):
            stop.append(1); return 'cancelled', 1
        r = BrowseRunner(s, Ladder(agent=scripted_llm([])), max_steps=4, wait=lambda n: None, hand_gate=cancelled_gate, cancelled=lambda: bool(stop)).run('g', LOGIN['start']['url'])
        self.assertEqual(r.status, 'cancelled')

    def test_a_page_that_stays_blocked_is_waited_for_a_few_times_and_then_the_run_ends(self):
        r, gate, llm, s = run(LOGIN, lambda s: Gate(s, moves_on=False))
        self.assertEqual(len(gate.calls), MAX_HANDOFFS); self.assertEqual(r.status, 'handoff'); self.assertEqual(llm.calls, [])

    def test_without_a_gate_nothing_changes(self):
        r = BrowseRunner(FakeSession(LOGIN), Ladder(agent=scripted_llm([])), max_steps=3, wait=lambda n: None).run('g', LOGIN['start']['url'])
        self.assertEqual(r.status, 'handoff')

    def test_the_saved_login_is_offered_once_not_every_time_the_page_comes_back(self):
        asked = []
        item = {'id': 'l1', 'kind': 'login', 'label': 'Login for shop.example', 'site': 'shop.example'}
        def ask_gate(q, step):
            asked.append(q['title']); return {'option': 'o2'}, 0          # "I will do it myself"
        r, gate, llm, s = run(LOGIN, lambda s: Gate(s, moves_on=False), vault=[item], ask_gate=ask_gate)
        self.assertEqual(len(asked), 1)


class ServiceGate(unittest.TestCase):
    """The real gate: the job stays alive in 'paused' with a reason, the customer's Continue (or the page moving on) lets the run go on."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.transports = []
        self.s = ScriptedService(spawn=lambda j, o: self.transports.append(FakeTransport(o, LOGIN_PAGES)) or self.transports[-1], llm_for=llm_for(['{"action":"done","answer":"signed in"}']),
                                 root=self.tmp.name, jev_mode='off', takeover_seconds=5)
        svc.HAND_POLL_SECONDS = 0.05

    def tearDown(self):
        svc.HAND_POLL_SECONDS = 2; self.tmp.cleanup()

    def test_the_job_waits_in_paused_with_a_reason_and_continues_when_the_customer_presses_continue(self):
        self.s.start('acct', RID, 'check my orders at https://shop.example/signin')
        p = wait(self.s, ('paused',))
        self.assertIn('sign in', p['needs_you'].lower()); self.assertTrue(p['takeover']); self.assertEqual(p['state'], 'paused')
        self.transports[0].at = 'home'                                  # the customer signed in
        time.sleep(0.05)
        self.s.resume('acct', RID)
        p = wait(self.s, ('done',))
        self.assertEqual(p['answer'], 'signed in'); self.assertIsNone(p['needs_you'])

    def test_it_carries_on_by_itself_when_the_page_has_moved_past_the_sign_in(self):
        self.s.start('acct', RID, 'check my orders at https://shop.example/signin')
        wait(self.s, ('paused',))
        self.transports[0].at = 'home'
        p = wait(self.s, ('done',), timeout=5)
        self.assertEqual(p['answer'], 'signed in')

    def test_a_wait_nobody_answers_ends_as_a_hand_off(self):
        self.s.takeover_seconds = 0.3
        self.s.start('acct', RID, 'check my orders at https://shop.example/signin')
        p = wait(self.s, ('handoff',), timeout=5)
        self.assertIn('sign in', p['reason'])


LOGIN_PAGES = {'start': {'url': 'https://shop.example/signin', 'snap': LOGIN['start']['snap'], 'text': 'Sign in'},
               'home': {'url': 'https://shop.example/orders', 'snap': LOGIN['home']['snap'], 'text': 'Your orders'}}

if __name__ == '__main__':
    unittest.main()
