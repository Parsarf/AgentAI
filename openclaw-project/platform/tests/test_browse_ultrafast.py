import json
import unittest

from agentai_platform.browse import candidates as cand
from agentai_platform.browse.ladder import JevChooser, Ladder, RUNNER_V2
from agentai_platform.browse.ultrafast_brain import MAX_VALUE, MODEL, TEXT_ENDPOINT, TEXT_MODEL, UltrafastChooser
from tests.test_browse import CANDS, MODEL as STANDARD_MODEL, PAGE, ScriptedJev, jev_answer, scripted_llm

def writer_reply(text):
    return json.dumps({'choices': [{'message': {'content': json.dumps({'text': text})}}]})


class Writer:
    """Stands in for the text model: records each request, answers with `reply` (a string, or a callable(body) -> string, or an exception to raise)."""
    def __init__(self, reply=None):
        self.reply, self.calls = reply if reply is not None else writer_reply('blue carbon paddle'), []

    def __call__(self, endpoint, body, key, deadline, headers=None):
        self.calls.append((endpoint, body, key))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(body) if callable(self.reply) else self.reply


def make(pick, writer=None, key='text-key', answered_by='jev-1.14.0', tokens=500):
    bodies = []

    def transport(endpoint, body, credential, deadline, headers=None):
        bodies.append(body)
        return jev_answer(body, pick, 1.0, model=answered_by, tokens=tokens)
    return UltrafastChooser('https://x', 'k', transport, key, writer or Writer()), bodies


TYPE_NEW = {'operation': 'type', 'type_target': 'c1', 'type_text': 'write_new'}


class Model(unittest.TestCase):
    def test_the_alias_is_asked_for_and_the_version_that_answered_is_recorded(self):
        brain, bodies = make({'operation': 'click', 'click_target': 'c2'})
        pick = brain.choose('buy a paddle', 'text', CANDS, page=PAGE, caps=RUNNER_V2)
        self.assertEqual((pick.operation, pick.target, bodies[0]['model'], brain.resolved), ('click', 'c2', MODEL, 'jev-1.14.0'))

    def test_an_answer_from_any_other_model_is_refused(self):
        for named in ('gpt-5', '', None, 'jev'):
            brain, _ = make({'operation': 'click', 'click_target': 'c2'}, answered_by=named)
            with self.assertRaises(ValueError, msg=named):
                brain.choose('buy a paddle', 'text', CANDS, page=PAGE, caps=RUNNER_V2)

    def test_the_standard_chooser_is_untouched(self):
        jev = ScriptedJev({'operation': 'type', 'type_target': 'c1', 'type_text': 'write_new'})
        pick = JevChooser('https://x', STANDARD_MODEL, 'k', jev).choose('buy a paddle', 'text', CANDS, page=PAGE, caps=RUNNER_V2)
        self.assertEqual((pick.text, pick.text_src), (None, ''))               # new text is still the assistant's job


class TextWriter(unittest.TestCase):
    def test_a_field_with_no_text_in_the_request_is_written_by_the_fast_model_not_the_assistant(self):
        writer = Writer()
        brain, _ = make(TYPE_NEW, writer)
        pick = brain.choose('buy a paddle', 'Welcome', CANDS, page=PAGE, caps=RUNNER_V2)
        self.assertEqual((pick.operation, pick.text, pick.text_src), ('type', 'blue carbon paddle', 'helper'))
        endpoint, body, key = writer.calls[0]
        self.assertEqual((endpoint, key, body['model']), (TEXT_ENDPOINT, 'text-key', TEXT_MODEL))
        self.assertIn('exactly one key, text', body['messages'][0]['content'])

    def test_a_phrase_from_the_request_still_needs_no_writer(self):
        writer = Writer()
        brain, _ = make({'operation': 'type', 'type_target': 'c1', 'type_text': 't0'}, writer)
        pick = brain.choose('find "carbon paddle" in blue', 'Welcome', CANDS, page=PAGE, caps=RUNNER_V2, phrases=['carbon paddle'])
        self.assertEqual((pick.text, pick.text_src, writer.calls), ('carbon paddle', '', []))

    def test_only_this_request_and_scrubbed_page_facts_leave_the_server(self):
        from agentai_platform.browse import goals
        writer = Writer()
        brain, _ = make(TYPE_NEW, writer)
        goal = goals.HISTORY_HEADER + json.dumps([{'role': 'user', 'content': 'my earlier private chat'}]) + goals.CURRENT_MARKER + 'Search for paddles, my email is me@example.com'
        page = {'url': 'https://shop.example/search?token=abc123', 'title': 'Shop for me@example.com', 'text': 'x'}
        brain.choose(goal, 'Order 4111 1111 1111 1111 now. ' + 'y' * 5000, CANDS, page=page, caps=RUNNER_V2)
        sent = json.dumps(writer.calls[0][1])
        for leaked in ('earlier private chat', 'me@example.com', '4111 1111 1111 1111', 'token=abc123'):
            self.assertNotIn(leaked, sent)
        self.assertLess(len(writer.calls[0][1]['messages'][1]['content']), 6500)

    def test_a_sensitive_field_or_a_missing_key_never_reaches_the_writer(self):
        writer = Writer()
        secret = cand.build('[1] <input type=password> "Password"\n[2] <a> "Home"')
        brain, _ = make({'operation': 'type', 'type_target': 'c1', 'type_text': 'write_new'}, writer)
        self.assertIsNone(brain.choose('log in', 'x', secret, page=PAGE, caps=RUNNER_V2).text)
        brain, _ = make(TYPE_NEW, writer, key='')
        self.assertIsNone(brain.choose('buy a paddle', 'x', CANDS, page=PAGE, caps=RUNNER_V2).text)
        self.assertEqual(writer.calls, [])

    def test_when_the_writer_fails_the_step_falls_back_to_the_assistant_as_before(self):
        bad = (writer_reply(None), writer_reply(''), writer_reply('x' * (MAX_VALUE + 1)), writer_reply('line\nbreak'), 'not json', '{}',
               json.dumps({'choices': [{'message': {'content': json.dumps({'text': 'a', 'extra': 1})}}]}), TimeoutError('slow'))
        for reply in bad:
            brain, _ = make(TYPE_NEW, Writer(reply))
            pick = brain.choose('buy a paddle', 'x', CANDS, page=PAGE, caps=RUNNER_V2)
            self.assertEqual((pick.operation, pick.text, pick.text_src), ('type', None, ''), repr(reply)[:40])
        self.assertTrue(brain.last_text_error)


class OnTheSameBrowser(unittest.TestCase):
    """Through the real ladder: the same decisions, loop rules and hand-overs as the standard decider, plus the fast writer."""

    def ladder(self, pick, writer=None, llm=()):
        brain, _ = make(pick, writer)
        return Ladder(agent=scripted_llm(list(llm)), jev=brain), brain

    def test_a_typed_step_is_decided_and_written_without_the_assistant(self):
        ladder, _ = self.ladder(TYPE_NEW)
        agent = ladder.agent
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2)
        self.assertEqual((d.kind, d.by, d.action['action'], d.action['value'], d.text_src, agent.calls), ('act', 'jev', 'type', 'blue carbon paddle', 'helper', []))

    def test_a_failed_writer_hands_that_one_step_to_the_assistant(self):
        ladder, _ = self.ladder(TYPE_NEW, Writer(TimeoutError('slow')), llm=['{"action":"type","ref":1,"value":"carbon"}'])
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2)
        self.assertEqual((d.by, d.text_src, d.action['value'], ladder.agent.calls), ('agent', 'agent', 'carbon', ['agent']))

    def test_clicks_done_and_hand_overs_are_exactly_the_standard_ones(self):
        ladder, _ = self.ladder({'operation': 'click', 'click_target': 'c2'})
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2)
        self.assertEqual((d.kind, d.by, d.action['ref'], ladder.agent.calls), ('act', 'jev', 2, []))
        ladder, _ = self.ladder({'operation': 'done'}, llm=['{"action":"done","answer":"cheapest is 13.99"}'])
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2)
        self.assertEqual((d.kind, d.agent_answer, d.answer), ('done', True, 'cheapest is 13.99'))          # `done` is still confirmed by the assistant, which writes the answer
        ladder, _ = self.ladder({'operation': 'needs_user'})
        self.assertEqual(ladder.decide('log in', [], PAGE, CANDS, caps=RUNNER_V2).kind, 'handoff')


if __name__ == '__main__':
    unittest.main()
