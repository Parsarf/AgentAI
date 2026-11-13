"""Behaviours ported from the standalone JEV extension's decision loop (the owner's reference), on Lumina's own engines and under Lumina's own rules.

What changed for JEV: it is offered the controls a person could click right now (up to 80, not the first 20 in the page's code); it is told what has the keyboard and what
a field reads after typing; a click on a field that already has focus is refused with the reason; a picture click that lands on nothing is moved to the control beside it;
a panel under the pointer scrolls before the page; Escape is offered; and a stumble gets a second look before the assistant is called.
What did not change: every code rule (payment, sign-in, sensitive controls), real browser input, and the assistant taking over when JEV cannot go on.
"""
import unittest

from agentai_platform.browse import candidates as cand
from agentai_platform.browse import modes
from agentai_platform.browse.ladder import RUNNER_V2, RUNNER_V3, JevChooser, build_heads, describe
from tests.test_browse_modes import SHOT, PictureJev, hit, runner

URL = 'https://shop.example/'


def el(ref, label, x=100, y=100, in_view=True, covered=False, **kw):
    return {'ref': ref, 'label': label, 'in_view': in_view, 'covered': covered if in_view else None, 'x': x, 'y': y, **kw}


class Page:
    """One scripted page for an engine that reports focus. `controls`: (tag, label, element state). Clicking or typing into a text field gives it the keyboard."""
    def __init__(self, controls, hits=None, fps=None, inner=None):
        self.controls, self.hits, self.acts, self.focus, self.values = controls, hits or {}, [], None, {}
        self.fps, self.inner = iter(fps) if fps else None, inner
    def open(self, url): return {'ok': True, 'url': url, 'title': 'T'}
    def _fp(self): return next(self.fps) if self.fps else None
    def snapshot(self):
        lines = '\n'.join(f'[{e["ref"]}] <{tag}> "{e["label"]}"' for tag, e in self.controls)
        focus = None
        if self.focus is not None:
            tag, e = next(c for c in self.controls if c[1]['ref'] == self.focus)
            focus = {'tag': tag.split()[0], 'type': '', 'editable': tag.startswith('input'), 'secret': False, 'ref': self.focus, 'label': e['label'], 'value': self.values.get(self.focus, '')}
        return {'ok': True, 'url': URL, 'title': 'T', 'snapshot': lines, 'text': 'Shop', 'elements': [e for _, e in self.controls], 'scroll': 0, 'height': 800, 'window': 800, 'focus': focus, 'page_fp': self._fp()}
    def view(self, save=False): return {'ok': True, **SHOT, 'file': None}
    def probe(self, x, y): return {'ok': True, 'hit': self.hits.get((round(x), round(y)))}
    def act(self, action, ref=None, value=None, label=None, x=None, y=None):
        x, y = (round(x), round(y)) if x is not None else (None, None)
        self.acts.append((action, ref, value, x, y))
        under = self.hits.get((x, y)) if action == 'clickat' else None
        if under and under.get('editable'):
            self.focus = next(e['ref'] for _, e in self.controls if e['label'] == under['label'])
        if action in ('click', 'type') and ref is not None:
            self.focus = ref
            if action == 'type': self.values[ref] = value
        out = {'ok': True, 'url': URL, 'page_fp': self._fp()}
        if action == 'scroll' and self.inner: out.update(self.inner.pop(0))
        return out
    def screenshot(self): return {'ok': True, 'file': 'shot-900.jpg'}


FIELD = {(300, 100): {**hit('Search'), 'tag': 'input', 'editable': True}}                      # what a probe names under the search box
POINT_AT_FIELD = {'operation': 'click', 'click_target': 'none', 'at': (300 / 1280, 100 / 800)}      # a text field is focused by clicking where it is in the picture
SEARCH = [('input type=search', el(1, 'Search', 300, 100)), ('button', el(2, 'Go', 520, 100)), ('a', el(3, 'Shoes', 300, 300))]
state = lambda jev, i: jev.calls[i][0]['state']
options = lambda jev, i, question: jev.calls[i][0]['questions'].get(question, {}).get('criteria', {})


class WhatJevIsOffered(unittest.TestCase):
    def test_reachable_is_what_a_person_could_click_right_now(self):
        lines = '\n'.join(f'[{i}] <button> "B{i}"' for i in range(1, 121))
        els = [el(i, f'B{i}', in_view=i > 60, covered=i > 110) for i in range(1, 121)]             # 60 off screen first (a long menu), then 50 in the window, then 10 under a banner
        everything = cand.build(lines, limit=200, elements=els)
        seen = cand.reachable(everything)
        self.assertEqual([c['ref'] for c in seen], list(range(61, 111)))                              # all 50, in page order; nothing off screen, nothing covered
        self.assertEqual(len(cand.reachable(cand.build('\n'.join(f'[{i}] <button> "B{i}"' for i in range(1, 121)), limit=200, elements=[el(i, f'B{i}') for i in range(1, 121)]))), cand.JEV_LIMIT)
        self.assertIsNone(cand.reachable(cand.build(lines, limit=200)))                              # an engine that does not say what is visible: the caller keeps its own list
        self.assertEqual(cand.reachable(cand.build(lines, limit=200, elements=[el(i, f'B{i}', in_view=False) for i in range(1, 121)])), [])       # nothing reachable is an answer, not "unknown"

    def test_jev_sees_the_visible_controls_not_the_first_twenty_and_its_choice_past_twenty_is_carried_out(self):
        controls = [('a', el(i, f'Menu {i}', in_view=False)) for i in range(1, 41)] + [('button', el(i, f'Item {i}', 100 + i, 400)) for i in range(41, 71)]
        s = Page(controls)
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'c65'}], max_steps=1)
        out = r.run('add item 65', URL)
        offered = options(jev, 0, 'click_target')
        self.assertEqual(set(offered), {f'c{i}' for i in range(41, 71)} | {'none'})                  # the 30 on screen; none of the 40 menu links that come first in the page
        self.assertEqual(s.acts[0][:2], ('click', 65)); self.assertEqual(out.steps[0]['label'], 'Item 65')

    def test_the_sensitive_control_rule_still_applies_to_a_control_past_the_old_cap(self):
        controls = [('a', el(i, f'Menu {i}', in_view=False)) for i in range(1, 41)] + [('button', el(41, 'Place order', 300, 400))]
        s = Page(controls)
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'c41'}], max_steps=1)
        out = r.run('order it', URL)
        self.assertEqual((out.status, s.acts), ('handoff', []))                                      # nothing was clicked: that one is the customer's
        self.assertEqual(out.pending_action['label'], 'Place order')

    def test_an_older_engine_keeps_the_list_it_had(self):
        from tests.test_browse import FLAT, FakeSession
        r, jev, _ = runner(FakeSession(FLAT), [{'operation': 'done'}], ['{"action":"done","answer":"ok"}'], max_steps=1)
        r.run('g', URL)
        self.assertNotIn('Keyboard:', state(jev, 0)); self.assertNotIn('press_escape', options(jev, 0, 'operation'))


class KeyboardFeedback(unittest.TestCase):
    def test_jev_is_told_what_has_the_keyboard_and_what_the_field_reads_after_typing(self):
        s = Page(SEARCH, hits=FIELD)
        script = [POINT_AT_FIELD, {'operation': 'type', 'type_target': 'c1', 'type_text': 't1'}, {'operation': 'press_enter'}]      # t1: the quoted words of the request
        r, jev, _ = runner(s, script, max_steps=3)
        r.run('search for "blue shoes"', URL)
        self.assertIn('Keyboard: no text field has focus', state(jev, 0))
        self.assertIn('-> ok; a text field is now focused and ready for typing', state(jev, 1))      # what the click did, which a picture cannot show
        self.assertIn('Keyboard: the text field "Search" has focus (it is empty)', state(jev, 1))
        self.assertIn('has the keyboard focus, ready for typing', options(jev, 1, 'type_target')['c1'])
        self.assertIn('the field now reads "blue shoes"', state(jev, 2))
        self.assertIn('it reads "blue shoes"', state(jev, 2))
        self.assertEqual([a[:3] for a in s.acts], [('clickat', None, None), ('type', 1, 'blue shoes'), ('press', None, 'Enter')])

    def test_a_click_on_something_that_takes_no_text_says_so(self):
        s = Page(SEARCH)
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'c3'}, {'operation': 'done'}], ['{"action":"done","answer":"ok"}'], max_steps=2)
        r.run('g', URL)
        self.assertIn('-> ok; no text field has focus', state(jev, 1))

    def test_a_field_that_already_has_focus_is_not_clicked_again_and_jev_is_told_why(self):
        s = Page(SEARCH, hits=FIELD)
        r, jev, events = runner(s, [POINT_AT_FIELD, POINT_AT_FIELD, {'operation': 'type', 'type_target': 'c1', 'type_text': 't1'}], max_steps=3)
        out = r.run('search for "blue shoes"', URL)
        self.assertEqual([a[:2] for a in s.acts], [('clickat', None), ('type', 1)])                       # the second click never reached the browser
        self.assertEqual([(h['action'], h['result']) for h in out.steps], [('click', 'ok'), ('click', 'already_focused'), ('type', 'ok')])
        self.assertIn('already has the keyboard focus', state(jev, 2))
        self.assertTrue(all('note' not in data for kind, data in events if kind == 'step'))          # the note is for the decider, not the customer's step list

    def test_jev_asking_for_the_same_dead_click_again_and_again_hands_the_page_to_the_assistant(self):
        s = Page(SEARCH, hits=FIELD)
        r, jev, _ = runner(s, [POINT_AT_FIELD] * 3, ['{"action":"click","ref":3}'], max_steps=4)
        out = r.run('g', URL)
        self.assertEqual([(h['by'], h['result']) for h in out.steps], [('jev', 'ok'), ('jev', 'already_focused'), ('jev', 'already_focused'), ('agent', 'ok')])        # told twice, then the same-control rule gives the page to the assistant
        self.assertEqual(len(s.acts), 2)

    def test_focus_words(self):
        self.assertEqual(JevChooser.focus_words(None), '')                                           # the engine does not say: nothing is claimed
        self.assertIn('no text field has focus', JevChooser.focus_words({}))
        self.assertIn('no text field has focus', JevChooser.focus_words({'editable': True, 'secret': True, 'value': 'x'}))      # a secret field is never described as ready for typing
        words = JevChooser.focus_words({'editable': True, 'label': 'Email', 'value': 'me@example.com'})
        self.assertIn('"Email"', words); self.assertNotIn('me@example.com', words)                   # what the field holds goes through the same scrub as everything else


class PointingAndScrolling(unittest.TestCase):
    def test_a_picture_click_on_nothing_clickable_is_moved_to_the_listed_control_beside_it(self):
        s = Page(SEARCH, hits={(540, 110): {**hit(''), 'tag': 'div'}})
        point = {'operation': 'click', 'click_target': 'none', 'at': (540 / 1280, 110 / 800)}
        r, jev, _ = runner(s, [point], max_steps=1)
        out = r.run('g', URL)
        self.assertEqual(s.acts[0][:2], ('click', 2)); self.assertEqual(out.steps[0]['label'], 'Go')  # the "Go" button 20 px away, clicked as itself

    def test_a_point_on_a_real_control_or_far_from_any_is_clicked_where_it_is(self):
        for where, under in (((540, 110), hit('Go')), ((1000, 700), {**hit(''), 'tag': 'div'})):
            s = Page(SEARCH, hits={where: under})
            r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'none', 'at': (where[0] / 1280, where[1] / 800)}], max_steps=1)
            r.run('g', URL)
            self.assertEqual((s.acts[0][0], s.acts[0][3:]), ('clickat', where), under['tag'])

    def test_a_click_is_never_moved_onto_a_sensitive_control(self):
        controls = [('button', el(1, 'Pay now', 540, 100))]
        s = Page(controls, hits={(540, 110): {**hit(''), 'tag': 'div'}})
        r, jev, _ = runner(s, [{'operation': 'click', 'click_target': 'none', 'at': (540 / 1280, 110 / 800)}], max_steps=1)
        r.run('g', URL)
        self.assertEqual(s.acts[0][0], 'clickat')
        self.assertIsNone(cand.nearest(cand.build('[1] <button> "Pay now"', elements=[el(1, 'Pay now', 540, 100)]), 540, 110, 1280, 800))

    def test_a_panel_that_scrolled_counts_as_a_change_and_jev_is_told_when_it_ends(self):
        s = Page(SEARCH, fps=[5] * 20, inner=[{'moved': True, 'inner': True, 'at_end': False}, {'moved': True, 'inner': True, 'at_end': True}, {'moved': False, 'inner': True, 'at_end': True}])
        down = {'operation': 'scroll_down'}
        r, jev, _ = runner(s, [down, down, down, {'operation': 'done'}], ['{"action":"done","answer":"ok"}'], max_steps=4)
        out = r.run('g', URL)
        self.assertEqual([h['changed'] for h in out.steps[:3]], [True, True, False])                 # the page's own fingerprint never moved; the panel did, twice
        self.assertIn('scrolled the panel under the pointer', state(jev, 1))
        self.assertIn('which is now at its end', state(jev, 2))
        self.assertIn('already at its end', state(jev, 3))


class OperationsAndNudges(unittest.TestCase):
    def test_escape_is_offered_only_by_an_engine_that_reports_focus_and_presses_the_real_key(self):
        cands = cand.build('[1] <button> "Close"')
        self.assertIn('press_escape', build_heads(cands, RUNNER_V3)[0]['operation']); self.assertNotIn('press_escape', build_heads(cands, RUNNER_V2)[0]['operation'])
        s = Page(SEARCH)
        r, jev, _ = runner(s, [{'operation': 'press_escape'}], max_steps=1)
        r.run('g', URL)
        self.assertEqual(s.acts[0][:3], ('press', None, 'Escape'))

    def test_two_dead_clicks_get_a_nudge_not_a_hand_over(self):
        dead = lambda label: {'action': 'click', 'label': label, 'result': 'ok', 'changed': False, 'by': 'jev'}
        self.assertIn('last two clicks changed nothing', modes.hint({}, [dead('A'), dead('B')]))
        self.assertEqual(modes.hint({}, [dead('A')]), ''); self.assertEqual(modes.hint({}, [dead('A'), {**dead('B'), 'changed': True}]), '')
        self.assertEqual(modes.claude_reason([dead('A'), dead('B')]), '')                            # JEV keeps the page and tries something else

    def test_a_focused_candidate_says_so_and_only_an_editable_focus_counts(self):
        cands = cand.build('[1] <input type=search> "Search"\n[2] <button> "Go"', elements=[el(1, 'Search'), el(2, 'Go')])
        marked = cand.with_focus(cands, {'editable': True, 'ref': 1})
        self.assertIn('has the keyboard focus', describe(marked[0])); self.assertNotIn('focus', describe(marked[1]))
        self.assertEqual(cand.with_focus(cands, {'editable': False, 'ref': 2}), cands); self.assertEqual(cand.with_focus(cands, None), cands)


if __name__ == '__main__':
    unittest.main()
