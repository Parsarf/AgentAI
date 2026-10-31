"""Using a saved login or card: offered only on the matching page, used only after a yes, typed straight into the page, and never seen by a model, the trace or the steps."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from agentai_platform.browse import trace as tr
from agentai_platform.browse.ladder import Ladder
from agentai_platform.browse.loop import BrowseRunner
from agentai_platform.browse.service import BrowseError, BrowseService, clean_vault
from tests.test_browse import FakeSession, scripted_llm

SECRET_PW = 'hunter2-SECRET-pw'
SECRET_CARD = '4242424242424242'
LOGIN_ITEM = {'id': 'l1', 'kind': 'login', 'label': 'Login for shop.example', 'site': 'shop.example'}
CARD_ITEM = {'id': 'c1', 'kind': 'card', 'label': 'Visa ending 4242', 'site': ''}
LOGIN_PAGES = {'start': {'url': 'https://shop.example/signin', 'snap': '[1] <input type=text> "Email"\n[2] <input type=password> "Password"\n[3] <a> "Forgot password"', 'text': 'Sign in', 'go': {'Enter': 'home'}},
               'home': {'url': 'https://shop.example/account', 'snap': '[1] <a> "Orders"', 'text': 'Welcome'}}
CARD_PAGES = {'start': {'url': 'https://shop.example/checkout', 'snap': '[1] <input type=text> "Name on card"\n[2] <input type=text> "Card number"\n[3] <input type=text> "Expiry (MM/YY)"\n[4] <input type=text> "CVV"\n[5] <button> "Place order"', 'text': 'Pay'}}


class RecordingSession(FakeSession):
    def __init__(self, pages):
        super().__init__(pages); self.typed = []
    def act(self, action, ref=None, value=None, label=None, **kw):
        self.log.append(('act', action, ref, value))
        if action == 'type': self.typed.append((ref, value))
        if action == 'press' and value == 'Enter' and 'Enter' in self.pages[self.at].get('go', {}): self.at = self.pages[self.at]['go']['Enter']
        return {'ok': True, 'url': self.pages[self.at]['url']}


class Fill(unittest.TestCase):
    def run_loop(self, pages, item, answer, trace_path=None, steps=('{"action":"done","answer":"ok","reason":"r"}',)):
        s, asked = RecordingSession(pages), []
        def gate(question, step):
            asked.append(question); return answer(question), 2.0
        llm = scripted_llm(list(steps))
        events = []
        r = BrowseRunner(s, Ladder(agent=llm), max_steps=4, ask_gate=gate, vault=[item], trace=tr.Trace(trace_path) if trace_path else tr.NULL, on_event=lambda k, d: events.append((k, d))).run('order it', pages['start']['url'])
        return r, s, asked, llm, events

    def yes(self, secret):
        return lambda q: {'option': 'o1', 'secret': dict(secret)}

    def test_a_saved_login_is_offered_and_typed_in_after_a_yes_and_no_model_sees_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.jsonl'
            r, s, asked, llm, events = self.run_loop(LOGIN_PAGES, LOGIN_ITEM, self.yes({'username': 'ada@example.com', 'password': SECRET_PW}), path)
            self.assertEqual([o['label'] for o in asked[0]['options']], ['Use Login for shop.example', 'I will do it myself']); self.assertEqual(asked[0]['use'], 'login')
            self.assertEqual(s.typed, [(1, 'ada@example.com'), (2, SECRET_PW)])
            self.assertIn(('act', 'press', None, 'Enter'), s.log); self.assertEqual(r.status, 'done')            # the next page was read normally
            everything = json.dumps([r.steps, events, path.read_text(), json.dumps(asked)])
            for secret in (SECRET_PW, 'ada@example.com'):
                self.assertNotIn(secret, everything)
            self.assertEqual(llm.calls, ['agent'])                                                                  # only the page after sign-in reached the assistant

    def test_a_no_leaves_the_sign_in_to_the_customer(self):
        r, s, asked, llm, _ = self.run_loop(LOGIN_PAGES, LOGIN_ITEM, lambda q: {'option': 'o2'})
        self.assertEqual((r.status, s.typed, llm.calls), ('handoff', [], []))

    def test_a_login_for_another_site_is_not_offered(self):
        r, s, asked, llm, _ = self.run_loop(LOGIN_PAGES, {**LOGIN_ITEM, 'site': 'other.example'}, self.yes({'username': 'a', 'password': 'b'}))
        self.assertEqual((asked, r.status, s.typed), ([], 'handoff', []))

    def test_a_login_that_does_not_work_is_tried_once_then_handed_over(self):
        pages = {'start': {**LOGIN_PAGES['start'], 'go': {}}}
        r, s, asked, llm, _ = self.run_loop(pages, LOGIN_ITEM, self.yes({'username': 'a@b.c', 'password': 'pw'}))
        self.assertEqual((len(asked), r.status), (1, 'handoff'))

    def test_a_saved_card_fills_the_card_fields_but_never_the_code_and_the_customer_places_the_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.jsonl'
            card = {'number': SECRET_CARD, 'exp_month': 7, 'exp_year': 2030, 'name': 'Ada Lovelace'}
            r, s, asked, llm, events = self.run_loop(CARD_PAGES, CARD_ITEM, self.yes(card), path)
            self.assertEqual(sorted(s.typed), [(1, 'Ada Lovelace'), (2, SECRET_CARD), (3, '07/30')])                # not the CVV field, and not clicked "Place order"
            self.assertNotIn(('act', 'click', 5, None), s.log)
            self.assertEqual(r.status, 'handoff'); self.assertIn('security code', r.reason); self.assertEqual(llm.calls, [])
            everything = json.dumps([r.steps, events, path.read_text(), json.dumps(asked)])
            for secret in (SECRET_CARD, 'Ada Lovelace'):
                self.assertNotIn(secret, everything)

    def test_a_card_form_it_cannot_read_is_left_to_the_customer(self):
        pages = {'start': {'url': 'https://shop.example/checkout', 'snap': '[1] <button> "Place order"', 'text': 'Pay with the card form below. CVV expiry card number'}}
        r, s, asked, llm, _ = self.run_loop(pages, CARD_ITEM, self.yes({'number': SECRET_CARD, 'exp_month': 1, 'exp_year': 2030, 'name': 'x'}))
        self.assertEqual((r.status, s.typed), ('handoff', [])); self.assertEqual(len(asked), 1)

    def test_without_a_way_to_ask_nothing_is_offered(self):
        s = RecordingSession(LOGIN_PAGES)
        r = BrowseRunner(s, Ladder(agent=scripted_llm([])), max_steps=2, vault=[LOGIN_ITEM]).run('x', 'https://shop.example/signin')
        self.assertEqual((r.status, s.typed), ('handoff', []))


class Service(unittest.TestCase):
    def test_using_a_saved_item_needs_the_item_and_it_is_never_polled_back(self):
        from tests.test_browse_service import FakeTransport, ScriptedService, llm_for, RID
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        pages = {'start': {'url': 'https://shop.example/signin', 'snap': LOGIN_PAGES['start']['snap'], 'text': 'Sign in'}}
        s = ScriptedService(spawn=lambda j, o: FakeTransport(o, pages=pages), llm_for=llm_for(['{"action":"stop","reason":"x"}']), root=tmp.name, jev_mode='off', takeover_seconds=5)
        s.start('acct', RID, 'sign in at https://shop.example/signin', vault=[LOGIN_ITEM, {'id': 'x', 'kind': 'bank', 'label': 'no'}, {'kind': 'login'}])
        end = time.time() + 5
        while time.time() < end and s.poll('acct', RID)['state'] != 'asking':
            time.sleep(0.02)
        q = s.poll('acct', RID)['question']
        self.assertEqual((q['use'], q['options'][0]['item'], 'item' in q['options'][1]), ('login', 'l1', False))
        with self.assertRaises(BrowseError): s.answer('acct', RID, q['id'], option='o1')                      # yes, but no item sent
        s.answer('acct', RID, q['id'], option='o1', secret={'username': 'u', 'password': SECRET_PW})
        time.sleep(0.3)
        self.assertNotIn(SECRET_PW, json.dumps(s.poll('acct', RID))); self.assertNotIn(SECRET_PW, (Path(tmp.name) / RID / 'trace.jsonl').read_text())

    def test_the_readable_list_is_cleaned(self):
        self.assertEqual(clean_vault([LOGIN_ITEM, {'id': 'x', 'kind': 'bank', 'label': 'no'}, {'kind': 'login'}, 'junk']), [LOGIN_ITEM])
        self.assertEqual(clean_vault(None), [])


if __name__ == '__main__':
    unittest.main()
