"""The rules that came out of the browsing reliability work (November 2026): each one answers a failure reproduced in the lab (browser-opt/lab) or read in production records.

They are all pure logic: scripted pages, a scripted JEV and a scripted assistant. What the runner does in a real page is tested in browse/test/runner.test.mjs.
"""
import unittest

from agentai_platform.browse import candidates as cand
from agentai_platform.browse.ladder import OP_FLOOR, TEXT_CHUNK, Ladder, JevChooser, Look, control_line, page_words, parse_decision, render, words_block
from agentai_platform.browse.loop import BrowseRunner, Policy
from agentai_platform.browse.session import RunnerError, Session
from tests.test_browse import FLAT, MODEL, FpSession, ScriptedJev, jev_answer, live, scripted_llm

URL = 'https://shop.example/'
DONE = '{"action":"done","answer":"ok"}'


def unsure(op, **picks):
    """A JEV answer that is valid and names `op`, with a probability under the floor."""
    return lambda body: jev_answer(body, {'operation': op, **picks}, p=0.4)


def run(session, jev_script, llm_steps, **kw):
    llm, jev = scripted_llm(list(llm_steps)), ScriptedJev(*jev_script)
    r = BrowseRunner(session, live(llm, jev), wait=lambda s: None, **kw).run('g', URL)
    return r, llm, jev


class AnUnsureStepGoesToTheAssistant(unittest.TestCase):
    def test_a_step_jev_gives_less_than_even_odds_is_the_assistants_and_the_next_is_jevs_again(self):
        self.assertEqual(OP_FLOOR, 0.5)
        r, llm, jev = run(FpSession(FLAT, iter(range(99))), [unsure('click', click_target='c2'), {'operation': 'click', 'click_target': 'c3'}], ['{"action":"click","ref":1}'], max_steps=2)
        self.assertEqual([(h['by'], h['label']) for h in r.steps], [('agent', 'Alpha'), ('jev', 'Gamma')])
        self.assertEqual(llm.why, ['the planner was unsure of this step']); self.assertIn('its best guess was to click', llm.hints[0])

    def test_a_scroll_or_a_wait_is_never_held_back_for_being_unsure(self):
        r, llm, _ = run(FpSession(FLAT, iter(range(99))), [unsure('scroll_down'), {'operation': 'done'}], [DONE], max_steps=2)
        self.assertEqual([(h['by'], h['action']) for h in r.steps], [('jev', 'scroll')]); self.assertEqual(llm.why, ['check that the goal is achieved'])

    def test_the_third_step_taken_from_jev_in_one_task_gives_the_assistant_the_task(self):
        click = '{"action":"click","ref":1}'
        r, llm, jev = run(FpSession(FLAT, iter(range(99))), [unsure('click', click_target='c2')] * 5, [click, click, click, DONE], max_steps=5)
        self.assertEqual(len(jev.bodies), 3)                                    # asked three times; after that the assistant has the task and JEV is not asked
        self.assertEqual((r.status, [h['by'] for h in r.steps]), ('done', ['agent'] * 3))


class WhatTheAssistantIsShown(unittest.TestCase):
    def test_a_control_carries_its_state_and_a_dropdown_its_options(self):
        c = cand.build('[1] <input type=checkbox> "Gift wrap"\n[2] <select> "Size"\n[3] <input type=text> "Name"\n[4] <button> "Medium"',
                       elements=[{'ref': 1, 'label': 'Gift wrap', 'checked': True, 'in_view': True, 'covered': False}, {'ref': 2, 'label': 'Size', 'value': 'M', 'options': ['S', 'M', 'L']},
                                 {'ref': 3, 'label': 'Name', 'value': 'Jo', 'in_view': False}, {'ref': 4, 'label': 'Medium', 'role': 'button', 'checked': True, 'covered': True, 'in_view': True}])
        lines = [control_line(x) for x in c]
        self.assertEqual(lines[0], 'c1: click "Gift wrap" (checked)'); self.assertEqual(lines[1], 'c2: select "Size" (now: "M"; options: S | M | L)')
        self.assertEqual(lines[2], 'c3: type "Name" (now: "Jo"; off screen)'); self.assertEqual(lines[3], 'c4: click "Medium" (selected; covered by something else)')
        self.assertEqual(control_line(cand.build('[1] <a> "Home"')[0]), 'c1: click "Home"')              # an engine that sends no state: the line it always was

    def test_a_page_that_fits_is_shown_whole_and_a_long_one_from_the_window_with_read_to_go_on(self):
        short = {'full': 'A' * 500, 'full_at': 0, 'text': 'A' * 500}
        self.assertEqual(page_words(short), ('A' * 500, 0, 500)); self.assertIn('the whole page', words_block(short))
        long = {'full': ''.join(chr(65 + i // 1000 % 26) for i in range(20000)), 'full_at': 9000, 'text': 'x'}
        words, at, total = page_words(long)
        self.assertEqual((at, len(words), total), (8800, TEXT_CHUNK, 20000)); self.assertIn('action "read" shows the next part', words_block(long)); self.assertIn('The first 8800 characters of the page are not shown', words_block(long))
        self.assertIn('3200 more characters you have NOT seen', words_block(long)); self.assertIn('Do not answer about the whole page', words_block(long))
        self.assertEqual(page_words({**long, 'read_from': 16000})[1:], (16000, 20000)); self.assertIn('This is the end of the page', words_block({**long, 'read_from': 16000}))
        self.assertEqual(page_words({**long, 'full_at': 900})[1], 0)                                       # a few lines above the window are shown with it, not left as a part of their own
        tail = page_words({**long, 'read_from': 11000}); self.assertEqual((tail[1], len(tail[0])), (11000, 9000))      # ... and a short remainder below comes with the part before it
        self.assertEqual(page_words({'text': 'only the old field'}), ('only the old field', 0, 18))      # an engine that sends no `full`

    def test_a_page_the_assistant_just_read_is_not_sent_whole_again(self):
        page = {'full': 'W' * 5000, 'text': 'in the window\n[below the window]\nfurther down', 'same_words': True, 'url': URL, 'title': 't'}
        block = words_block(page)
        self.assertIn('in the window', block); self.assertNotIn('further down', block); self.assertNotIn('WWWW', block); self.assertIn('as it did in your previous result', block)

    def test_reading_on_sends_only_the_next_words(self):
        page = {'full': 'W' * 20000, 'full_at': 0, 'read_from': 7800, 'text': 'x', 'url': URL, 'title': 't'}
        out = render('g', [{'by': 'agent', 'action': 'read', 'result': 'ok'}], page, cand.build('[1] <a> "Home"'))
        self.assertTrue(out.startswith('You are reading on.')); self.assertNotIn('Interactive elements', out); self.assertIn('characters 7800 to 15800 of 20000', out)
        self.assertIn('4200 more characters you have NOT seen', out)

    def test_read_is_a_step_the_assistant_may_send(self):
        d = parse_decision('{"action":"read"}', [], 'agent')
        self.assertEqual((d.kind, d.action['action']), ('act', 'read'))


class LongPage(FpSession):
    def snapshot(self):
        snap = super().snapshot(); snap.update(full='P' * 20000, full_at=0, scroll=0, height=9000, window=800); return snap


class TheLoop(unittest.TestCase):
    def test_reading_on_moves_nothing_in_the_browser_and_shows_the_next_part(self):
        s = LongPage(FLAT, iter(range(99)))
        llm = scripted_llm(['{"action":"read"}', '{"action":"read"}', '{"action":"read"}', DONE])
        seen = []
        inner = llm
        def agent(goal, history, page, candidates, handover, look):
            seen.append(page_words(page)[1]); return inner(goal, history, page, candidates, handover, look)
        r = BrowseRunner(s, Ladder(agent=agent, jev=JevChooser('https://x', MODEL, 'k', ScriptedJev({'operation': 'done'}))), max_steps=5, wait=lambda x: None).run('g', URL)
        self.assertEqual(r.status, 'done'); self.assertEqual([c for c in s.log if c[0] == 'act'], [])       # the page was never touched
        self.assertEqual(seen, [0, 7800, 15600, 15600])                                                     # each read starts where the last ended (less a little overlap); at the end it stays
        self.assertIn('end of the page text', r.steps[-1]['note'])

    def test_a_wait_for_a_page_that_is_still_loading_is_not_a_loop(self):
        fps = iter([1, 1, 1, 1, 1, 2])                                           # five looks the same, then the page has loaded
        r, llm, jev = run(FpSession(FLAT, fps), [{'operation': 'wait'}] * 5 + [{'operation': 'done'}], [DONE], max_steps=7)
        self.assertEqual((r.status, [h['action'] for h in r.steps]), ('done', ['wait'] * 5))                 # it used to end as "repeating the same step" on the fourth wait

    def test_five_waits_with_nothing_changing_bring_the_assistant_and_ten_end_the_task(self):
        r, llm, jev = run(FpSession(FLAT, iter([1] * 99)), [{'operation': 'wait'}] * 12, ['{"action":"wait"}'] * 3, max_steps=14)
        self.assertEqual((r.status, r.reason), ('stuck', 'the page did not finish loading')); self.assertIn('JEV has waited 5 times', llm.why[0])

    def test_a_change_that_arrives_after_the_step_was_judged_is_credited_to_it(self):
        class Late(FpSession):
            def snapshot(self):
                snap = super().snapshot()
                if any(c[0] == 'act' for c in self.log): snap['page_fp'] = 'later'      # the page changed a moment after the click was reported
                return snap
        r, llm, jev = run(Late(FLAT, iter([1] * 99)), [{'operation': 'click', 'click_target': 'c2'}, {'operation': 'done'}], [DONE], max_steps=2)
        self.assertIs(r.steps[0]['changed'], True); self.assertNotIn('did not change', jev.bodies[1]['state'])

    def test_the_browsers_own_error_page_is_loaded_again_and_never_called_a_site_that_is_not_allowed(self):
        class Flaky(FpSession):
            fails = 1
            def snapshot(self):
                snap = super().snapshot()
                if self.fails: snap['url'] = 'chrome-error://chromewebdata/'
                return snap
            def open(self, url):
                self.fails = max(0, self.fails - 1) if self.log else self.fails; return super().open(url)
        s = Flaky(FLAT, iter(range(99)))
        r, llm, jev = run(s, [{'operation': 'done'}], [DONE], max_steps=3)
        self.assertEqual(r.status, 'done'); self.assertEqual(r.steps[0]['action'], 'reload'); self.assertEqual(len([c for c in s.log if c[0] == 'open']), 2)
        s = Flaky(FLAT, iter(range(99))); s.fails = 99
        r, *_ = run(s, [], [], max_steps=6)
        self.assertEqual((r.status, r.reason), ('error', 'the site stopped answering, so the page could not be loaded'))

    def test_a_page_that_cannot_be_read_once_is_read_again(self):
        class Hiccup(FpSession):
            bad = 1
            def snapshot(self):
                if self.bad:
                    self.bad -= 1; return {'ok': False, 'error': 'timeout'}
                return super().snapshot()
        r, *_ = run(Hiccup(FLAT, iter(range(99))), [{'operation': 'done'}], [DONE], max_steps=1)
        self.assertEqual(r.status, 'done')
        s = Hiccup(FLAT, iter(range(99))); s.bad = 2
        r, *_ = run(s, [], [], max_steps=1)
        self.assertEqual((r.status, r.reason), ('error', 'could not read the page'))

    def test_scrolling_is_not_offered_where_it_cannot_move_anything(self):
        class AtTop(FpSession):
            def snapshot(self):
                snap = super().snapshot(); snap.update(scroll=0, height=3000, window=800); return snap
        r, llm, jev = run(AtTop(FLAT, iter(range(99))), [{'operation': 'done'}], [DONE], max_steps=1)
        ops = jev.bodies[0]['questions']['operation']['criteria']
        self.assertNotIn('scroll_up', ops); self.assertIn('scroll_down', ops)
        self.assertIn('whole page is then read', ops['done']); self.assertIn('not to read', ops['scroll_down'])      # JEV sees one window; the assistant reads the page

    def test_a_restarted_browser_is_said_to_the_deciders(self):
        class Restarted(FpSession):
            def snapshot(self):
                snap = super().snapshot(); snap['restarted'] = not self.log[1:]; return snap
        r, llm, jev = run(Restarted(FLAT, iter(range(99))), [{'operation': 'done'}], [DONE], max_steps=1)
        self.assertIn('the browser stopped working and was started again', jev.bodies[0]['state'])


class HumanChecks(unittest.TestCase):
    def test_a_challenge_is_recognised_under_a_long_menu_and_an_article_about_them_is_not(self):
        menu = 'All Images Videos News Maps Shopping Settings ' * 60
        self.assertTrue(cand.page_is_bot_check('Search', menu + 'Unfortunately, bots use DuckDuckGo too. Please complete the following challenge to confirm this search was made by a human.'))
        self.assertTrue(cand.page_is_bot_check('x', menu + 'Our systems have detected unusual traffic from your computer network.'))
        self.assertFalse(cand.page_is_bot_check('News', 'How a captcha works and why bots defeat it. ' * 80))
        self.assertTrue(cand.page_is_bot_check('Just a moment...', 'Checking your browser'))                  # the short-page rule is unchanged


class OnePageScript(unittest.TestCase):
    def test_the_three_engines_run_the_same_page_script(self):
        import subprocess
        import sys
        from pathlib import Path
        script = Path(__file__).resolve().parents[2] / 'browse' / 'sync-page-scripts.py'
        done = subprocess.run([sys.executable, str(script), '--check'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr or done.stdout)       # the extension's and the cell engine's copies are generated from browse/runner.mjs


class ASiteThatRefuses(unittest.TestCase):
    def test_an_access_denied_page_is_a_refusal_and_a_challenge_or_an_ordinary_page_is_not(self):
        self.assertTrue(cand.page_is_refusal('Access Denied', "You don't have permission to access this server. Reference #18.cfe", 403))
        self.assertTrue(cand.page_is_refusal('Error Page', 'SORRY Something went wrong on our end. Please go back and try again.', 403))
        self.assertFalse(cand.page_is_refusal('Just a moment...', 'Verify you are human by completing the action below', 403))       # something the customer can solve: the human-check path
        self.assertFalse(cand.page_is_refusal('Access Denied', 'no permission', None))                                               # an engine that does not report the status claims nothing
        self.assertFalse(cand.page_is_refusal('Shop', 'Welcome ' * 400, 403)); self.assertFalse(cand.page_is_refusal('Shop', 'Welcome', 200))

    def test_the_task_asks_once_more_then_ends_with_the_refusal_as_its_reason_and_tells_the_assistant_what_to_do_instead(self):
        from agentai_platform.browse.adapter import findings, is_refused, is_wall
        from agentai_platform.browse.loop import REFUSED_REASON
        class Denied(FpSession):
            def snapshot(self):
                snap = super().snapshot(); snap.update(title='Access Denied', text="You don't have permission to access this server.", http_status=403); return snap
        s = Denied(FLAT, iter(range(99)))
        r, llm, jev = run(s, [], [], max_steps=5)
        self.assertEqual((r.status, r.reason), ('blocked', REFUSED_REASON)); self.assertEqual(len(jev.bodies), 0)       # no model was asked about a page that is not the site's
        self.assertEqual(len([c for c in s.log if c[0] == 'open']), 2); self.assertEqual([c for c in s.log if c[0] == 'act'], [])
        final = {'state': r.status, 'reason': r.reason, 'url': 'https://www.shop.example/'}
        self.assertTrue(is_refused(final) and is_wall(final))
        told = findings(final)
        self.assertIn("the site refuses Lumina's browser", told); self.assertIn('web_search and web_fetch', told); self.assertIn('Do not send this site to the browser again', told)
        self.assertNotIn('Live view', told)                                    # there is nothing for the customer to do in this browser either

    def test_the_assistant_may_clear_a_field_with_an_empty_text_and_jev_may_not_type_nothing(self):
        c = cand.build('[1] <input type=text> "Search"')
        self.assertEqual(parse_decision('{"action":"type","ref":1,"value":""}', c, 'agent').action['value'], '')
        with self.assertRaises(ValueError): parse_decision('{"action":"type","ref":1,"value":""}', c, 'haiku')


CART = {'start': {'url': 'https://shop.example/cart', 'snap': '[1] <a> "Keep shopping"\n[2] <button> "Remove"\n[3] <button> "Place order"\n[4] <button> "Checkout"', 'text': 'Your cart: joggers, Small', 'go': {2: 'empty'}},
        'empty': {'url': 'https://shop.example/cart', 'snap': '[1] <a> "Keep shopping"', 'text': 'Your cart is empty'}}


class AButtonOnlyTheCustomerMayAllow(unittest.TestCase):
    def go(self, agent_steps, answer, **kw):
        asked = []
        def ask_gate(question, step):
            asked.append(question); return answer, 0
        s = FpSession(CART, iter(range(99)))
        llm = scripted_llm(list(agent_steps))
        kw.setdefault('policy', Policy(press_approval=lambda: True))              # the owner's switch `browser_press_approval` is on in these tests, unless one says otherwise
        r = BrowseRunner(s, Ladder(agent=llm), ask_gate=ask_gate, wait=lambda x: None, max_steps=4, **kw).run('g', 'https://shop.example/cart')
        return r, s, asked

    def test_while_the_owners_switch_is_off_nobody_is_asked_and_nothing_is_pressed(self):
        def broken():
            raise OSError('the switch file cannot be read')
        for policy in (Policy(), Policy(press_approval=lambda: False), Policy(press_approval=broken), Policy(press_approval=lambda: 'yes')):
            r, s, asked = self.go(['{"action":"click","ref":2}'], {'option': 'o1'}, policy=policy)
            self.assertEqual((r.status, r.pending_action['label'], asked), ('handoff', 'Remove', [])); self.assertEqual([c for c in s.log if c[0] == 'act'], [])

    def test_with_the_customers_yes_the_button_is_pressed_and_the_task_goes_on(self):
        r, s, asked = self.go(['{"action":"click","ref":2}', '{"action":"click","ref":2}', DONE], {'option': 'o1'})
        self.assertEqual(r.status, 'done'); self.assertEqual([c for c in s.log if c[0] == 'act'], [('act', 'click', 2, None)])
        self.assertEqual(len(asked), 1); self.assertIn('press "Remove" on shop.example', asked[0]['title']); self.assertEqual(asked[0]['use'], 'approval')
        self.assertEqual([o['label'] for o in asked[0]['options']], ['Yes, press it', 'No, I will do it myself'])

    def test_a_no_or_no_answer_is_the_hand_off_it_always_was(self):
        for answer in ({'option': 'o2'}, None):
            r, s, asked = self.go(['{"action":"click","ref":2}'], answer)
            self.assertEqual((r.status, r.pending_action['label']), ('handoff', 'Remove')); self.assertEqual([c for c in s.log if c[0] == 'act'], [])

    def test_a_button_that_pays_or_orders_is_never_asked_about_and_never_pressed(self):
        for ref, label in ((3, 'Place order'), (4, 'Checkout')):
            r, s, asked = self.go(['{"action":"click","ref":%d}' % ref], {'option': 'o1'})
            self.assertEqual((r.status, r.pending_action['label'], asked), ('handoff', label, [])); self.assertEqual([c for c in s.log if c[0] == 'act'], [])
        for label in ('Pay now', 'Buy now', 'Place your order', 'Complete purchase', 'Subscribe', 'Donate', 'Book now', 'Order'):
            self.assertTrue(cand.PAYMENT.search(label), label)
        for label in ('Remove', 'Delete', 'Send', 'Submit', 'Confirm', 'Sign out', 'Unsubscribe', 'Publish'):
            self.assertFalse(cand.PAYMENT.search(label), label); self.assertTrue(cand.SENSITIVE.search(label), label)

    def test_without_a_way_to_ask_it_is_the_hand_off(self):
        s = FpSession(CART, iter(range(99)))
        r = BrowseRunner(s, Ladder(agent=scripted_llm(['{"action":"click","ref":2}'])), wait=lambda x: None, max_steps=2).run('g', 'https://shop.example/cart')
        self.assertEqual(r.status, 'handoff')


class WhatAssistantsActuallySend(unittest.TestCase):
    """Production, 2026-11-22: the first call of every browser task was refused. The runtime keeps tool schemas out of the prompt, so the assistant guessed the names."""
    def test_a_task_is_taken_with_the_names_assistants_use_for_the_address_and_the_steps(self):
        from agentai_platform.browse.adapter import TOOL as BROWSER_TOOL, BadTask, clean_task
        sent = {'task': 'Go to clothes.example and find the socks collection.', 'url': 'https://www.clothes.example', 'done_when': 'A list is reported.'}      # the shape of the call that was refused
        t = clean_task(sent)
        self.assertEqual((t['site'], t['start_url'], t['done_when']), ('clothes.example', 'https://www.clothes.example/', 'A list is reported.'))
        self.assertEqual(clean_task({'goal': 'List the new arrivals and their prices', 'website': '"shop.example/collections/new"'})['start_url'], 'https://shop.example/collections/new')
        self.assertEqual(clean_task({'task': 'Find the cheapest paddle on https://shop.example/paddles?sort=price and report it.'})['start_url'], 'https://shop.example/paddles?sort=price')   # an address written in the task
        self.assertEqual(clean_task({'task': 'List the paddles', 'site': 'shop.example', 'steps': '1. Open the page.\n2. Read the list.\n- Report names and prices.'})['steps'],
                         ['Open the page.', 'Read the list.', 'Report names and prices.'])
        many = clean_task({'task': 'List the paddles', 'site': 'shop.example', 'steps': ['Open the shop'] * 30 + ['', 7]})['steps']
        self.assertEqual(len(many), 12)                                                           # too many steps are cut, an unreadable one is left out: neither refuses the task
        self.assertEqual(BROWSER_TOOL['inputSchema']['required'], ['task'])                       # the runtime refuses a call that breaks the schema before Lumina can read it

    def test_what_may_be_opened_is_exactly_what_it_was(self):
        from agentai_platform.browse.adapter import BadTask, clean_task
        for bad in ({'task': 'do the thing on the internet please'},                              # no address anywhere
                    {'task': 'Open the admin page', 'url': 'http://user:pw@host.example/'}, {'task': 'Open the local page', 'url': 'http://127.0.0.1/'},
                    {'task': 'Open the internal page', 'site': 'http://intranet/'}, {'task': 'Open the file listing', 'url': 'file:///etc/passwd'},
                    {'task': 'Open the page on the port', 'site': 'shop.example:8443'}, {'task': 'short', 'site': 'shop.example'}, {'site': 'shop.example'}, 'not arguments'):
            with self.assertRaises(BadTask, msg=repr(bad)): clean_task(bad)

    def test_a_step_is_read_in_its_close_spellings_and_a_refusal_says_what_to_send(self):
        from agentai_platform.browse.adapter import STEP as STEP_TOOL, BadTask, clean_step
        self.assertEqual(clean_step({'action': 'type', 'ref': 'c12', 'text': 'socks'}), {'action': 'type', 'value': 'socks', 'ref': 12})
        self.assertEqual(clean_step({'action': 'scroll_down', 'ref': 3}), {'action': 'scroll', 'value': 'down'})        # a number left on a scroll is dropped, not a reason to refuse
        self.assertEqual(clean_step({'action': 'press', 'key': 'enter'}), {'action': 'press', 'value': 'Enter'})
        self.assertEqual(clean_step({'action': 'Scroll', 'direction': 'UP'}), {'action': 'scroll', 'value': 'up'})
        self.assertEqual(clean_step({'action': 'finish', 'result': 'Two styles, both out of stock.'}), {'action': 'done', 'answer': 'Two styles, both out of stock.'})
        self.assertEqual(clean_step({'action': 'ask', 'question': 'Which size?', 'field': 'size', 'options': ['c4', 5, '[6]']}), {'action': 'ask', 'question': 'Which size?', 'field': 'size', 'options': [4, 5, 6]})
        for bad in ({'action': 'navigate', 'value': 'https://evil.example/'}, {'action': 'click', 'ref': 'the blue one'}, {'action': 'type', 'ref': 2, 'value': ['x']}, {}, None):
            with self.assertRaises(BadTask, msg=repr(bad)): clean_step(bad)
        self.assertNotIn('enum', STEP_TOOL['inputSchema']['properties']['action'])
        c = cand.build('[1] <input type=text> "Search"\n[2] <button> "Add to cart"')
        for step, says in (('{"action":"click","ref":9}', 'there is no control 9 in the list above'), ('{"action":"click"}', 'click needs ref'), ('{"action":"type","ref":2,"value":"x"}', 'control 2 takes click, not type'),
                           ('{"action":"type","ref":1}', 'type needs value'), ('{"action":"press","value":"F5"}', 'press takes value Enter, Tab or Escape')):
            with self.assertRaisesRegex(ValueError, says): parse_decision(step, c, 'agent')


class ALongTakeOverCostsLess(unittest.TestCase):
    def test_once_the_assistant_is_working_through_the_task_it_gets_the_window_not_the_whole_page_again(self):
        page = {'url': URL, 'title': 'T', 'text': 'in the window\n[below the window]\nfar below', 'full': 'F' * 9000, 'full_at': 0}
        c = cand.build('[1] <a> "Home"')
        first = render('Task: buy joggers\nSteps: one\nStop before: payment', [{'by': 'jev', 'action': 'click', 'label': 'x', 'result': 'ok'}], page, c)
        later = render('Task: buy joggers\nSteps: one\nStop before: payment', [{'by': 'agent', 'action': 'click', 'label': 'x', 'result': 'ok'}], page, c)
        self.assertIn('FFFF', first); self.assertIn('Stop before: payment', first)
        self.assertNotIn('FFFF', later); self.assertNotIn('far below', later); self.assertIn('in the window', later); self.assertIn('c1: click "Home"', later)
        self.assertIn('the full task is in your earlier results', later); self.assertIn('action "read" shows the whole page', later)
        self.assertLess(len(later), len(first) / 5)


class ATakeOverThatGoesNowhereEnds(unittest.TestCase):
    def test_the_assistant_gets_a_dozen_steps_in_one_task_and_then_the_task_ends_where_it_is(self):
        from agentai_platform.browse.loop import AGENT_STEP_LIMIT
        s = FpSession(FLAT, iter(range(999)))
        llm = scripted_llm(['{"action":"scroll"}', '{"action":"click","ref":1}', '{"action":"scroll","value":"up"}', '{"action":"click","ref":2}', '{"action":"scroll"}', '{"action":"click","ref":3}'] * 4)
        r = BrowseRunner(s, Ladder(agent=llm), wait=lambda x: None, max_steps=40).run('g', URL)
        self.assertEqual(r.status, 'stuck'); self.assertIn(f'took {AGENT_STEP_LIMIT} steps', r.reason)
        self.assertEqual(len(r.steps), AGENT_STEP_LIMIT); self.assertEqual(len(llm.calls), AGENT_STEP_LIMIT + 1)        # the thirteenth answer is not carried out


class Pipe:
    """A transport that answers from a script: a dict is a reply, an exception is raised by recv."""
    def __init__(self, script):
        self.script, self.sent, self.closed = list(script), [], False
    def send(self, obj): self.sent.append(obj)
    def recv(self, timeout):
        item = self.script.pop(0)
        if isinstance(item, BaseException): raise item
        return {'id': self.sent[-1]['id'], **item}
    def close(self): self.closed = True


class TheSession(unittest.TestCase):
    def test_a_read_that_times_out_is_asked_once_more(self):
        s = Session(Pipe([TimeoutError(), {'ok': True, 'url': URL}]), wait=lambda x: None)
        self.assertTrue(s.snapshot()['ok'])

    def test_a_late_answer_to_an_earlier_call_is_not_taken_for_this_one(self):
        class Late(Pipe):
            def recv(self, timeout):
                item = self.script.pop(0)
                return item if 'id' in item else {'id': self.sent[-1]['id'], **item}
        s = Session(Late([{'id': 0, 'ok': True, 'stale': True}, {'ok': True, 'fresh': True}]))
        s._id = 1
        self.assertTrue(s.snapshot().get('fresh'))

    def test_a_dead_browser_is_started_again_once_on_the_address_it_was_on(self):
        first = Pipe([{'ok': True, 'url': URL + 'cart'}, RunnerError('runner exited')])
        second = Pipe([{'ok': True, 'url': URL + 'cart'}, {'ok': True, 'url': URL + 'cart', 'snapshot': ''}, RunnerError('runner exited')])
        spawned = []
        s = Session(first, respawn=lambda: spawned.append(1) or second)
        s.open(URL + 'cart')
        snap = s.snapshot()
        self.assertTrue(snap['ok'] and snap['restarted']); self.assertTrue(first.closed); self.assertEqual(second.sent[0]['url'], URL + 'cart')
        with self.assertRaises(RunnerError): s.snapshot()                       # a second death in the same task ends it, as before
        self.assertEqual(len(spawned), 1)

    def test_a_step_cut_short_by_a_restart_is_reported_as_not_done(self):
        first = Pipe([{'ok': True, 'url': URL}, RunnerError('runner exited')])
        s = Session(first, respawn=lambda: Pipe([{'ok': True, 'url': URL}]))
        s.open(URL)
        self.assertEqual(s.act('click', 2, None, 'Buy'), {'ok': False, 'error': 'browser_restarted'})

    def test_without_a_way_to_restart_the_failure_is_raised_as_before(self):
        s = Session(Pipe([{'ok': True, 'url': URL}, RunnerError('runner exited')]))
        s.open(URL)
        with self.assertRaises(RunnerError): s.snapshot()


if __name__ == '__main__':
    unittest.main()
