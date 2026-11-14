"""The fixes that came out of the browsing cost report (production request 064ac023, 13 November 2026). Each test names the measured problem it guards.

  - the prompt cache ended on the runtime's trailing internal-context message, so the conversation was written to the cache on every call and never read from it;
  - the window picture reached the assistant as cut-off base64 text;
  - the assistant, handed a page, was offered 20 controls where JEV was offered the 80 in the window;
  - JEV said "done", the assistant took a step instead, JEV was asked again and undid it, until the loop rule fired;
  - a new browser task queued behind the same request's job that was still waiting for the assistant's step;
  - what JEV had cost was reported as zero until the job ended.
"""
import copy
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch

from agentai_platform import model_keys as mk
from agentai_platform.browse import candidates as cand
from agentai_platform.browse import service as svc
from agentai_platform.browse.ladder import DONE_NOT_CONFIRMED, Ladder, Look, parse_decision
from agentai_platform.browse.loop import BrowseRunner
from tests.test_browse import FLAT, FpSession, ScriptedJev, live, scripted_llm
from tests.test_browser_tool import Base, FakeBrowse, done
from agentai_platform.browse.adapter import BrowserTool
from agentai_platform.events import EventService

TRAILER = {'role': 'user', 'content': [{'type': 'text', 'text': mk.INTERNAL_CONTEXT + '\nConversation info'}]}
POINT = {'type': 'ephemeral'}


def request(turns):
    """A request as the runtime (2026.9.6) sends it, captured from a real gateway: system, the customer's message, the tool loop so far, and the internal-context message LAST."""
    messages = [{'role': 'system', 'content': 'You are a personal assistant.'}, {'role': 'user', 'content': '[Fri 2026-11-13 15:35 PST] add the racket to my cart'}]
    for n in range(turns):
        messages.append({'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call_{n}', 'type': 'function', 'function': {'name': 'tool_call', 'arguments': '{}'}}]})
        messages.append({'role': 'tool', 'tool_call_id': f'call_{n}', 'content': f'the page after step {n}'})
    return {'model': 'selected', 'messages': messages + [copy.deepcopy(TRAILER)]}


def unmarked(messages):
    out = copy.deepcopy(messages)
    for m in out:
        m.pop('cache_control', None)
        for block in m['content'] if isinstance(m.get('content'), list) else []:
            block.pop('cache_control', None)
    return out


def marked_at(body):
    return [i for i, m in enumerate(body['messages']) if mk._has_cache_point(m)]


class CachePoints(unittest.TestCase):
    def test_the_cache_ends_on_the_last_message_that_stays_in_place_not_on_the_trailing_internal_context(self):
        body = request(2)
        self.assertTrue(mk.mark_cache_points(body))
        self.assertEqual(marked_at(body), [0, 5])                                         # the system prompt, and the last tool result; never the trailer (index 6)
        self.assertEqual(body['messages'][5]['cache_control'], POINT)
        self.assertEqual(body['messages'][-1], TRAILER)

    def test_the_prefix_marked_on_one_call_is_byte_for_byte_the_start_of_the_next_call(self):
        """What makes the next call a cache read: everything up to this call's mark is unchanged in the next request, where the mark has moved on."""
        for turns in range(0, 6):
            now, later = request(turns), request(turns + 1)
            mk.mark_cache_points(now); mk.mark_cache_points(later)
            end = marked_at(now)[-1] + 1
            self.assertEqual(json.dumps(unmarked(now['messages'][:end])), json.dumps(unmarked(later['messages'][:end])), turns)
            self.assertGreater(marked_at(later)[-1], marked_at(now)[-1])
            self.assertLessEqual(len(marked_at(later)), 2)                               # the provider allows four

    def test_nothing_but_the_two_marks_is_changed(self):
        body = request(3); before = copy.deepcopy(body)
        mk.mark_cache_points(body)
        self.assertEqual(unmarked(body['messages']), before['messages'])
        self.assertEqual({k: v for k, v in body.items() if k != 'messages'}, {k: v for k, v in before.items() if k != 'messages'})

    def test_a_message_with_nothing_to_mark_is_passed_over_for_the_one_before_it(self):
        body = request(1)
        body['messages'].insert(-1, {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c9', 'type': 'function', 'function': {'name': 'x', 'arguments': '{}'}}]})
        body['messages'].insert(-1, {'role': 'assistant', 'content': '  '})
        mk.mark_cache_points(body)
        self.assertEqual(marked_at(body), [0, 3])
        blocks = {'messages': [{'role': 'system', 'content': [{'type': 'text', 'text': 'rules'}]}, {'role': 'user', 'content': [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b'}]}]}
        mk.mark_cache_points(blocks)
        self.assertEqual(blocks['messages'][1]['content'], [{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': 'b', 'cache_control': POINT}])       # a list: its last block
        self.assertEqual(blocks['messages'][0]['content'][-1]['cache_control'], POINT)

    def test_a_request_without_the_trailer_ends_on_its_last_message_and_a_request_that_marks_its_own_is_left_alone(self):
        plain = {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'hello'}]}
        mk.mark_cache_points(plain); self.assertEqual(marked_at(plain), [0, 1])
        for own in ({'messages': [{'role': 'system', 'content': 's', 'cache_control': POINT}, {'role': 'user', 'content': 'hello'}]},
                    {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'x', 'cache_control': POINT}]}, {'role': 'user', 'content': 'y'}]},
                    {'messages': [{'role': 'user', 'content': 'y'}], 'tools': [{'type': 'function', 'function': {'name': 't', 'cache_control': POINT}}]},
                    {'messages': [{'role': 'user', 'content': 'y'}], 'cache_control': POINT}):
            before = copy.deepcopy(own)
            self.assertFalse(mk.mark_cache_points(own)); self.assertEqual(own, before)
        for odd in ({}, {'messages': 'x'}, {'messages': ['x']}, {'messages': []}, {'messages': [copy.deepcopy(TRAILER)]}):
            before = copy.deepcopy(odd)
            self.assertFalse(mk.mark_cache_points(odd)); self.assertEqual(odd, before)   # never an error, never a mark on the trailer alone

    def test_only_a_claude_model_behind_luminas_own_proxy_is_marked(self):
        if True:
            relay = mk.ModelRelay(None, lambda a: True, selection=lambda account: 'lumina-default')        # the route is the admitted request's own: no key store is read
            response = Mock(status=200); response.getheader.return_value = 'application/json'
            connection = Mock(); connection.getresponse.return_value = response
            raw = json.dumps(request(2)).encode()
            with patch.object(mk.http.client, 'HTTPConnection', return_value=connection):
                relay.selected_chat('a', 'cell', raw).close()
                sent = json.loads(connection.request.call_args.args[2])
                self.assertEqual((sent['model'], marked_at(sent)), ('claude-sonnet-5-5', [0, 5]))
                self.assertEqual(unmarked(sent['messages']), request(2)['messages'])
                with patch('agentai_platform.model_catalog.find', return_value={'id': 'lumina-next', 'name': 'Next', 'model': 'gpt-next'}):
                    relay.selected_chat('a', 'cell', raw).close()
                self.assertEqual(marked_at(json.loads(connection.request.call_args.args[2])), [])       # another provider's request is forwarded as it came


class PictureAndRelease(Base):
    def setUp(self):
        super().setUp()
        self.rpc = FakeBrowse()
        self.make = lambda **kw: BrowserTool(self.store, browse_factory=lambda account: self.rpc, events=EventService(self.store, clock=lambda: self.now), clock=lambda: self.now,
                                             sleep=lambda s: setattr(self, 'now', self.now + s), poll_interval=1.5, run_timeout=900, **kw)

    ARGS = {'task': 'Add the spiciest chicken wings to the cart', 'site': 'ubereats.com', 'steps': ['Open the site', 'Add the spiciest wings']}
    HANDED = {'state': 'running', 'events': [], 'cost_microusd': 30, 'url': 'https://ubereats.com/', 'observation': {'n': 1, 'text': 'Handed to you because: an open choice.', 'image': 'QUJD' * 30000}}

    def running(self):
        from tests.test_browser_tool import ToolChecks
        return ToolChecks.running_request(self)

    def test_a_handed_over_page_is_text_only_unless_the_picture_is_switched_on(self):
        self.running()
        self.rpc.script = [self.HANDED]
        result = self.make().call('a', self.ARGS)
        self.assertEqual(len(result), 2)
        self.assertNotIn('QUJDQUJD', result[0]); self.assertLess(len(result[0]), 1000)           # 120,000 characters of picture are not in what the assistant reads
        self.assertIn('needs your next step', result[0])

    def test_the_picture_can_still_be_sent_to_a_runtime_that_delivers_images(self):
        self.running()
        self.rpc.script = [self.HANDED]
        result = self.make(picture=True).call('a', self.ARGS)
        self.assertEqual((len(result), result[2]), (3, self.HANDED['observation']['image']))

    def test_a_new_browser_task_lets_go_of_the_job_still_waiting_for_the_assistants_step(self):
        request_id, _claim = self.running()
        tool = self.make()
        self.rpc.script = [self.HANDED]
        tool.call('a', self.ARGS)                                                          # the first job hands its page over and waits
        self.assertNotIn('agent_release', [c[0] for c in self.rpc.calls])                 # a request's first job has nothing to let go of
        self.rpc.script = [done()]
        tool.call('a', self.ARGS)                                                          # the assistant starts another task instead of sending the step
        ops = [(c[0], c[1]['request_id']) for c in self.rpc.calls if c[0] in ('agent_release', 'start')]
        self.assertEqual(ops[0], ('start', request_id))
        self.assertEqual(ops[1], ('agent_release', request_id))                           # the waiting job is released BEFORE the new one is started
        self.assertEqual(ops[2][0], 'start'); self.assertNotEqual(ops[2][1], request_id)

    def test_a_release_that_fails_never_stops_the_new_task(self):
        self.running()
        tool = self.make()
        self.rpc.script = [done()]
        tool.call('a', self.ARGS)

        class Refusing(FakeBrowse):
            def __call__(s, op, **params):
                if op == 'agent_release':
                    s.calls.append((op, params)); raise RuntimeError('service down')
                return super().__call__(op, **params)
        self.rpc = Refusing(); self.rpc.script = [done(answer='second')]
        text, error = tool.call('a', self.ARGS)
        self.assertFalse(error); self.assertIn('second', text)


def el(ref, in_view, covered=False):
    return {'ref': ref, 'label': f'Item {ref}', 'in_view': in_view, 'covered': covered, 'x': 10, 'y': 10 * ref}


class WhatTheAssistantIsOffered(unittest.TestCase):
    SNAP = '\n'.join(f'[{n}] <a> "Item {n}"' for n in range(1, 61))

    def lists(self, visible):
        elements = [el(n, n in visible) for n in range(1, 61)]
        listed = cand.build(self.SNAP, elements=elements)
        return listed, cand.reachable(cand.build(self.SNAP, limit=200, elements=elements))

    def test_the_controls_in_the_window_are_offered_with_the_list_it_always_had(self):
        listed, in_window = self.lists(set(range(25, 56)))                               # a results page scrolled down: 31 controls in the window, none of them among the first 20
        self.assertEqual(len(listed), 20)
        offered = cand.for_assistant(listed, in_window)
        refs = [c['ref'] for c in offered]
        self.assertEqual(refs, sorted(refs))
        self.assertTrue(set(range(25, 56)) <= set(refs))                                # every control a person could click right now
        self.assertTrue({c['ref'] for c in listed} <= set(refs))                        # and nothing it was offered before is taken away
        self.assertLessEqual(len(offered), cand.JEV_LIMIT)

    def test_an_engine_that_does_not_say_what_is_visible_keeps_the_old_list_and_the_limit_holds(self):
        listed = cand.build(self.SNAP)
        self.assertIs(cand.for_assistant(listed, None), listed)
        self.assertIs(cand.for_assistant(listed, []), listed)                           # nothing reachable (a popup covers the page): the list as before
        many = '\n'.join(f'[{n}] <a> "Item {n}"' for n in range(1, 201))
        elements = [el(n, n > 50) for n in range(1, 201)]
        offered = cand.for_assistant(cand.build(many, elements=elements), cand.reachable(cand.build(many, limit=200, elements=elements)))
        self.assertEqual(len(offered), cand.JEV_LIMIT)
        self.assertTrue(all(c['in_view'] for c in offered))                             # too many: the ones in the window are kept

    def test_the_assistant_can_choose_a_control_in_the_window_that_was_not_among_the_first_twenty(self):
        listed, in_window = self.lists(set(range(25, 56)))
        seen = []
        def agent(goal, history, page, candidates, handover, look):
            seen.append(candidates)
            return parse_decision('{"action":"click","ref":50}', candidates, 'agent')
        self.assertNotIn(50, [c['ref'] for c in listed])                                # 31 controls in the window, 20 places in the old list
        with self.assertRaises(ValueError):
            parse_decision('{"action":"click","ref":50}', listed, 'agent')              # before: "unknown element", and the assistant could only scroll
        d = Ladder(agent=agent).decide('g', [], {'url': 'https://shop.example/s', 'title': 't', 'text': ''}, listed, look=Look(jev_candidates=in_window))
        self.assertEqual((d.kind, d.by, d.action['ref'], d.action['label']), ('act', 'agent', 50, 'Item 50'))
        self.assertIn(50, [c['ref'] for c in seen[0]])

    def test_a_sensitive_control_in_the_wider_list_still_stops_for_the_customer(self):
        """The wider list widens what the assistant can point at, not what may be done: the code rule on the chosen control runs as before."""
        snap = '\n'.join([f'[{n}] <a> "Item {n}"' for n in range(1, 30)] + ['[30] <button> "Place order"'])
        elements = [el(n, n >= 25) for n in range(1, 31)]; elements[-1]['label'] = 'Place order'
        class S(FpSession):
            def snapshot(s):
                out = super().snapshot(); out['elements'] = elements; return out
        s = S({'start': {'url': 'https://shop.example/', 'snap': snap, 'text': 'x'}}, iter(range(99)))
        r = BrowseRunner(s, Ladder(agent=scripted_llm(['{"action":"click","ref":30}'])), max_steps=3).run('g', 'https://shop.example/')
        self.assertEqual((r.status, r.pending_action['label']), ('handoff', 'Place order'))
        self.assertEqual([c for c in s.log if c[0] == 'act'], [])                       # never clicked


SCROLL_UP = '{"action":"scroll","value":"up"}'


class DoneThatIsNotConfirmed(unittest.TestCase):
    def run_loop(self, jev_script, llm_steps, max_steps=8):
        llm = scripted_llm(list(llm_steps)); jev = ScriptedJev(*jev_script)
        s = FpSession(FLAT, iter(range(10 ** 6)))
        events = []
        r = BrowseRunner(s, live(llm, jev), max_steps=max_steps, on_stat=lambda name, n=1: events.append(name)).run('g', 'https://shop.example/')
        return r, llm, jev, events

    def test_the_second_time_on_one_address_the_assistant_keeps_the_page_and_jev_cannot_undo_its_steps(self):
        """The production run: JEV said done, the assistant scrolled up, JEV said done, the assistant scrolled up, JEV scrolled down, ... until 'same step a third time'."""
        jev = [{'operation': 'done'}, {'operation': 'done'}, {'operation': 'scroll_down'}, {'operation': 'scroll_down'}, {'operation': 'scroll_down'}]
        r, llm, jev_seen, stats = self.run_loop(jev, [SCROLL_UP, SCROLL_UP, SCROLL_UP, SCROLL_UP, '{"action":"done","answer":"the list"}'])
        self.assertEqual((r.status, r.answer), ('done', 'the list'))
        self.assertEqual([h['by'] for h in r.steps], ['agent'] * 4)                       # no JEV step between the assistant's
        self.assertEqual(len(jev_seen.bodies), 2)                                         # JEV was not asked again on that page after the second time
        self.assertEqual(llm.why[:2], ['check that the goal is achieved'] * 2)
        self.assertTrue(all(DONE_NOT_CONFIRMED in why for why in llm.why[2:]), llm.why)
        self.assertEqual(stats.count('claude_page_takeovers'), 1)

    def test_once_is_a_second_opinion_and_jev_is_asked_again(self):
        r, llm, jev_seen, _ = self.run_loop([{'operation': 'done'}, {'operation': 'click', 'click_target': 'c2'}, {'operation': 'done'}],
                                            [SCROLL_UP, '{"action":"done","answer":"ok"}'], max_steps=3)
        self.assertEqual([(h['by'], h['action']) for h in r.steps], [('agent', 'scroll'), ('jev', 'click')])
        self.assertEqual(len(jev_seen.bodies), 3)

    def test_the_page_goes_back_to_jev_when_the_address_changes(self):
        pages = {'start': {'url': 'https://shop.example/', 'snap': '[1] <a> "Alpha"\n[2] <a> "Beta"', 'text': 'x', 'go': {1: 'item'}},
                 'item': {'url': 'https://shop.example/item', 'snap': '[1] <a> "Add to basket"\n[2] <a> "Back"', 'text': 'y'}}
        llm = scripted_llm([SCROLL_UP, SCROLL_UP, '{"action":"click","ref":1}', '{"action":"done","answer":"added"}']); jev = ScriptedJev({'operation': 'done'}, {'operation': 'done'}, {'operation': 'done'})
        r = BrowseRunner(FpSession(pages, iter(range(10 ** 6))), live(llm, jev), max_steps=6).run('g', 'https://shop.example/')
        self.assertEqual((r.status, r.answer), ('done', 'added'))
        self.assertEqual(len(jev.bodies), 3)                                              # twice on the first page, and again on the new one
        self.assertEqual(llm.why[-1], 'check that the goal is achieved')

    def test_confirming_done_ends_the_run_as_it_always_did(self):
        r, llm, jev_seen, stats = self.run_loop([{'operation': 'done'}], ['{"action":"done","answer":"42"}'])
        self.assertEqual((r.status, r.answer, len(r.steps)), ('done', '42', 0))
        self.assertNotIn('claude_page_takeovers', stats)


class CostWhileTheJobRuns(unittest.TestCase):
    def test_a_poll_reports_what_the_run_has_spent_so_far_and_never_less_than_the_final_cost(self):
        job = svc.Job('acct', 'a' * 32, 'goal text', None, 1000, 5, 60)
        service = svc.BrowseService(spawn=None, root='/nonexistent')
        service.jobs[job.id] = job
        self.assertEqual(service.poll('acct', job.id)['cost_microusd'], 0)
        spent = [2887]
        job.running_cost = lambda: spent[0]
        self.assertEqual(service.poll('acct', job.id)['cost_microusd'], 2887)            # a job waiting for the assistant, or stopped before its end, used to read 0
        job.cost = 3000
        self.assertEqual(service.poll('acct', job.id)['cost_microusd'], 3000)
        job.running_cost = lambda: 1 / 0
        self.assertEqual(service.poll('acct', job.id)['cost_microusd'], 3000)            # a broken reading never breaks a poll


if __name__ == '__main__':
    unittest.main()
