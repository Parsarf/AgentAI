"""Screenshot -> model -> one action -> fresh screenshot. No page/DOM dependency."""
from collections import deque
import time


class Paused(RuntimeError):
    """User focus changed: wait for them to return to the selected window."""


def run(controller, model, prompt_source, texts=(), steps=500, delay=.8, say=print,
        should_stop=lambda: False, sleep=time.sleep, memory=6, dry_run=False):
    pictures, history = deque(maxlen=memory), []
    attempts, unchanged, uncertain = 0, 0, 0
    paused = False
    while attempts < steps:
        if should_stop():
            return 'stopped'
        prompt = prompt_source().strip()
        if not prompt:
            if not paused:
                say('Paused: prompt is empty. Add a prompt and return to the selected window.')
            paused = True
            sleep(.5)
            continue
        try:
            shot = controller.shot()
        except Paused as exc:
            if not paused:
                say(f'Paused: {exc}')
            paused = True
            sleep(.5)
            continue
        if paused:
            say('Resuming.')
            paused = False
        # A prompt edit replaces the instructions. Do not execute a reply to the old prompt.
        if prompt_source().strip() != prompt:
            continue
        same = bool(pictures and shot['data'] == pictures[-1]['data'])
        if history:
            history[-1]['observation'] = ('Next picture unchanged; if scrolling, the end may have been reached.'
                                          if same else 'Next picture changed; verify the previous action succeeded.')
        if same:
            unchanged += 1
        else:
            unchanged = 0
            pictures.append(shot)
        if unchanged >= 3:
            say('Stopped: three fresh pictures showed no change. Check the window and prompt.')
            return 'stuck'
        attempts += 1
        plan = model.decide(prompt, list(pictures), history, texts)
        if should_stop():
            return 'stopped'
        if prompt_source().strip() != prompt:
            say('Prompt changed; discarding the previous decision.')
            continue
        action = plan['action']
        say(f'{attempts}: {action} ({plan["confidence"]:.0%})')
        if dry_run:
            say('Preview only; no action sent.')
            return 'preview'
        pointed = action in ('click', 'type') or action.startswith('scroll_')
        if plan['confidence'] < .5 or (pointed and (plan['found'] < .5 or plan['box_confidence'] < .2)):
            uncertain += 1
            if uncertain >= 3:
                return 'uncertain'
            history.append({'action': action, 'result': 'not executed: uncertain target or action'})
            sleep(delay)
            continue
        uncertain = 0
        if action in ('done', 'needs_user'):
            return action
        try:
            # The native side checks the selected window and its geometry again, after the model call.
            result = 'waited' if action == 'wait' else controller.act(plan, shot['token'])
        except Paused as exc:
            say(f'Paused: {exc}; discarding this decision.')
            history.append({'action': action, 'result': 'not executed: focus or window changed'})
            pictures.clear()  # a resumed action always uses a new picture
            paused = True
            continue
        history.append({'action': action, 'result': result})
        history = history[-12:]
        sleep(delay)
    return 'max_steps'
