"""JEV display choice for a plain-text reply: asked only when worth it, never changes a word, and anything uncertain stays plain."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform.routing import display
from agentai_platform.routing.display import STYLES, DisplayDecider, worth_asking
from tests.test_native_run import Base

MODEL = 'jev-1.13.0'
STEPS = 'Here is how to reset it.\n\n1. Unplug the router\n2. Wait ten seconds\n3. Plug it back in\n4. Wait for the light\n\n' + 'Then try again. ' * 20
LIST = 'A few good options:\n\n- Luigi on Main St\n- Nonna on Elm St\n- Slice Bar downtown\n\n' + 'All are open late. ' * 20
CHAT = 'Sure! ' * 10


def jev(style, p=0.9, model=MODEL):
    rest = (1 - p) / (len(STYLES) - 1)
    return json.dumps({'model': model, 'answers': {'display': {'type': 'choice', 'choice': style, 'probabilities': {s: (p if s == style else rest) for s in STYLES}}}})


class Decider(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup); root = Path(d.name)
        (root / 'routing.json').write_text(json.dumps({'enabled': True})); (root / 'key').write_text('k')
        self.calls, self.reply, self.on = [], jev('steps'), True
        def transport(endpoint, body, key, deadline):
            self.calls.append((body, deadline))
            if isinstance(self.reply, Exception): raise self.reply
            return self.reply
        self.d = DisplayDecider(config_path=str(root / 'routing.json'), key_path=str(root / 'key'), switch_on=lambda: self.on, transport=transport)

    def test_short_or_unstructured_replies_are_never_asked_about(self):
        self.assertFalse(worth_asking(CHAT)); self.assertFalse(worth_asking('x' * 2000)); self.assertFalse(worth_asking(None))
        self.assertTrue(worth_asking(STEPS)); self.assertTrue(worth_asking(LIST))
        self.assertIsNone(self.d.choose(CHAT)); self.assertEqual(self.calls, [])

    def test_the_switch_off_means_no_call(self):
        self.on = False
        self.assertIsNone(self.d.choose(STEPS)); self.assertEqual(self.calls, [])

    def test_each_layout_comes_back_only_when_the_text_has_what_it_needs(self):
        self.reply = jev('steps'); self.assertEqual(self.d.choose(STEPS), 'steps')
        self.reply = jev('list'); self.assertEqual(self.d.choose(LIST), 'list')
        self.reply = jev('answer'); self.assertEqual(self.d.choose(LIST), 'answer')
        self.reply = jev('plain'); self.assertIsNone(self.d.choose(STEPS))
        self.reply = jev('steps'); self.assertIsNone(self.d.choose(LIST))                    # a checklist needs a numbered list to work on
        self.reply = jev('list'); self.assertIsNone(self.d.choose(STEPS))                    # tiles need bullets

    def test_unsure_unusable_or_slow_jev_means_plain(self):
        for reply in (jev('steps', p=0.6), jev('steps', model='other'), 'oops', json.dumps({'model': MODEL, 'answers': {}}), TimeoutError('slow')):
            self.reply = reply
            self.assertIsNone(self.d.choose(STEPS), str(reply)[:40])

    def test_what_jev_sees_is_the_reply_only_bounded_and_scrubbed_with_a_short_deadline(self):
        secret = 'sk-ant-api03-' + 'A' * 40
        self.d.choose(STEPS + ' my key is ' + secret + ' ' + 'z' * 3000)
        body, deadline = self.calls[0]
        self.assertNotIn(secret, json.dumps(body)); self.assertLessEqual(len(body['state']), 1700); self.assertLessEqual(deadline, display.DEADLINE_S)
        self.assertEqual(set(body['questions']['display']['criteria']), set(STYLES))


class Flow(Base):
    def with_display(self, style, on=True):
        calls = []
        class Fake:
            def choose(s, text):
                calls.append(text); return style if on else None
        self.worker.driver.display = Fake()
        return calls

    def blocks(self):
        return self.rows("SELECT kind,spec_json,anchor_message_id FROM data_blocks ORDER BY position")

    def test_a_plain_reply_gets_the_layout_jev_chose_anchored_to_it_and_the_words_stay(self):
        calls = self.with_display('steps')
        self.run_message('how do I reset my router', replies=[STEPS])
        b = self.blocks()
        self.assertEqual([(x['kind'], json.loads(x['spec_json'])['style']) for x in b], [('display', 'steps')])
        agent_row = self.rows("SELECT id,content FROM chat_messages WHERE provenance='agent' ORDER BY id DESC LIMIT 1")[0]
        self.assertEqual((b[0]['anchor_message_id'], agent_row['content']), (agent_row['id'], STEPS.strip()))
        self.assertEqual(calls, [STEPS.strip()])

    def test_a_reply_with_its_own_card_is_never_sent_to_jev(self):
        calls = self.with_display('list')
        card = 'Here.\n```lumina-doc\n' + json.dumps({'version': '1.0', 'responseId': 'tip', 'blocks': [{'id': 'tip', 'type': 'callout', 'props': {'tone': 'tip', 'content': 'Book early.'}}]}) + '\n```'
        self.run_message('tips please', replies=[card], ui='medium')
        self.assertEqual(calls, []); self.assertEqual([x['kind'] for x in self.blocks()], ['document'])

    def test_plain_stays_plain_and_a_broken_decider_never_fails_the_answer(self):
        self.with_display(None)
        self.run_message('hi', replies=[STEPS])
        self.assertEqual(self.blocks(), [])
        class Broken:
            def choose(s, text): raise RuntimeError('down')
        self.worker.driver.display = Broken()
        self.run_message('again', key='k2', replies=[LIST])
        self.assertEqual(self.rows("SELECT state FROM customer_requests ORDER BY sequence DESC")[0]['state'], 'completed')


class PresentationHint(Decider):
    """JEV's advisory presentation plan rides on the SAME call as the display choice: no extra call, no data, and it never blocks."""

    def reply_with(self, style, hint, p=0.9, hp=0.9):
        rest = (1 - hp) / (len(display.HINTS) - 1)
        body = json.loads(jev(style, p))
        body['answers']['presentation'] = {'type': 'choice', 'choice': hint, 'probabilities': {h: (hp if h == hint else rest) for h in display.HINTS}}
        return json.dumps(body)

    def test_one_call_carries_both_questions(self):
        self.reply = self.reply_with('list', 'table')
        style, plan = self.d.decide(LIST)
        self.assertEqual(len(self.calls), 1); self.assertEqual(set(self.calls[0][0]['questions']), {'display', 'presentation'})
        self.assertEqual(style, 'list')
        self.assertEqual(plan['advisory'], True); self.assertEqual(plan['blocks'][0]['componentId'], 'table')
        self.assertLessEqual(set(plan['blocks'][0]), {'blockId', 'componentId', 'variant', 'layout', 'purpose', 'dataRequirements'})       # a hint names a component; it never carries data or props

    def test_choose_still_works_and_old_replies_without_the_second_answer_are_fine(self):
        self.reply = jev('steps')                                    # no 'presentation' answer at all
        self.assertEqual(self.d.decide(STEPS), ('steps', None)); self.assertEqual(self.d.choose(STEPS), 'steps')

    def test_unsure_none_or_broken_hint_is_no_hint(self):
        for reply in (self.reply_with('plain', 'none'), self.reply_with('plain', 'table', hp=0.5)):
            self.reply = reply; self.assertEqual(self.d.decide(LIST), (None, None))
        self.reply = self.reply_with('list', 'table').replace('"timeline"', '"nope"')
        self.assertEqual(self.d.decide(LIST)[1], None)

    def test_off_switch_slow_or_failing_jev_means_no_plan_and_no_error(self):
        self.on = False; self.assertEqual(self.d.decide(LIST), (None, None)); self.assertEqual(self.calls, [])
        self.on = True; self.reply = TimeoutError('slow'); self.assertEqual(self.d.decide(LIST), (None, None))

    def test_short_replies_cost_nothing(self):
        self.assertEqual(self.d.decide(CHAT), (None, None)); self.assertEqual(self.calls, [])


class HintStored(Flow):
    def test_the_plan_is_stored_with_the_display_choice_as_advice_only(self):
        plan = {'advisory': True, 'blocks': [{'blockId': 'hint1', 'componentId': 'table', 'purpose': 'Compare options'}]}
        class Fake:
            def decide(s, text): return 'list', plan
        self.worker.driver.display = Fake()
        self.run_message('options please', replies=[LIST])
        spec = json.loads(self.blocks()[0]['spec_json']); self.assertEqual((spec['style'], spec['presentationPlan']), ('list', plan))


if __name__ == '__main__':
    unittest.main()
