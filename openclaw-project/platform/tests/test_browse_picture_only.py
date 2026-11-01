import json
import unittest

from agentai_platform.browse.ladder import JevChooser, Ladder, Look, RUNNER_V2
from agentai_platform.browse.picture_only_brain import PictureOnlyChooser, UltrafastPictureOnlyChooser
from tests.test_browse import CANDS, MODEL, PAGE, jev_answer, scripted_llm

SHOT = {'data': 'AAAA', 'width': 1280, 'height': 800, 'view': {'w': 1280, 'h': 800}}
SECRET_PAGE = {**PAGE, 'text': 'ZZ-PAGE-TEXT-ZZ', 'title': 'ZZ-TITLE-ZZ'}


def make(*picks):
    bodies, script = [], list(picks)

    def transport(endpoint, body, credential, deadline, headers=None):
        bodies.append(body)
        return jev_answer(body, script.pop(0) if script else script_default, 1.0, model=MODEL)
    script_default = {'operation': 'click'}
    return PictureOnlyChooser('https://x', MODEL, 'k', transport), bodies


class PictureOnly(unittest.TestCase):
    def ladder(self, *picks, llm=()):
        jev, bodies = make(*picks)
        return Ladder(agent=scripted_llm(list(llm)), jev=jev), bodies

    def test_jev_is_sent_the_picture_and_no_controls_no_page_text_no_title(self):
        ladder, bodies = self.ladder({'operation': 'click'})
        d = ladder.decide('buy a paddle', [], SECRET_PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT, why='test'))
        sent = json.dumps(bodies[0])
        self.assertNotIn('ZZ-PAGE-TEXT-ZZ', sent)
        self.assertNotIn('ZZ-TITLE-ZZ', sent)
        self.assertNotIn('c1', json.dumps(bodies[0]['questions'].get('click_target', {})))
        self.assertIn('assets', bodies[0])
        self.assertEqual((d.kind, d.by, d.action['action']), ('act', 'jev', 'clickat'))      # a spot in the picture, never a listed control
        self.assertEqual(ladder.agent.calls, [])

    def test_it_is_not_told_that_a_popup_is_in_the_way_but_the_standard_picture_prompt_still_is(self):
        ladder, bodies = self.ladder({'operation': 'click'})
        ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT))
        self.assertNotIn('popup', bodies[0]['state'])
        self.assertIn('all you are given', bodies[0]['state'])
        bodies2 = []
        def transport(endpoint, body, credential, deadline, headers=None):
            bodies2.append(body); return jev_answer(body, {'operation': 'click'}, 1.0, model=MODEL)
        JevChooser('https://x', MODEL, 'k', transport).choose_picture('buy a paddle', PAGE, [], SHOT, why='the page lists no controls', caps=RUNNER_V2)
        self.assertIn('a popup, a panel or a human check is probably in the way', bodies2[0]['state'])

    def test_without_a_picture_the_task_stops_instead_of_sending_text(self):
        ladder, bodies = self.ladder({'operation': 'click'})
        d = ladder.decide('buy a paddle', [], SECRET_PAGE, CANDS, caps=RUNNER_V2, look=Look())
        self.assertEqual((d.kind, bodies, ladder.agent.calls), ('stop', [], []))

    def test_the_assistant_never_takes_a_step_it_stops_after_two_misses(self):
        ladder, _ = self.ladder({'operation': 'ask_user'}, {'operation': 'ask_user'}, llm=['{"action":"click","ref":1}'])
        for kind in ('stop',):
            d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT), jev_misses=1)
            self.assertEqual(d.kind, kind)
        self.assertEqual(ladder.agent.calls, [])

    def test_a_take_over_request_stops_the_task_rather_than_calling_the_assistant(self):
        ladder, _ = self.ladder({'operation': 'click'}, llm=['{"action":"click","ref":1}'])
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT, claude='the page needs more'), force_escalate=True)
        self.assertEqual((d.kind, ladder.agent.calls), ('stop', []))

    def test_done_is_still_confirmed_by_the_assistant(self):
        ladder, _ = self.ladder({'operation': 'done'}, llm=['{"action":"done","answer":"13.99"}'])
        d = ladder.decide('buy a paddle', [], PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT))
        self.assertEqual((d.kind, d.answer), ('done', '13.99'))


if __name__ == '__main__':
    unittest.main()


class UltrafastPictureOnly(unittest.TestCase):
    def test_the_ultrafast_decider_in_picture_only_mode_gets_the_picture_alone_and_the_text_writer_is_not_used(self):
        bodies, writer = [], []

        def transport(endpoint, body, credential, deadline, headers=None):
            bodies.append(body)
            return jev_answer(body, {'operation': 'click'}, 1.0, model='jev-1.14.0')
        jev = UltrafastPictureOnlyChooser('https://x', 'k', transport, 'text-key', lambda *a, **k: writer.append(a) or '{}')
        ladder = Ladder(agent=scripted_llm([]), jev=jev)
        d = ladder.decide('buy a paddle', [], SECRET_PAGE, CANDS, caps=RUNNER_V2, look=Look(shot=SHOT, why='test'))
        sent = json.dumps(bodies[0])
        self.assertNotIn('ZZ-PAGE-TEXT-ZZ', sent)
        self.assertNotIn('ZZ-TITLE-ZZ', sent)
        self.assertEqual(bodies[0]['model'], 'jev-latest')
        self.assertEqual((d.kind, d.by, d.action['action']), ('act', 'jev', 'clickat'))
        self.assertEqual(writer, [])
        self.assertEqual(ladder.agent.calls, [])
