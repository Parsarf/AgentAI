"""Picture steps, the mode rules, JEV 1.14 pointing, scroll feedback and the hint, and Claude taking a page over from JEV."""
import json
from pathlib import Path
import tempfile
import unittest

from agentai_platform.browse import candidates as cand
from agentai_platform.browse import modes
from agentai_platform.browse import trace as tr
from agentai_platform.browse.ladder import IMAGE_HEADERS, JevChooser, Ladder, Look, NoSpot, picture_heads, validate_pointing
from agentai_platform.browse.loop import BrowseRunner
from tests.test_browse import FLAT, HAIKU, FakeSession, FpSession, ScriptedJev, jev_answer, scripted_llm

MODEL = 'jev-1.14.0'
VIEW = {'w': 1280, 'h': 800}
SHOT = {'data': '/9j/AAAA', 'width': 1280, 'height': 800, 'view': VIEW}


def box(cx, cy, w=0.1, h=0.1):
    return {'left': cx - w / 2, 'right': cx + w / 2, 'top': cy - h / 2, 'bottom': cy + h / 2}


def picture_answer(body, picks=None, found=0.9, spot=0.6, at=(0.5, 0.5), p=1.0, model=MODEL):
    """A valid JEV reply to a picture request: every choice as named in `picks` (else the first option), the box around `at`, and the yes/no."""
    answers = {}
    for name, q in body['questions'].items():
        if q['type'] == 'choice':
            ids = list(q['criteria']); choice = (picks or {}).get(name) or ids[0]
            answers[name] = {'type': 'choice', 'choice': choice, 'probabilities': {i: (p if i == choice else (1 - p) / (len(ids) - 1)) for i in ids}}
        elif q['type'] == 'box':
            answers[name] = {'type': 'box', 'box': box(*at), 'confidence': spot}
        else:
            answers[name] = {'type': 'noul', 'noul': found}
    return json.dumps({'model': model, 'answers': answers, 'usage': {'input_tokens': 3400}})


class PictureJev:
    """Stands in for TypeSafe for both kinds of request. Each call takes the next entry: a dict of picks for a controls request, or a dict with 'shot': {...} for a picture request."""
    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, endpoint, body, key, deadline, headers=None):
        self.calls.append((body, headers, deadline))
        step = self.script.pop(0) if self.script else {'operation': 'done'}
        if 'assets' in body:
            return picture_answer(body, {k: v for k, v in step.items() if k not in ('found', 'spot', 'at')}, step.get('found', 0.9), step.get('spot', 0.6), step.get('at', (0.5, 0.5)))
        return jev_answer(body, step, model=MODEL)


class PictureSession:
    """Scripted pages with the runner's newer fields. `hits` says what is under each point; `acts` records every call that reaches the browser."""
    def __init__(self, pages, hits=None):
        self.pages, self.at, self.hits, self.acts, self.views = pages, 'start', hits or {}, [], 0
    def open(self, url): return {'ok': True, 'url': url, 'title': 'T'}
    def snapshot(self):
        p = self.pages[self.at]
        return {'ok': True, 'url': p['url'], 'title': 'T', 'snapshot': p['snap'], 'text': p.get('text', ''), 'elements': p.get('elements', []), 'scroll': 0, 'height': 800, 'window': 800}
    def view(self, save=False):
        self.views += 1
        return {'ok': True, **SHOT, 'file': f'shot-{self.views:03d}.jpg' if save else None}
    def probe(self, x, y):
        return {'ok': True, 'hit': self.hits.get((round(x), round(y)))}
    def act(self, action, ref=None, value=None, label=None, x=None, y=None):
        self.acts.append((action, ref, value, x, y))
        nxt = self.pages[self.at].get('go', {}).get((x, y) if x is not None else ref)
        if nxt: self.at = nxt
        return {'ok': True, 'url': self.pages[self.at]['url']}
    def screenshot(self): return {'ok': True, 'file': 'shot-900.jpg'}


def hit(label, **kw):
    return {'tag': 'button', 'type': '', 'label': label, 'secret': False, 'editable': False, 'disabled': False, **kw}


COVERED = {'url': 'https://shop.example/', 'snap': '', 'text': 'Cookie banner', 'go': {(640, 400): 'shop'}}
SHOP = {'url': 'https://shop.example/shop', 'snap': '[1] <a> "Boxer Briefs"\n[2] <a> "Cart"', 'text': 'Shop', 'go': {1: 'item'},
        'elements': [{'ref': 1, 'label': 'Boxer Briefs', 'in_view': True, 'covered': False}, {'ref': 2, 'label': 'Cart', 'in_view': True, 'covered': False}]}
ITEM = {'url': 'https://shop.example/item', 'snap': '[1] <a> "Add to cart"', 'text': 'Boxer Briefs, $12', 'elements': [{'ref': 1, 'label': 'Add to cart', 'in_view': True, 'covered': False}]}


def runner(session, jev_script, llm_steps=(), trace=tr.NULL, **kw):
    transport = PictureJev(*jev_script)
    ladder = Ladder(agent=scripted_llm(list(llm_steps)), jev=JevChooser('https://x', MODEL, 'k', transport), trace=trace)
    events = []
    return BrowseRunner(session, ladder, on_event=lambda k, d: events.append((k, d)), trace=trace, **kw), transport, events


class ModeRules(unittest.TestCase):
    def snap(self, covered=(), **kw):
        return {'window': 800, 'height': 800, 'scroll': 0, 'elements': [{'in_view': True, 'covered': c} for c in covered], **kw}

    def test_a_panel_at_the_end_of_the_page_makes_the_list_in_place_of_what_it_covers(self):
        lines = '\n'.join(f'[{i}] <button> "B{i}"' for i in range(1, 26))
        state = lambda covered: [{'ref': i, 'label': f'B{i}', 'in_view': True, 'covered': covered if i < 23 else False} for i in range(1, 26)]   # 23-25: the drawer
        refs = lambda els: [c['ref'] for c in cand.build(lines, elements=els)]
        self.assertEqual(refs(state(True)), list(range(1, 18)) + [23, 24, 25])     # the drawer's own buttons replace the last covered ones, in page order
        self.assertEqual(refs(state(False)), list(range(1, 21)))                     # nothing covered: plain page order
        self.assertEqual(refs(None), list(range(1, 21)))                                   # an older runner sends no state

    def test_the_position_is_put_in_words_and_nothing_is_claimed_when_the_runner_does_not_say(self):
        snap = lambda scroll: {'scroll': scroll, 'height': 3000, 'window': 800}
        self.assertEqual(modes.position(snap(0)), ('at the top; the page is about 3.8 windows tall', False))
        self.assertEqual(modes.position(snap(1100)), ('50% of the way down; the page is about 3.8 windows tall', False))
        self.assertEqual(modes.position(snap(2200)), ('at the very bottom (nothing more below); the page is about 3.8 windows tall', True))
        self.assertEqual(modes.position({'scroll': 0, 'height': 800, 'window': 800}), ('the whole page fits in the window (nothing to scroll)', True))
        self.assertEqual(modes.position({}), ('', False))

    def test_a_hint_after_three_scrolls_in_a_row_and_only_a_hint(self):
        scroll = {'action': 'scroll', 'by': 'jev', 'result': 'ok', 'changed': True}
        click = {'action': 'click', 'by': 'jev', 'result': 'ok', 'changed': True}
        snap = {'scroll': 0, 'height': 3000, 'window': 800}
        self.assertEqual((modes.hint(snap, [scroll] * 2), modes.hint(snap, [scroll, scroll, click]), modes.hint(snap, [])), ('', '', ''))
        text = modes.hint(snap, [click] + [scroll] * 3)
        self.assertIn('scrolled 3 times in a row', text); self.assertIn('search', text); self.assertNotIn('bottom', text); self.assertNotIn('user', text)
        self.assertIn('now at the bottom', modes.hint({'scroll': 2200, 'height': 3000, 'window': 800}, [scroll] * 5))

    def test_a_picture_when_nothing_is_listed_when_most_of_the_window_is_covered_or_after_a_refused_click(self):
        c = [{'id': 'c1'}]
        self.assertEqual(modes.choose_mode(self.snap(), [], [])[0], 'picture')                                       # no controls
        self.assertEqual(modes.choose_mode(self.snap([False, False, False]), c, [])[0], 'controls')
        self.assertEqual(modes.choose_mode(self.snap([True, True, False, True]), c, [])[0], 'picture')                # most of the window is covered
        self.assertEqual(modes.choose_mode(self.snap([True, False, False, False]), c, [])[0], 'controls')           # a sticky header over one control is not a cover
        self.assertEqual(modes.choose_mode(self.snap([True, True]), c, [])[0], 'controls')                           # too few in the window to judge
        self.assertEqual(modes.choose_mode({**self.snap([True, True, True, True]), 'elements': [{'in_view': False, 'covered': None}] * 5}, c, [])[0], 'controls')   # out of the window: unknown
        self.assertEqual(modes.choose_mode(self.snap([False]), c, [{'action': 'click', 'result': 'covered', 'by': 'jev'}])[0], 'picture')
        self.assertEqual(modes.choose_mode({'elements': [{'in_view': True, 'covered': True}] * 5}, [], [])[0], 'controls')   # an older runner cannot take a picture

    def test_claude_takes_the_page_when_jev_repeats_itself_with_nothing_happening_or_cannot_carry_out_its_step(self):
        step = lambda action='click', label='Next', result='ok', changed=False, by='jev', **kw: {'action': action, 'label': label, 'result': result, 'changed': changed, 'by': by, **kw}
        self.assertEqual(modes.claude_reason([]), '')
        self.assertEqual(modes.claude_reason([step()]), '')                                                           # once is not a pattern
        self.assertIn('repeated the same step 2 times', modes.claude_reason([step(), step()]))
        self.assertEqual(modes.claude_reason([step(), step(label='Other')]), '')                                      # a different step
        self.assertEqual(modes.claude_reason([step(changed=True), step(changed=True)]), '')                           # the page moved: not stuck
        self.assertEqual(modes.claude_reason([step(), step(by='agent')]), '')                                         # the assistant's step ends JEV's run
        self.assertIn('could not be carried out (stale)', modes.claude_reason([step(result='stale', changed=None)]))
        self.assertEqual(modes.claude_reason([step(result='covered', changed=None)]), '')                             # a refused click gets a picture first, not Claude
        self.assertIn('last 3 JEV steps changed nothing', modes.claude_reason([step(label='A'), step(label='B'), step(label='C')]))
        self.assertEqual(modes.claude_reason([step(label='A'), step(action='wait', label='', changed=False), step(label='B')]), '')   # a wait neither counts nor breaks the run
        down, up = step('scroll', '', move='down'), step('scroll', '', move='up')
        self.assertEqual(modes.claude_reason([down, up]), '')                                                         # scrolling down then up is not the same step
        self.assertIn('repeated the same step', modes.claude_reason([down, down]))
        moving = [step('scroll', '', changed=True, move='down')] * 6
        self.assertIn('only scrolled for 6 steps', modes.claude_reason(moving)); self.assertEqual(modes.claude_reason(moving[:5]), '')


class Pointing(unittest.TestCase):
    page = {'url': 'https://shop.example/x?token=SECRET#frag', 'title': 'Shop'}

    def chooser(self, *script, **kw):
        transport = PictureJev(*script)
        return JevChooser('https://x', MODEL, 'k', transport, **kw), transport

    def test_a_picture_request_carries_the_image_the_header_and_the_questions_and_no_page_text(self):
        jev, transport = self.chooser({'operation': 'click', 'at': (0.25, 0.5)})
        pick = jev.choose_picture('buy a paddle', self.page, [{'action': 'click', 'label': 'Menu', 'result': 'ok', 'changed': True}], SHOT, why='the page lists no controls',
                                  phrases=['paddle'], position='at the top', hint='Hint: x')
        body, headers, deadline = transport.calls[0]
        self.assertEqual((body['model'], headers), (MODEL, IMAGE_HEADERS)); self.assertGreaterEqual(deadline, 12)
        (ref, asset), = body['assets'].items()
        self.assertEqual((asset['type'], asset['format'], asset['data_base64']), ('image', 'jpg', SHOT['data'])); self.assertIn(ref, body['state'])
        self.assertEqual({q['type'] for q in body['questions'].values()}, {'choice', 'box', 'noul'})
        state = body['state']
        self.assertIn('Page: shop.example/x', state); self.assertNotIn('SECRET', state); self.assertNotIn('frag', state); self.assertNotIn('Page text', state)
        self.assertIn('because the page lists no controls', state); self.assertIn('Scroll position: at the top', state); self.assertIn('Hint: x', state); self.assertIn('- click "Menu" -> ok, page changed', state)
        self.assertEqual(pick.operation, 'click'); self.assertAlmostEqual(pick.point[0], 320.0); self.assertAlmostEqual(pick.point[1], 400.0)
        self.assertEqual((pick.found, pick.spot), (0.9, 0.6))

    def test_typing_needs_a_phrase_and_a_picture_never_offers_a_dropdown(self):
        self.assertNotIn('type', picture_heads()['operation']); self.assertIn('type', picture_heads(phrases=['x'])['operation'])
        self.assertNotIn('select', picture_heads(phrases=['x'])['operation'])
        self.assertEqual(set(picture_heads(phrases=['x'])['type_text']), {'t0', 'none'})                              # a question needs two options
        jev, _ = self.chooser({'operation': 'type', 'type_text': 't1'})
        pick = jev.choose_picture('g', self.page, [], SHOT, why='w', phrases=['a', 'b'])
        self.assertEqual((pick.operation, pick.text), ('type', 'b'))

    def test_an_answer_that_does_not_say_where_is_a_miss_with_its_numbers_and_never_an_action(self):
        for found, spot in ((0.3, 0.9), (0.9, 0.1)):
            jev, _ = self.chooser({'operation': 'click', 'found': found, 'spot': spot})
            with self.assertRaises(NoSpot) as ctx:
                jev.choose_picture('g', self.page, [], SHOT, why='w')
            self.assertEqual((ctx.exception.found, ctx.exception.spot), (found, spot)); self.assertIn('did not find where to click', str(ctx.exception))
        jev, _ = self.chooser({'operation': 'scroll_down', 'found': 0.0, 'spot': 0.0})
        self.assertEqual(jev.choose_picture('g', self.page, [], SHOT, why='w').operation, 'scroll_down')                # no spot is needed to scroll

    def test_every_kind_of_bad_pointing_answer_is_refused(self):
        good = {'answers': {'target': {'type': 'box', 'box': box(0.5, 0.5), 'confidence': 0.5}, 'found': {'type': 'noul', 'noul': 0.7}}}
        self.assertEqual(validate_pointing(good)['found'], 0.7)
        for name, mutate in {'upside down': lambda d: d['answers']['target']['box'].update(top=0.9), 'outside': lambda d: d['answers']['target']['box'].update(right=1.4),
                             'no confidence': lambda d: d['answers']['target'].pop('confidence'), 'not a box': lambda d: d['answers']['target'].update(type='choice'),
                             'yes/no out of range': lambda d: d['answers']['found'].update(noul=3), 'yes/no missing': lambda d: d['answers'].pop('found')}.items():
            data = json.loads(json.dumps(good)); mutate(data)
            with self.subTest(name), self.assertRaises(ValueError):
                validate_pointing(data)

    def test_a_wrong_model_or_a_bad_choice_is_refused_with_what_jev_said_kept_for_the_trace(self):
        jev, _ = self.chooser(lambda body: picture_answer(body, model='jev-1.13.0'))
        jev.transport = lambda *a, **k: picture_answer(a[1], model='jev-1.13.0')
        with self.assertRaises(ValueError) as ctx:
            jev.choose_picture('g', self.page, [], SHOT, why='w')
        self.assertIn('model pin mismatch', str(ctx.exception)); self.assertIn('jev-1.13.0', ctx.exception.raw)


class PictureSteps(unittest.TestCase):
    def test_no_controls_means_a_picture_only_and_with_controls_the_next_step_sees_the_picture_and_the_list(self):
        s = PictureSession({'start': COVERED, 'shop': SHOP, 'item': ITEM}, hits={(640, 400): hit('Accept')})
        r, jev, events = runner(s, [{'operation': 'click', 'at': (0.5, 0.5)}, {'operation': 'click', 'click_target': 'c1'}, {'operation': 'done'}], ['{"action":"done","answer":"ok"}'], max_steps=4)
        out = r.run('buy briefs', 'https://shop.example/')
        self.assertEqual(out.status, 'done'); self.assertEqual([h['by'] for h in out.steps], ['jev', 'jev'])
        self.assertEqual(s.acts, [('clickat', None, None, 640, 400), ('click', 1, None, None, None)])               # the point first, then the numbered control
        first, second = jev.calls[0], jev.calls[1]
        self.assertIn('assets', first[0]); self.assertEqual(first[1], IMAGE_HEADERS)
        self.assertIn('assets', second[0]); self.assertEqual(second[1], IMAGE_HEADERS); self.assertIn('Page text', second[0]['state'])                  # with controls: the picture AND the list
        self.assertIn('click_target', second[0]['questions']); self.assertIn('The picture shows the browser window right now', second[0]['state'])
        self.assertEqual(out.steps[0]['label'], 'Accept'); self.assertEqual(out.steps[0]['action'], 'click')           # the history says what was done, not how
        seen = [d for k, d in events if k == 'screenshot' and d.get('seen_by') == 'jev']
        self.assertEqual(len(seen), 1); self.assertEqual(seen[0]['why'], 'the page lists no controls'); self.assertRegex(seen[0]['file'], r'^shot-\d{3}\.jpg$')
        self.assertEqual([d.get('mode') for k, d in events if k == 'step'], ['picture', 'picture'])                     # the customer's step list can say "looked at a picture"

    def test_a_button_that_places_an_order_is_never_pressed_from_a_picture(self):
        for label, kw in (('Place an order', {}), ('Pin', {'secret': True, 'type': 'password', 'editable': True})):
            with self.subTest(label):
                s = PictureSession({'start': COVERED}, hits={(640, 400): hit(label, **kw)})
                r, *_ = runner(s, [{'operation': 'click', 'at': (0.5, 0.5)}], max_steps=3)
                out = r.run('g', 'https://shop.example/')
                self.assertEqual(out.status, 'handoff'); self.assertEqual(s.acts, []); self.assertEqual(out.pending_action['label'], label)

    def test_typing_where_there_is_no_text_field_is_recorded_and_nothing_is_typed(self):
        s = PictureSession({'start': COVERED}, hits={(640, 400): hit('Just words')})
        r, *_ = runner(s, [{'operation': 'type', 'type_text': 't0', 'at': (0.5, 0.5)}], ['{"action":"stop","reason":"x"}'], max_steps=3)
        out = r.run('find boxers', 'https://shop.example/')
        self.assertEqual(s.acts, []); self.assertEqual((out.steps[0]['action'], out.steps[0]['result']), ('type', 'not_a_field'))

    def test_a_weak_spot_is_a_miss_and_claude_takes_that_step(self):
        s = PictureSession({'start': COVERED, 'shop': SHOP}, hits={})
        weak = {'operation': 'click', 'found': 0.1, 'spot': 0.9}
        r, jev, _ = runner(s, [weak, weak], ['{"action":"scroll"}'], max_steps=2)
        out = r.run('g', 'https://shop.example/')
        self.assertEqual([h['by'] for h in out.steps], ['rule', 'agent']); self.assertEqual(s.acts[-1], ('scroll', None, None, None, None))      # the first weak spot was looked at again; the second handed over, and with no controls to name the assistant could only scroll

    def test_when_the_picture_cannot_be_taken_claude_decides_instead(self):
        s = PictureSession({'start': COVERED}); s.view = lambda save=False: {'ok': False, 'error': 'no_picture'}
        r, jev, _ = runner(s, [], ['{"action":"scroll"}'], max_steps=1)
        out = r.run('g', 'https://shop.example/')
        self.assertEqual(jev.calls, []); self.assertEqual([h['by'] for h in out.steps], ['agent'])

    def test_the_trace_records_the_mode_and_the_probe_without_page_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            s = PictureSession({'start': COVERED, 'shop': SHOP, 'item': ITEM}, hits={(640, 400): hit('Accept')})
            r, *_ = runner(s, [{'operation': 'click', 'at': (0.5, 0.5)}, {'operation': 'done'}], ['{"action":"done","answer":"ok"}'], trace=tr.Trace(path), max_steps=3)
            r.run('buy briefs', 'https://shop.example/')
            rows = tr.read(path)
        mode = next(x for x in rows if x['kind'] == 'mode'); self.assertEqual((mode['mode'], mode['why']), ('picture', 'the page lists no controls'))
        probe = next(x for x in rows if x['kind'] == 'probe'); self.assertEqual(set(probe) - {'t', 'at', 'step', 'kind'}, {'found', 'tag', 'editable', 'secret'})
        jevs = [x for x in rows if x['kind'] == 'jev']; self.assertEqual(jevs[0]['mode'], 'picture'); self.assertIn('target', jevs[0]['heads'])
        self.assertNotIn('Cookie banner', json.dumps(rows))


CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


@unittest.skipUnless(Path(CHROME).exists(), 'needs Chrome and Node')
class RealRunner(unittest.TestCase):
    def test_a_popup_that_hides_every_control_is_seen_in_the_picture_accepted_and_the_next_step_sees_the_list_too(self):
        import os
        import subprocess
        import time
        from agentai_platform.browse.session import ProcessTransport, Session
        root = Path(__file__).resolve().parents[2] / 'browse'
        site = subprocess.Popen(['node', '-e', "import('./fixtures/site.mjs').then(async m=>{const s=await m.startSite();console.log(s.port)})"], cwd=root, stdout=subprocess.PIPE, text=True)
        port = int(site.stdout.readline()); self.addCleanup(site.terminate)
        env = {**os.environ, 'BROWSE_CHROME': CHROME, 'BROWSE_ALLOW_LOOPBACK': '1', 'BROWSE_OUT': tempfile.mkdtemp()}
        session = Session(ProcessTransport(['node', 'runner.mjs'], env=env, cwd=root)); self.addCleanup(session.close)
        time.sleep(1.5)
        events = []
        transport = PictureJev({'operation': 'click', 'at': (0.5, 0.45)}, {'operation': 'done'})
        ladder = Ladder(agent=scripted_llm(['{"action":"done","answer":"ok"}']), jev=JevChooser('https://x', MODEL, 'k', transport))
        out = BrowseRunner(session, ladder, on_event=lambda k, d: events.append((k, d)), max_steps=4).run('find a paddle', f'http://127.0.0.1:{port}/blocked')
        self.assertEqual(out.status, 'done', out.reason)
        self.assertEqual([(h['by'], h['action'], h['label'], h['result']) for h in out.steps], [('jev', 'click', 'Accept', 'ok')])        # the popup's button was found under the point and clicked
        first, second = transport.calls[0][0], transport.calls[1][0]
        (asset,) = first['assets'].values(); self.assertTrue(asset['data_base64'].startswith('/9j/'))                                  # a real JPEG of the real window
        self.assertIn('assets', second); self.assertIn('Paddle Shop', json.dumps(second['questions']['click_target']))                  # the cover is gone: the page lists its controls, and JEV still sees the window
        self.assertTrue(any(k == 'screenshot' and d.get('seen_by') == 'jev' for k, d in events))


class WhoIsDeciding(unittest.TestCase):
    """What the live view is told, in codes: who decides, from what, and a one-word notice when something worth a little notice happens."""
    def calls(self, session, jev_script, llm_steps=(), max_steps=4, **kw):
        seen = []
        r, _, _ = runner(session, jev_script, llm_steps, max_steps=max_steps, on_now=lambda by, mode, note: seen.append((by, mode, note)), **kw)
        return r.run('g', 'https://shop.example/'), seen

    def test_a_picture_is_announced_once_and_stays_because_jev_now_sees_the_window_every_step(self):
        s = PictureSession({'start': COVERED, 'shop': SHOP, 'item': ITEM}, hits={(640, 400): hit('Accept')})
        _, seen = self.calls(s, [{'operation': 'click', 'at': (0.5, 0.5)}, {'operation': 'click', 'click_target': 'c1'}, {'operation': 'done'}], ['{"action":"done","answer":"ok"}'])
        self.assertEqual(seen, [('jev', 'picture', 'picture')])                                                          # told once; the label stays while JEV keeps looking at the window

    def test_one_step_taken_by_claude_is_a_notice_and_then_jev_is_back_quietly(self):
        s = FpSession(FLAT, iter(range(1, 99)))
        _, seen = self.calls(s, [{'operation': 'done'}, {'operation': 'click', 'click_target': 'c2'}], [HAIKU], max_steps=2)       # JEV says done, the assistant disagrees and takes that one step
        self.assertEqual(seen, [('claude', 'controls', 'help'), ('jev', 'controls', '')])

    def test_claude_taking_a_page_and_giving_it_back_are_both_announced(self):
        s = FpSession(FLAT, iter([7, 7, 7, 8, 9, 10, 11]))
        _, seen = self.calls(s, [{'operation': 'click', 'click_target': 'c1'}] * 2 + [{'operation': 'click', 'click_target': 'c2'}], ['{"action":"click","ref":3}'], max_steps=4)
        self.assertEqual(seen, [('jev', 'controls', ''), ('claude', 'controls', 'took'), ('jev', 'controls', 'back')])

    def test_a_broken_status_light_never_stops_a_task(self):
        def boom(by, mode, note): raise RuntimeError('disk full')
        s = PictureSession({'start': COVERED, 'shop': SHOP}, hits={(640, 400): hit('Accept')})
        r, _, _ = runner(s, [{'operation': 'click', 'at': (0.5, 0.5)}], max_steps=1, on_now=boom)
        self.assertEqual(len(r.run('g', 'https://shop.example/').steps), 1)


class ClaudeTakesThePage(unittest.TestCase):
    click = lambda self, c: {'operation': 'click', 'click_target': c}

    def run_loop(self, jev_script, llm_steps, session, max_steps=6):
        r, jev, events = runner(session, jev_script, llm_steps, max_steps=max_steps)
        return r.run('g', 'https://shop.example/'), jev, events

    def test_jev_repeating_a_step_with_nothing_happening_hands_the_page_to_claude_until_a_claude_step_moves_it(self):
        s = FpSession(FLAT, iter([7, 7, 7, 8, 9, 10, 11]))             # the page stays the same for JEV's two clicks, then the assistant's step changes it
        out, jev, _ = self.run_loop([self.click('c1'), self.click('c1'), self.click('c2')], ['{"action":"click","ref":3}'], s, max_steps=4)     # the assistant does something else
        self.assertEqual([h['by'] for h in out.steps], ['jev', 'jev', 'agent', 'jev'])
        self.assertEqual(len(jev.calls), 3)                              # JEV was not asked for the assistant's step

    def test_a_step_jev_could_not_carry_out_goes_to_claude_for_that_page(self):
        s = FpSession(FLAT, iter(range(1, 99)), errors={('click', 2): 'stale'})
        out, jev, _ = self.run_loop([self.click('c2'), self.click('c1')], [HAIKU], s, max_steps=3)
        self.assertEqual([(h['by'], h['result']) for h in out.steps], [('jev', 'stale'), ('agent', 'ok'), ('jev', 'ok')])

    def test_the_ladder_says_why_it_skipped_jev(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            ladder = Ladder(agent=scripted_llm([HAIKU]), jev=JevChooser('https://x', MODEL, 'k', PictureJev()), trace=tr.Trace(path))
            c = cand.build('[1] <a> "Alpha"')
            d = ladder.decide('g', [], {'url': 'https://shop.example/', 'title': 't', 'text': ''}, c, look=Look(claude='JEV repeated the same step 2 times and nothing happened'))
            rows = tr.read(path)
        self.assertEqual(d.by, 'agent'); route = next(x for x in rows if x['kind'] == 'route')
        self.assertFalse(route['jev_asked']); self.assertIn('the page needs more than controls: JEV repeated the same step', route['skipped'])

    def test_a_run_of_scrolls_gets_the_position_and_the_hint_and_then_claude(self):
        class Scrolling(FpSession):
            pos = 0
            def snapshot(self):
                snap = super().snapshot(); snap.update(scroll=self.pos, height=2500, window=800); return snap
            def act(self, action, ref=None, value=None, label=None):
                if action == 'scroll':
                    was, self.pos = self.pos, min(self.pos + 500, 1700)
                    if self.pos == was:                                          # already at the bottom: nothing moves, so the fingerprint stays
                        out = FakeSession.act(self, action, ref, value, label); out['page_fp'] = self.fp; return out
                return super().act(action, ref, value, label)
        s = Scrolling(FLAT, iter(range(1, 99)))
        out, jev, _ = self.run_loop([{'operation': 'scroll_down'}] * 8, ['{"action":"done","answer":"ok"}'], s, max_steps=8)
        states = [c[0]['state'] for c in jev.calls]
        self.assertIn('Scroll position: at the top', states[0]); self.assertIn('Scroll position: 29% of the way down', states[1])
        self.assertIn('scroll -> ok, page changed; now 29% of the way down', states[2])                                 # what the scroll did, in words
        self.assertTrue(all('Hint:' not in st for st in states[:3])); self.assertIn('Hint: you have scrolled 3 times in a row', states[3])
        self.assertTrue(any('already at the bottom of the page, nothing more to see below' in st for st in states))
        self.assertEqual((out.status, out.answer), ('done', 'ok')); self.assertEqual(len(jev.calls), 6)                  # JEV scrolled until it stopped moving; Claude took the page and finished


if __name__ == '__main__':
    unittest.main()
