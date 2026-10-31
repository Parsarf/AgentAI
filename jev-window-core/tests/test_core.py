import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loop import Paused, run
from model import Jev, MODEL, ModelError, validate


def image(data='a'):
    return {'data': data, 'width': 700, 'height': 1000, 'token': data}


def decision(action='click', confidence=.9, **kw):
    return dict(action=action, confidence=confidence, found=.9, box_confidence=.8, x=.3, y=.4, **kw)


class Controller:
    def __init__(self, images=None):
        self.images = iter(images or [image('a'), image('b'), image('c'), image('d')])
        self.actions = []

    def shot(self):
        value = next(self.images)
        if isinstance(value, Exception):
            raise value
        return value

    def act(self, plan, token):
        self.actions.append((plan['action'], token))
        return 'sent'


class Model:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = []

    def decide(self, prompt, images, history, texts):
        self.calls.append((prompt, list(images), [dict(h) for h in history]))
        return decision(next(self.actions))


def execute(controller, model, prompt=lambda: 'Review the page', **kw):
    return run(controller, model, prompt, delay=0, sleep=lambda _: None, say=lambda _: None, **kw)


class LoopTests(unittest.TestCase):
    def test_each_action_uses_a_fresh_screenshot_and_keeps_visual_history(self):
        controller, model = Controller(), Model(['scroll_down', 'click', 'done'])
        self.assertEqual(execute(controller, model), 'done')
        self.assertEqual(controller.actions, [('scroll_down', 'a'), ('click', 'b')])
        self.assertEqual([i['data'] for i in model.calls[-1][1]], ['a', 'b', 'c'])
        self.assertIn('changed', model.calls[1][2][-1]['observation'])

    def test_focus_loss_discards_decision_and_never_acts_in_another_window(self):
        class FocusController(Controller):
            def act(self, plan, token):
                if token == 'a':
                    raise Paused('focus changed during model call')
                return super().act(plan, token)
        controller = FocusController([image('a'), Paused('other window'), image('b')])
        model = Model(['click', 'done'])
        self.assertEqual(execute(controller, model), 'done')
        self.assertEqual(controller.actions, [])
        self.assertEqual([i['data'] for i in model.calls[-1][1]], ['b'])

    def test_prompt_edit_during_model_call_discards_the_old_action(self):
        prompt = ['old goal']
        class EditingModel(Model):
            def decide(self, *args):
                plan = super().decide(*args)
                prompt[0] = 'new goal'
                return plan
        controller, model = Controller(), EditingModel(['click', 'done'])
        self.assertEqual(execute(controller, model, lambda: prompt[0]), 'done')
        self.assertEqual(controller.actions, [])
        self.assertEqual(model.calls[-1][0], 'new goal')

    def test_unchanged_scrolls_are_reported_then_stop_infinite_loop(self):
        controller = Controller([image()] * 5)
        model = Model(['scroll_down'] * 4)
        self.assertEqual(execute(controller, model), 'stuck')
        self.assertEqual(len(controller.actions), 3)
        self.assertIn('end may have been reached', model.calls[1][2][-1]['observation'])

    def test_uncertain_boxes_do_not_click(self):
        class Uncertain(Model):
            def decide(self, *args):
                return {**decision(), 'found': .1}
        controller = Controller()
        self.assertEqual(execute(controller, Uncertain([])), 'uncertain')
        self.assertEqual(controller.actions, [])

    def test_stop_arriving_during_model_call_prevents_action(self):
        stop = [False]
        class StopModel(Model):
            def decide(self, *args):
                stop[0] = True
                return decision()
        controller = Controller()
        self.assertEqual(execute(controller, StopModel([]), should_stop=lambda: stop[0]), 'stopped')
        self.assertEqual(controller.actions, [])

    def test_step_cap_and_preview(self):
        controller = Controller()
        self.assertEqual(execute(controller, Model(['click']), steps=1), 'max_steps')
        self.assertEqual(len(controller.actions), 1)
        controller = Controller()
        self.assertEqual(execute(controller, Model(['click']), dry_run=True), 'preview')
        self.assertEqual(controller.actions, [])

    def test_empty_prompt_pauses_without_capturing_or_calling_model(self):
        calls = [0]
        def prompt():
            calls[0] += 1
            return '' if calls[0] == 1 else 'new goal'
        model = Model(['done'])
        self.assertEqual(execute(Controller(), model, prompt), 'done')
        self.assertEqual(len(model.calls), 1)


def response(actions, action='click'):
    return {'model': MODEL, 'answers': {
        'action': {'type': 'choice', 'choice': action, 'probabilities': {k: int(k == action) for k in actions}},
        'target': {'type': 'box', 'box': {'left': .2, 'right': .4, 'top': .3, 'bottom': .6}, 'confidence': .9},
        'found': {'type': 'noul', 'noul': .9},
    }}


class ModelTests(unittest.TestCase):
    def test_request_has_visual_memory_and_only_current_frame_is_target(self):
        requests = []
        def send(body, key):
            requests.append(body)
            return response(body['questions']['action']['criteria'])
        plan = Jev('not-a-real-key', send).decide('Goal', [image('old'), image('new')], [], [])
        self.assertEqual(plan['action'], 'click')
        body = requests[0]
        self.assertEqual([a['data_base64'] for a in body['assets'].values()], ['old', 'new'])
        self.assertIn('CURRENT picture: frame-1', body['state'])
        self.assertNotIn('type', body['questions']['action']['criteria'])

    def test_invalid_choices_coordinates_probabilities_and_nan_rejected(self):
        actions = {'click': 'Click', 'done': 'Done'}
        mutations = [
            lambda r: r['answers']['action'].update(choice='super_like'),
            lambda r: r['answers']['action'].update(probabilities={'click': .1, 'done': .9}),
            lambda r: r['answers']['target']['box'].update(left=-1),
            lambda r: r['answers']['target']['box'].update(right=float('nan')),
            lambda r: r['answers']['found'].update(noul=True),
        ]
        for mutation in mutations:
            reply = response(actions)
            mutation(reply)
            with self.subTest(mutation=mutation), self.assertRaises(ModelError):
                validate(reply, actions, [])

    def test_only_supplied_text_can_be_typed(self):
        def send(body, key):
            reply = response(body['questions']['action']['criteria'], 'type')
            reply['answers']['text'] = {'type': 'choice', 'choice': 't0', 'probabilities': {'t0': 1}}
            return reply
        plan = Jev('test', send).decide('Search', [image()], [], ['exact query'])
        self.assertEqual(plan['text'], 'exact query')


if __name__ == '__main__':
    unittest.main()
