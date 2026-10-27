"""JEV sees the window on every step, together with the page's own list of controls: it picks from the list and points at a spot only when nothing listed fits.
The assistant that JEV hands a page to gets the same picture."""
import io
import json
import unittest
import urllib.error

from agentai_platform.browse import candidates as cand
from agentai_platform.browse.ladder import IMAGE_HEADERS, JevChooser, Ladder, Look, NoSpot, build_heads, describe
from agentai_platform.browse.loop import BrowseRunner
from tests.test_browse import FpSession, FLAT, scripted_llm
from tests.test_browse_modes import MODEL, SHOT, PictureJev, PictureSession, SHOP, box, hit, picture_answer, runner

SNAP = '[1] <a> "Open search"\n[2] <input type=text> "Search"\n[3] <a> "Cart"'
PAGE = {'url': 'https://shop.example/', 'title': 'Shop'}


class Transport:
    def __init__(self, make): self.make, self.calls = make, []
    def __call__(self, endpoint, body, key, deadline, headers=None):
        self.calls.append((body, headers, deadline)); return self.make(body)


def chooser(make):
    t = Transport(make)
    return JevChooser('https://x', MODEL, 'k', t), t


class SightRequests(unittest.TestCase):
    cands = cand.build(SNAP, elements=[{'ref': 1, 'label': 'Open search', 'in_view': True, 'covered': True}, {'ref': 2, 'label': 'Search', 'in_view': True, 'covered': False},
                                       {'ref': 3, 'label': 'Cart', 'in_view': False, 'covered': False}])

    def ask(self, make, **kw):
        jev, t = chooser(make)
        return jev.choose('Find a paddle', 'Shop text', self.cands, page=PAGE, phrases=['carbon paddle'], shot=SHOT, **kw), t

    def test_the_request_carries_the_picture_the_list_and_both_kinds_of_question(self):
        pick, t = self.ask(lambda b: picture_answer(b, {'operation': 'click', 'click_target': 'c3'}))
        body, headers, deadline = t.calls[0]
        self.assertEqual(headers, IMAGE_HEADERS); self.assertGreaterEqual(deadline, 12)
        (ref, asset), = body['assets'].items(); self.assertEqual(asset['data_base64'], SHOT['data']); self.assertIn(ref, body['state'])
        self.assertEqual({q['type'] for q in body['questions'].values()}, {'choice', 'box', 'noul'})
        self.assertIn('Page text', body['state']); self.assertIn('A control marked covered cannot be clicked', body['state'])
        self.assertEqual((pick.operation, pick.target, pick.point), ('click', 'c3', None))              # a listed control that is right is simply chosen

    def test_a_covered_or_off_screen_control_says_so_to_jev(self):
        self.assertIn('covered by something else', describe(self.cands[0])); self.assertIn('off screen', describe(self.cands[2])); self.assertNotIn('covered', describe(self.cands[1]))

    def test_when_nothing_listed_fits_jev_points_at_what_it_sees(self):
        pick, _ = self.ask(lambda b: picture_answer(b, {'operation': 'click', 'click_target': 'none'}, found=0.9, spot=0.6, at=(0.25, 0.5)))
        self.assertEqual((pick.operation, pick.target), ('click', None)); self.assertAlmostEqual(pick.point[0], 320.0); self.assertAlmostEqual(pick.point[1], 400.0)
        self.assertEqual((pick.found, pick.spot), (0.9, 0.6))

    def test_a_weak_pointing_answer_is_a_miss_never_an_action(self):
        for found, spot in ((0.3, 0.9), (0.9, 0.1)):
            with self.assertRaises(NoSpot):
                self.ask(lambda b: picture_answer(b, {'operation': 'click', 'click_target': 'none'}, found=found, spot=spot))

    def test_typing_into_a_spot_needs_a_phrase_from_the_request(self):
        pick, _ = self.ask(lambda b: picture_answer(b, {'operation': 'type', 'type_target': 'none', 'type_text': 't0'}, found=0.9, spot=0.6))
        self.assertEqual((pick.operation, pick.text), ('type', 'carbon paddle')); self.assertIsNotNone(pick.point)
        with self.assertRaises(ValueError):                                              # "write new text" for a field that is not in the list: refused, nothing typed
            self.ask(lambda b: picture_answer(b, {'operation': 'type', 'type_target': 'none', 'type_text': 'write_new'}))

    def test_without_a_picture_none_fits_is_still_a_miss_for_the_next_tier(self):
        def none_fits(body):
            answers = {}
            for name, q in body['questions'].items():
                pick = 'click' if name == 'operation' else 'none' if 'none' in q['criteria'] else list(q['criteria'])[0]
                answers[name] = {'type': 'choice', 'choice': pick, 'probabilities': {i: (1.0 if i == pick else 0.0) for i in q['criteria']}}
            return json.dumps({'model': MODEL, 'answers': answers})
        jev, _ = chooser(none_fits)
        with self.assertRaises(ValueError) as ctx:
            jev.choose('g', 't', self.cands, page=PAGE, phrases=['x'])
        self.assertIn('none fits', str(ctx.exception))

    def test_without_a_picture_the_request_is_exactly_the_text_one(self):
        jev, t = chooser(lambda b: json.dumps({'model': MODEL, 'answers': {k: {'type': 'choice', 'choice': list(q['criteria'])[0], 'probabilities': {i: (1.0 if n == 0 else 0.0) for n, i in enumerate(q['criteria'])}} for k, q in b['questions'].items()}}))
        jev.choose('g', 't', self.cands, page=PAGE)
        body, headers, _ = t.calls[0]; self.assertNotIn('assets', body); self.assertIsNone(headers); self.assertEqual({q['type'] for q in body['questions'].values()}, {'choice'})

    def test_pointing_is_only_offered_with_a_picture(self):
        plain, _ = build_heads(self.cands, phrases=['x']); sight, _ = build_heads(self.cands, phrases=['x'], points=True)
        self.assertNotIn('picture', plain['operation']['click']); self.assertIn('picture', sight['operation']['click'])
        empty_plain, _ = build_heads([], phrases=['x']); empty_sight, _ = build_heads([], phrases=['x'], points=True)
        self.assertNotIn('click', empty_plain['operation']); self.assertIn('click', empty_sight['operation']); self.assertIn('type_text', empty_sight)


class EveryStep(unittest.TestCase):
    def test_the_window_is_taken_on_every_step_and_the_picture_goes_to_the_assistant_when_jev_hands_over(self):
        s = PictureSession({'start': SHOP, 'item': {'url': 'https://shop.example/item', 'snap': '[1] <a> "Add to cart"', 'text': 'x', 'elements': []}}, hits={})
        miss = {'operation': 'click', 'click_target': 'none', 'found': 0.1, 'spot': 0.9}
        r, jev, events = runner(s, [miss, miss], ['{"action":"click","ref":1}'], max_steps=2)
        out = r.run('buy briefs', 'https://shop.example/')
        self.assertGreaterEqual(s.views, 2)                                                       # a picture on each step, not only on a problem
        self.assertTrue(all('assets' in call[0] for call in jev.calls))
        agent = r.ladder.agent
        self.assertEqual(agent.calls, ['agent']); self.assertIsNotNone(agent.looks[0].shot)       # the assistant's step sees the window too
        self.assertEqual([h['by'] for h in out.steps], ['rule', 'agent'])

    def test_a_runner_that_cannot_show_the_window_stays_on_the_text_request(self):
        s = FpSession(FLAT, iter(range(1, 99)))
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'c2'}], ['{"action":"done","answer":"ok"}'], max_steps=2)
        r.run('g', 'https://shop.example/')
        self.assertTrue(jev.calls); self.assertTrue(all('assets' not in call[0] for call in jev.calls))

    def test_a_picture_that_cannot_be_taken_with_a_list_present_just_means_text_for_that_step(self):
        s = PictureSession({'start': SHOP, 'item': {'url': 'https://shop.example/item', 'snap': '[1] <a> "x"', 'text': 'x', 'elements': []}}); s.view = lambda save=False: {'ok': False, 'error': 'no_picture'}
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'c1'}], ['{"action":"done","answer":"ok"}'], max_steps=1)
        out = r.run('g', 'https://shop.example/')
        self.assertTrue(jev.calls and 'assets' not in jev.calls[0][0]); self.assertEqual(out.steps[0]['by'], 'jev')           # no takeover by the assistant: the list is enough


class TheAssistantSeesToo(unittest.TestCase):
    def test_the_hand_over_carries_the_picture_only_when_there_is_one(self):
        agent = scripted_llm(['{"action":"scroll"}', '{"action":"scroll"}'])
        shot = {'data': 'QUJD', 'width': 1, 'height': 1, 'view': {'w': 1, 'h': 1}}
        Ladder(agent=agent).decide('g', [], PAGE, cand.build(SNAP), look=Look(shot=shot))
        Ladder(agent=agent).decide('g', [], PAGE, cand.build(SNAP))
        self.assertEqual(agent.looks[0].shot['data'], 'QUJD'); self.assertIsNone(agent.looks[1].shot)


if __name__ == '__main__':
    unittest.main()
