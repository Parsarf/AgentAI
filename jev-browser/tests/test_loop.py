"""The loop against a real (headless) Chrome and a tiny local shop. The stand-in for JEV is given the same request JEV would get (the page's controls, or a picture) and answers by name."""
import base64
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jevbrowse.__main__ import search_words, start_url
from jevbrowse.browser import Browser, find_chrome
from jevbrowse.jev import IMAGE_HEADERS, MODEL, Jev, JevError
from jevbrowse.log import RunLog, read, show
from jevbrowse.loop import SENSITIVE, choose_mode, control_questions, hint, pick_control, pick_shot, position, run, shot_questions

# Where each thing sits on its page, in percent of the window (left, top, width, height), so the stand-in can point at it whatever the window size.
AT = {'Search products': (10, 10, 40, 8), 'Boxer Briefs': (10, 40, 30, 8), 'Add to cart': (10, 20, 30, 8), 'Place order': (10, 50, 30, 8), 'Details': (40, 40, 20, 10),
      'Accept': (40, 40, 20, 10), 'Place order popup': (40, 40, 20, 10), 'Password': (10, 10, 40, 8), 'Open the product in a new tab': (10, 10, 50, 8),
      'Open a page that closes itself': (10, 30, 50, 8), 'Plain words': (10, 70, 30, 8), 'Size': (10, 30, 30, 8),
      'Item 1': (45, 10, 20, 8), 'Item 2': (45, 25, 20, 8), 'Item 3': (45, 40, 20, 8), 'Item 4': (45, 55, 20, 8), 'Close panel': (60, 70, 20, 8), 'Under header': (10, 2, 20, 4),
      'Far away': (10, 150, 20, 4)}


def put(label, html):
    left, top, width, height = AT[label]
    return html.format(style=f'position:absolute;left:{left}%;top:{top}%;width:{width}%;height:{height}%;display:block;box-sizing:border-box', label=label)


def link(label, href, extra=''):
    return put(label, f'<a href="{href}" style="{{style}}" {extra}>{{label}}</a>')


def popup(button, on_click, main=''):
    """A page whose controls are marked hidden (as a modal does) with the popup's only button inside a shadow root: the page lists no controls."""
    return (f'<div id=main aria-hidden="true">{main}</div><div id=host></div><script>const host = document.getElementById("host"), r = host.attachShadow({{mode: "open"}});'
            'const layer = document.createElement("div"); layer.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99";'
            f'const b = document.createElement("button"); b.textContent = "{button}"; b.style.cssText = "position:absolute;left:40%;top:40%;width:20%;height:10%";'
            f'b.addEventListener("click", () => {{ {on_click} }}); layer.appendChild(b); r.appendChild(layer);</script>')


PAGES = {
    '/': put('Search products', '<input type=search placeholder="{label}" style="{style}">') + link('Boxer Briefs', '/product'),
    '/product': link('Add to cart', '/added') + link('Place order', '/ordered'),
    '/added': '<h1>Added to cart</h1><p>Boxer Briefs, size M</p>',
    '/ordered': '<h1>Ordered</h1>',
    '/form': put('Size', '<select aria-label="{label}" style="{style}"><option>Choose</option><option>Small (S)</option><option>Medium (M)</option></select>'),
    '/login': put('Password', '<input type=password aria-label="{label}" style="{style}">'),
    '/covered': put('Details', '<button style="{style}" onclick="document.title=\'CLICKED\'">{label}</button>') + '<div style="position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:50"></div>',
    '/popup': popup('Accept', 'document.title = "ACCEPTED"'),                                      # stays covered: the page never lists a control
    '/popup-lifts': popup('Accept', 'document.getElementById("main").removeAttribute("aria-hidden"); host.remove();', link('Boxer Briefs', '/product')),
    '/popup-buy': popup('Place order', 'document.title = "ORDERED"'),
    '/drawer': ''.join(link(f'Item {i}', '/product') for i in range(1, 5)) + link('Far away', '/product')
               + '<div id=panel style="position:fixed;top:0;bottom:0;left:30%;right:0;background:#ddd;z-index:50"></div>'
               + put('Close panel', '<button style="{style};position:fixed;z-index:60" onclick="document.getElementById(\'panel\').remove(); this.remove()">{label}</button>'),
    '/sticky': link('Under header', '/product') + ''.join(link(f'Item {i}', '/product') for i in range(2, 5))
               + '<div style="position:fixed;top:0;left:0;right:0;height:8%;background:#ddd;z-index:50"></div>',
    '/long': '<div style="height:3000px">tall</div><a href="/product" style="display:block">End</a>',
    '/plain': put('Plain words', '<p style="{style}">Just some words, nothing to press</p>') + link('Boxer Briefs', '/product'),
    '/newtab': link('Open the product in a new tab', '/product', 'target=_blank') + link('Open a page that closes itself', '/closer', 'target=_blank'),
    '/closer': '<h1>Closing</h1><script>setTimeout(() => window.close(), 300)</script>',
}
HITS = []


class Shop(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        body = f'<!doctype html><title>Shop</title><body style="margin:0">{PAGES.get(self.path, "<h1>404</h1>")}'.encode()
        self.send_response(200 if self.path in PAGES else 404)
        self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


def box_at(label):
    left, top, width, height = AT[label]
    return {'left': left / 100, 'right': (left + width) / 100, 'top': top / 100, 'bottom': (top + height) / 100}


def option(options, text, key=None):
    """The id of the option whose description starts with `"text"` (or ends with `: text`), or 'none'."""
    return next((k for k, v in options.items() if (v.endswith(f': {text}') if key == 'option' else v.startswith(f'"{text}"'))), 'none')


def fake_jev(decide, seen=None):
    """decide(state text, mode) -> {'operation', 'at': what to point at (a label), 'option': a dropdown option, 'type_text'}. The stand-in answers every question in the form JEV uses."""
    def transport(endpoint, body, key, deadline, headers=None):
        if seen is not None:
            seen.append((body, headers))
        picks = decide(body['state'], 'screenshot' if 'assets' in body else 'controls')
        at = picks.get('at')
        answers = {}
        for name, q in body['questions'].items():
            if q['type'] == 'choice':
                ids = list(q['criteria'])
                if name.endswith('_target'):
                    choice = option(q['criteria'], at)
                elif name == 'select_option':
                    choice = option(q['criteria'], picks.get('option'), 'option')
                else:
                    choice = picks.get(name) or ids[0]
                top = 0.9 if len(ids) > 1 else 1.0
                rest = (1 - top) / max(1, len(ids) - 1)
                answers[name] = {'type': 'choice', 'choice': choice, 'probabilities': {i: top if i == choice else rest for i in ids}}
            elif q['type'] == 'box':
                answers[name] = {'type': 'box', 'box': box_at(at) if at else {'left': 0.0, 'right': 0.1, 'top': 0.0, 'bottom': 0.1}, 'confidence': 0.9 if at else 0.2}
            else:
                answers[name] = {'type': 'noul', 'noul': 0.9 if at else 0.1}
        return json.dumps({'model': MODEL, 'answers': answers})
    return Jev('k', transport=transport)


def script(*steps):
    """A stand-in that does the given decisions one after another, then says done."""
    it = iter(steps)
    return lambda state, mode: next(it, {'operation': 'done'})


class Units(unittest.TestCase):
    def test_goal_to_site_and_search_words(self):
        self.assertEqual(start_url('Order me underwear from youngla.com'), 'https://youngla.com/')
        self.assertEqual(start_url('look at https://shop.example/p/1 now'), 'https://shop.example/p/1')
        self.assertEqual(search_words('Order me underwear from youngla.com'), ['underwear'])

    def test_every_kind_of_bad_jev_answer_is_refused(self):
        options = {'operation': {'click': 'x', 'done': 'y'}}
        box = {'left': 0.1, 'right': 0.3, 'top': 0.2, 'bottom': 0.4}
        good = {'model': MODEL, 'answers': {'operation': {'type': 'choice', 'choice': 'click', 'probabilities': {'click': 0.9, 'done': 0.1}},
                                            'target': {'type': 'box', 'box': box, 'confidence': 0.8}, 'found': {'type': 'noul', 'noul': 0.7}}}
        self.assertEqual(Jev.check(good, options, ['target'], ['found']), {'operation': ('click', 0.9), 'target': {**box, 'confidence': 0.8}, 'found': 0.7})
        bad_choice = {'type': 'choice', 'choice': 'fly', 'probabilities': {'click': 0.9, 'done': 0.1}}
        for name, bad in {'other model': {**good, 'model': 'other'}, 'no answers': {'model': MODEL, 'answers': {}}, 'choice not offered': {**good, 'answers': {**good['answers'], 'operation': bad_choice}},
                          'box upside down': {**good, 'answers': {**good['answers'], 'target': {'type': 'box', 'box': {**box, 'top': 0.9}, 'confidence': 0.8}}},
                          'box outside the picture': {**good, 'answers': {**good['answers'], 'target': {'type': 'box', 'box': {**box, 'right': 1.4}, 'confidence': 0.8}}},
                          'box without confidence': {**good, 'answers': {**good['answers'], 'target': {'type': 'box', 'box': box}}},
                          'yes/no out of range': {**good, 'answers': {**good['answers'], 'found': {'type': 'noul', 'noul': 3}}}}.items():
            with self.subTest(name), self.assertRaises(JevError):
                Jev.check(bad, options, ['target'], ['found'])

    def test_a_screenshot_outside_what_jev_accepts_is_not_sent(self):
        jev = fake_jev(script())
        for w, h in ((2560, 1626), (200, 900), (1569, 800)):
            with self.subTest((w, h)), self.assertRaises(JevError):
                jev.ask('x', {'data': 'AAAA', 'width': w, 'height': h}, shot_questions([], None))

    def test_the_questions_offer_only_what_can_be_done(self):
        page = {'url': 'https://x.example/', 'title': '', 'text': '', 'elements': [{'ref': 1, 'tag': 'input', 'type': 'search', 'label': 'Search', 'value': '', 'checked': None, 'options': []},
                                                                                  {'ref': 2, 'tag': 'select', 'type': '', 'label': 'Size', 'value': '', 'checked': None, 'options': ['S', 'M']}]}
        self.assertNotIn('type', control_questions(page, [], None)['operation']['options'])
        self.assertIn('type', control_questions(page, ['boxers'], None)['operation']['options'])
        self.assertIn('select', control_questions(page, ['boxers'], None)['operation']['options'])
        self.assertNotIn('press_enter', control_questions(page, ['boxers'], None)['operation']['options'])
        self.assertIn('press_enter', control_questions(page, ['boxers'], {'action': 'type', 'ok': True})['operation']['options'])
        self.assertNotIn('select', shot_questions(['boxers'], None)['operation']['options'])           # a dropdown cannot be chosen from a picture
        self.assertNotIn('type', shot_questions([], None)['operation']['options'])
        self.assertIn('press_enter', shot_questions(['boxers'], {'action': 'type', 'ok': True})['operation']['options'])

    def test_a_control_answer_becomes_an_action_on_that_control(self):
        page = {'elements': [{'ref': 4, 'tag': 'select', 'type': '', 'label': 'Size', 'value': '', 'checked': None, 'options': ['S', 'M']}, {'ref': 5, 'tag': 'a', 'type': '', 'label': 'Add to cart', 'value': '', 'checked': None, 'options': []}]}
        self.assertEqual(pick_control(page, {'operation': ('click', 0.9), 'click_target': ('e5', 0.9)}, []), {'action': 'click', 'shown': 'click', 'ref': 5, 'label': 'Add to cart'})
        plan = pick_control(page, {'operation': ('select', 0.9), 'select_target': ('e4', 0.9), 'select_option': ('o4_1', 0.9)}, [])
        self.assertEqual((plan['action'], plan['ref'], plan['value']), ('select', 4, 'M'))
        self.assertIn('no listed element', pick_control(page, {'operation': ('click', 0.9), 'click_target': ('none', 0.9)}, [])['note'])
        self.assertEqual(pick_control(page, {'operation': ('done', 0.9)}, []), {'done': 'done'})

    def test_the_spot_is_the_middle_of_the_box_in_page_pixels_and_a_weak_answer_is_not_acted_on(self):
        view = {'w': 1000, 'h': 500}
        box = {'left': 0.2, 'right': 0.4, 'top': 0.5, 'bottom': 0.7, 'confidence': 0.9}
        answers = {'operation': ('click', 0.9), 'target': box, 'found': 0.9}
        plan = pick_shot(answers, [], view)
        self.assertEqual(plan['action'], 'clickat'); self.assertAlmostEqual(plan['point'][0], 300.0); self.assertAlmostEqual(plan['point'][1], 300.0)
        plan = pick_shot({**answers, 'operation': ('type', 0.9), 'type_text': ('t1', 0.9)}, ['a', 'b'], view)
        self.assertEqual((plan['action'], plan['value']), ('typeat', 'b')); self.assertAlmostEqual(plan['point'][0], 300.0)
        for weak in ({**answers, 'found': 0.2}, {**answers, 'target': {**box, 'confidence': 0.1}}):
            plan = pick_shot(weak, [], view)
            self.assertNotIn('point', plan); self.assertIn('did not find where', plan['note'])
        self.assertEqual(pick_shot({**answers, 'operation': ('scroll_down', 0.9), 'found': 0.0}, [], view)['action'], 'scroll_down')

    def test_the_mode_follows_what_is_covered_and_how_the_last_steps_went(self):
        def el(covered, in_view=True):
            return {'inView': in_view, 'covered': covered if in_view else None}
        page = lambda *els: {'elements': list(els)}
        self.assertEqual(choose_mode(page(), [])[0], 'screenshot')                                                    # no controls
        self.assertEqual(choose_mode(page(el(False), el(False), el(False)), [])[0], 'controls')
        self.assertEqual(choose_mode(page(el(True), el(True), el(False), el(True)), [])[0], 'screenshot')            # most of the window is covered
        self.assertEqual(choose_mode(page(el(True), el(False), el(False), el(False)), [])[0], 'controls')           # a sticky header over one control is not a cover
        self.assertEqual(choose_mode(page(el(True), el(True)), [])[0], 'controls')                                   # too few in the window to judge
        self.assertEqual(choose_mode(page(el(True, False), el(True, False), el(True, False), el(False)), [])[0], 'controls')   # covered but out of the window does not count
        refused = [{'action': 'click', 'label': 'Open cart', 'result': 'failed: something else is on top of it (a popup or a banner?)'}]
        self.assertEqual(choose_mode(page(el(False)), refused)[0], 'screenshot')
        again = [{'action': 'click', 'label': 'Next', 'result': 'page did not change'}] * 2
        self.assertEqual(choose_mode(page(el(False)), again)[0], 'screenshot')
        self.assertEqual(choose_mode(page(el(False)), again[:1])[0], 'controls')
        self.assertEqual(choose_mode(page(el(False)), [{'action': 'click', 'label': 'Next', 'result': 'page changed'}] * 2)[0], 'controls')
        self.assertEqual(choose_mode(page(el(False)), [{'action': 'click', 'label': 'A', 'result': 'page did not change'}, {'action': 'click', 'label': 'B', 'result': 'page did not change'}])[0], 'controls')
        self.assertEqual(choose_mode(page(el(False)), [{'action': 'none', 'label': '', 'result': 'x'}] * 2)[0], 'controls')      # "nothing fits" is the stuck rule's business

    def test_where_the_page_is_scrolled_to_is_put_in_words(self):
        page = lambda scroll: {'scroll': scroll, 'height': 3000, 'window': 800}
        self.assertEqual(position(page(0)), ('at the top; the page is about 3.8 windows tall', False))
        self.assertEqual(position(page(1100)), ('50% of the way down; the page is about 3.8 windows tall', False))
        self.assertEqual(position(page(2200)), ('at the very bottom (nothing more below); the page is about 3.8 windows tall', True))
        self.assertEqual(position({'scroll': 0, 'height': 800, 'window': 800}), ('the whole page fits in the window (nothing to scroll)', True))
        self.assertEqual(position({'url': 'x'}), (None, False))                                              # a runner that does not say: nothing is claimed

    def test_a_hint_is_sent_after_three_scrolls_in_a_row_and_it_is_only_a_hint(self):
        scroll = {'action': 'scroll_down', 'label': '', 'result': 'scrolled down'}
        click = {'action': 'click', 'label': 'Next', 'result': 'page changed'}
        page = {'scroll': 0, 'height': 3000, 'window': 800}
        self.assertIsNone(hint(page, [scroll] * 2)); self.assertIsNone(hint(page, [scroll, scroll, click])); self.assertIsNone(hint(page, []))
        text = hint(page, [click, scroll, scroll, scroll])
        self.assertIn('scrolled down 3 times in a row', text); self.assertIn('search', text); self.assertNotIn('bottom', text)
        self.assertNotIn('user', text); self.assertNotIn('must act', text)                                    # it must not invite a handover
        self.assertIn('now at the bottom', hint({'scroll': 2200, 'height': 3000, 'window': 800}, [scroll] * 5))
        self.assertIn('scrolled down 5 times', hint({'scroll': 2200, 'height': 3000, 'window': 800}, [scroll] * 5))

    def test_buttons_that_pay_send_or_delete_are_recognised_in_their_usual_wordings(self):
        for label in ('Place order', 'Place an order', 'Place my order', 'Pay now', 'Complete purchase', 'Checkout', 'Delete', 'Send message'):
            with self.subTest(label):
                self.assertTrue(SENSITIVE.search(label))
        for label in ('Add to cart', 'Open search', 'Boxer Briefs', 'SHOP NOW'):
            with self.subTest(label):
                self.assertFalse(SENSITIVE.search(label))


@unittest.skipUnless(find_chrome(), 'needs Chrome and Node')
class WithChrome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Shop)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_address[1]}'
        cls.shots = Path(tempfile.mkdtemp())
        cls.browser = Browser(headless=True, shots_dir=cls.shots)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.server.shutdown()

    def run_goal(self, decide, path='/', texts=('boxer briefs',), steps=10, seen=None, log=None):
        HITS.clear()
        jev = fake_jev(decide, seen)
        if log:
            jev.log = log
        return run('add boxer briefs to the cart', self.base + path, self.browser, jev, list(texts), steps=steps, say=lambda *_: None, log=log) if log else \
            run('add boxer briefs to the cart', self.base + path, self.browser, jev, list(texts), steps=steps, say=lambda *_: None)

    def modes(self, steps_script, path, **kw):
        """Run a script and return (status, detail, the mode of each step)."""
        log = RunLog(Path(tempfile.mkdtemp()))
        status, detail = self.run_goal(steps_script, path, log=log, **kw)
        return status, detail, [r['mode'] for r in read(log.path) if r['kind'] == 'page']

    def point(self, label):
        view = self.browser.shot()['view']
        left, top, width, height = AT[label]
        return (left + width / 2) / 100 * view['w'], (top + height / 2) / 100 * view['h']

    def open(self, path):
        reply = self.browser.open(self.base + path)
        self.assertTrue(reply['ok'], reply)
        return reply['page']

    def control(self, page, label):
        return next(e for e in page['elements'] if e['label'] == label)

    # ---- the loop, in controls mode (the normal case)
    def test_a_page_with_controls_is_done_in_controls_mode_with_no_picture_sent(self):
        seen = []
        status, detail, modes = self.modes(script({'operation': 'type', 'at': 'Search products'}, {'operation': 'click', 'at': 'Boxer Briefs'},
                                                  {'operation': 'click', 'at': 'Add to cart'}, {'operation': 'done'}), '/', seen=seen)
        self.assertEqual(status, 'done', detail); self.assertTrue(detail.endswith('/added')); self.assertNotIn('/ordered', HITS)
        self.assertEqual(modes, ['controls'] * 3 + ['screenshot'])                     # the confirmation page lists no controls, so it is looked at
        for body, headers in seen[:3]:
            self.assertNotIn('assets', body); self.assertIsNone(headers); self.assertEqual({q['type'] for q in body['questions'].values()}, {'choice'})
        self.assertIn('assets', seen[3][0])
        state = seen[0][0]['state']
        self.assertIn('Goal: add boxer briefs to the cart', state); self.assertIn('Page text', state)
        self.assertIn('Boxer Briefs', json.dumps(seen[0][0]['questions']))
        self.assertIn('type "Search products"', seen[1][0]['state'])                  # the next request remembers what was done

    def test_a_dropdown_is_chosen_in_controls_mode(self):
        status, _, _ = self.modes(script({'operation': 'select', 'at': 'Size', 'option': 'Medium (M)'}), '/form')
        self.assertEqual(status, 'done')
        self.assertEqual(self.control(self.browser.look()['page'], 'Size')['value'], 'Medium (M)')

    def test_a_button_that_places_an_order_is_never_pressed(self):
        status, detail = self.run_goal(script({'operation': 'click', 'at': 'Place order'}), path='/product')
        self.assertEqual(status, 'sensitive'); self.assertIn('Place order', detail); self.assertNotIn('/ordered', HITS)

    def test_a_password_page_stops_before_asking_jev(self):
        asked = []
        status, _ = self.run_goal(lambda state, mode: asked.append(1) or {'operation': 'done'}, path='/login')
        self.assertEqual(status, 'password'); self.assertEqual(asked, [])

    def test_nothing_that_fits_three_times_in_a_row_stops_the_run(self):
        status, _ = self.run_goal(script(*[{'operation': 'click', 'at': None}] * 3), path='/product')
        self.assertEqual(status, 'stuck')

    def test_the_step_limit_ends_a_run_that_never_finishes(self):
        status, _ = self.run_goal(lambda state, mode: {'operation': 'scroll_down'}, steps=3)
        self.assertEqual(status, 'max_steps')

    # ---- the switch to the screenshot and back
    def test_no_controls_means_a_screenshot_and_with_controls_again_it_goes_back_to_controls(self):
        seen = []
        status, detail, modes = self.modes(script({'operation': 'click', 'at': 'Accept'}, {'operation': 'click', 'at': 'Boxer Briefs'}, {'operation': 'done'}), '/popup-lifts', seen=seen)
        self.assertEqual(status, 'done', detail); self.assertTrue(detail.endswith('/product'))
        self.assertEqual(modes, ['screenshot', 'controls', 'controls'])
        first, second = seen[0], seen[1]
        self.assertEqual((first[0]['model'], first[1]), (MODEL, IMAGE_HEADERS)); self.assertEqual({q['type'] for q in first[0]['questions'].values()}, {'choice', 'box', 'noul'})
        (ref, asset), = first[0]['assets'].items()
        self.assertIn(ref, first[0]['state']); self.assertTrue(base64.b64decode(asset['data_base64']).startswith(b'\xff\xd8'))
        self.assertNotIn('Page text', first[0]['state'])
        self.assertNotIn('assets', second[0]); self.assertIn('Page text', second[0]['state'])                # back to the page's own controls: no picture

    def test_a_panel_over_the_page_switches_to_the_picture_until_it_is_closed(self):
        seen = []
        log = RunLog(Path(tempfile.mkdtemp()))
        status, detail = self.run_goal(script({'operation': 'click', 'at': 'Close panel'}, {'operation': 'click', 'at': 'Item 1'}, {'operation': 'done'}), '/drawer', seen=seen, log=log)
        pages = [r for r in read(log.path) if r['kind'] == 'page']
        self.assertEqual(status, 'done', detail); self.assertTrue(detail.endswith('/product'))
        self.assertEqual([r['mode'] for r in pages], ['screenshot', 'controls', 'controls'])
        self.assertIn('are covered', pages[0]['why']); self.assertIsNone(pages[1]['why'])
        self.assertIn('assets', seen[0][0]); self.assertIn('are covered', seen[0][0]['state']); self.assertNotIn('assets', seen[1][0])

    def test_a_header_over_one_control_is_not_a_cover(self):
        status, _, modes = self.modes(script({'operation': 'done'}), '/sticky')
        self.assertEqual((status, modes), ('done', ['controls']))

    def test_a_refused_click_makes_the_next_step_use_the_picture(self):
        status, _, modes = self.modes(script({'operation': 'click', 'at': 'Details'}, {'operation': 'done'}), '/covered')
        self.assertEqual((status, modes), ('done', ['controls', 'screenshot']))

    def test_scrolling_counts_as_the_page_changing_and_scrolling_at_the_bottom_does_not(self):
        log = RunLog(Path(tempfile.mkdtemp()))
        status, _ = self.run_goal(script(*[{'operation': 'scroll_down'}] * 8), '/long', log=log, steps=8)
        acts = [r['changed'] for r in read(log.path) if r['kind'] == 'act']
        self.assertEqual(status, 'max_steps'); self.assertTrue(acts[0]); self.assertFalse(acts[-1])         # moved at first, then the bottom was reached

    def test_jev_is_told_where_it_is_on_the_page_gets_a_hint_after_three_scrolls_and_the_run_carries_on(self):
        seen = []
        status, _ = self.run_goal(lambda state, mode: {'operation': 'scroll_down'}, '/long', steps=9, seen=seen)
        self.assertEqual(status, 'max_steps')                                                                # a hint, not a handover: the run goes on to its limit
        states = [body['state'] for body, _ in seen]
        self.assertIn('Scroll position: at the top', states[0])
        self.assertIn('% of the way down', states[1])
        self.assertTrue(all('Hint:' not in st for st in states[:3]))
        self.assertIn('Hint: you have scrolled down 3 times in a row', states[3])
        self.assertIn('scrolled down, now', states[1])                                                       # what the scroll did, in words
        self.assertTrue(any('at the very bottom' in st and 'already at the bottom of the page, nothing more to see below' in st for st in states))
        self.assertTrue(any('and you are now at the bottom of the page' in st for st in states))

    def test_the_page_reader_says_which_controls_are_in_the_window_and_which_are_covered(self):
        page = self.open('/drawer')
        by = {e['label']: e for e in page['elements']}
        self.assertEqual([(by[f'Item {i}']['inView'], by[f'Item {i}']['covered']) for i in range(1, 5)], [(True, True)] * 4)
        self.assertEqual((by['Close panel']['inView'], by['Close panel']['covered']), (True, False))
        self.assertEqual((by['Far away']['inView'], by['Far away']['covered']), (False, None))

    def test_still_no_controls_after_the_action_means_another_screenshot(self):
        status, _, modes = self.modes(script({'operation': 'click', 'at': 'Accept'}, {'operation': 'click', 'at': 'Accept'}, {'operation': 'done'}), '/popup')
        self.assertEqual(status, 'done'); self.assertEqual(modes, ['screenshot'] * 3)
        self.assertEqual(self.browser.look()['page']['title'], 'ACCEPTED')                              # the click in the shadow root really happened

    def test_a_button_that_places_an_order_is_not_pressed_in_screenshot_mode_either(self):
        status, detail = self.run_goal(script({'operation': 'click', 'at': 'Place order popup'}), path='/popup-buy')
        self.assertEqual(status, 'sensitive'); self.assertIn('Place order', detail)
        self.assertEqual(self.browser.look()['page']['title'], 'Shop')                                  # it was never clicked

    def test_pointing_at_nothing_in_screenshot_mode_three_times_is_stuck(self):
        status, detail = self.run_goal(script(*[{'operation': 'click', 'at': None}] * 3), path='/popup')
        self.assertEqual(status, 'stuck'); self.assertIn('did not find where', detail)

    def test_the_picture_fits_what_jev_accepts(self):
        self.open('/')
        shot = self.browser.shot()
        self.assertTrue(shot['ok'])
        self.assertTrue(280 <= shot['width'] <= 1568 and 280 <= shot['height'] <= 1568 and 78_400 <= shot['width'] * shot['height'] <= 2_458_624, (shot['width'], shot['height']))
        self.assertTrue((self.shots / shot['file']).exists())

    # ---- what the browser side does on its own (talking to Chrome directly, no libraries)
    def test_what_is_under_a_point_is_named_even_through_a_shadow_root(self):
        self.open('/popup')
        hit = self.browser.probe(*self.point('Accept'))['hit']
        self.assertEqual((hit['label'], hit['tag'], hit['editable']), ('Accept', 'button', False))
        self.open('/')
        hit = self.browser.probe(*self.point('Search products'))['hit']
        self.assertEqual((hit['label'], hit['editable']), ('Search products', True))

    def test_pointing_at_words_that_are_not_a_text_field_is_not_typed_into(self):
        status, detail = self.run_goal(script(*[{'operation': 'type', 'at': 'Plain words'}] * 3), path='/popup')
        self.assertEqual(status, 'stuck')
        self.open('/plain')
        self.assertIn('no text field', self.browser.act('typeat', None, *self.point('Plain words'), 'x')['error'])

    def test_typing_choosing_and_clicking_by_number_work_and_the_next_look_shows_the_result(self):
        page = self.open('/')
        self.assertTrue(self.browser.act('type', self.control(page, 'Search products')['ref'], value='boxer briefs')['ok'])
        self.assertEqual(self.control(self.browser.look()['page'], 'Search products')['value'], 'boxer briefs')
        page = self.open('/form')
        self.assertTrue(self.browser.act('select', self.control(page, 'Size')['ref'], value='medium')['ok'])        # matched loosely: "medium" is "Medium (M)"
        self.assertEqual(self.browser.act('select', self.control(page, 'Size')['ref'], value='Gigantic')['error'], 'no such option')
        page = self.open('/product')
        self.assertTrue(self.browser.act('click', self.control(page, 'Add to cart')['ref'])['ok'])
        self.assertTrue(self.browser.look()['page']['url'].endswith('/added'))

    def test_a_click_by_number_on_something_covered_is_refused_and_says_why(self):
        page = self.open('/covered')
        reply = self.browser.act('click', self.control(page, 'Details')['ref'])
        self.assertFalse(reply['ok']); self.assertIn('on top of it', reply['error'])
        self.assertEqual(self.browser.look()['page']['title'], 'Shop')

    def test_a_click_at_a_point_goes_to_whatever_is_there_as_it_would_for_a_person(self):
        self.open('/covered')
        self.assertTrue(self.browser.act('clickat', None, *self.point('Details'))['ok'])
        self.assertEqual(self.browser.look()['page']['title'], 'Shop')                  # the overlay took the click
        self.assertEqual(self.browser.probe(*self.point('Details'))['hit']['label'], '')

    def test_typing_at_a_point_goes_into_the_field(self):
        self.open('/')
        self.assertTrue(self.browser.act('typeat', None, *self.point('Search products'), 'boxer briefs')['ok'])
        self.assertEqual(self.control(self.browser.look()['page'], 'Search products')['value'], 'boxer briefs')

    def test_a_link_that_opens_a_new_tab_is_followed(self):
        page = self.open('/newtab')
        self.assertTrue(self.browser.act('click', self.control(page, 'Open the product in a new tab')['ref'])['ok'])
        self.assertTrue(self.browser.look()['page']['url'].endswith('/product'))

    def test_when_the_tab_closes_itself_the_next_look_carries_on_in_another_tab(self):
        page = self.open('/newtab')
        self.assertTrue(self.browser.act('click', self.control(page, 'Open a page that closes itself')['ref'])['ok'])
        time.sleep(0.6)
        seen = self.browser.look()
        self.assertTrue(seen['ok']); self.assertTrue(seen['page']['url'].startswith('http'), seen['page']['url'])

    def test_the_runner_has_no_libraries(self):
        root = Path(__file__).resolve().parent.parent
        self.assertFalse((root / 'runner' / 'node_modules').exists()); self.assertFalse((root / 'runner' / 'package.json').exists())
        self.assertNotIn('playwright', (root / 'runner' / 'runner.mjs').read_text().lower().replace('no libraries', ''))

    def test_the_log_holds_the_full_story_of_a_run(self):
        folder = Path(tempfile.mkdtemp())
        log = RunLog(folder)
        browser = Browser(headless=True, log=log, shots_dir=log.shots_dir)
        try:
            HITS.clear()
            jev = fake_jev(script({'operation': 'click', 'at': 'Place order'}))
            jev.log = log
            status, _ = run('add boxer briefs', self.base + '/product', browser, jev, ['boxer briefs'], say=lambda *_: None, log=log)
        finally:
            browser.close()
        self.assertEqual(status, 'sensitive')
        rows = read(log.path)
        kinds = [r['kind'] for r in rows]
        for kind in ('run_start', 'browser_start', 'runner', 'runner_event', 'page', 'jev_call', 'jev_answer', 'decision', 'safety_stop', 'end'):
            self.assertIn(kind, kinds)
        page = next(r for r in rows if r['kind'] == 'page'); self.assertEqual(page['mode'], 'controls'); self.assertEqual(page['shot'], 'step-001.jpg')
        call = next(r for r in rows if r['kind'] == 'jev_call')
        self.assertIn('Goal: add boxer briefs', call['state']); self.assertIn('click_target', call['questions']); self.assertIn('"answers"', call['raw']); self.assertIsNone(call['image'])
        self.assertEqual(next(r for r in rows if r['kind'] == 'decision')['label'], 'Place order')
        lines = []
        show(log.path, out=lines.append)
        text = '\n'.join(lines)
        self.assertIn('Place order', text); self.assertIn('controls mode', text); self.assertIn('summary:', text); self.assertTrue((folder / 'latest.jsonl').exists())

    def test_a_screenshot_step_is_logged_with_its_picture_the_box_and_the_spot(self):
        log = RunLog(Path(tempfile.mkdtemp()))
        self.run_goal(script({'operation': 'click', 'at': 'Accept'}), path='/popup', log=log)
        rows = read(log.path)
        call = next(r for r in rows if r['kind'] == 'jev_call')
        self.assertRegex(call['image']['file'], r'^step-\d{3}\.jpg$'); self.assertTrue((self.shots / call['image']['file']).exists())
        self.assertNotIn('data_base64', json.dumps(call)); self.assertIn('target', call['asked'])
        answer = next(r for r in rows if r['kind'] == 'jev_answer'); self.assertEqual(answer['mode'], 'screenshot'); self.assertGreater(answer['found'], 0.5)
        decision = next(r for r in rows if r['kind'] == 'decision'); self.assertEqual((decision['action'], decision['label'], decision['hit']['tag']), ('click', 'Accept', 'button'))


if __name__ == '__main__':
    unittest.main()
