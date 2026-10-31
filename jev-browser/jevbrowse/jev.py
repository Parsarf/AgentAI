"""JEV (TypeSafe): you give it a state and questions; it answers each one. It never writes anything: a `choice` picks one of the options we list, a `box` says where on a
picture something is, a `noul` gives the chance of a yes. The state is text (the goal and the page's controls), and when the page's controls cannot be read, a screenshot too."""
import base64
import json
import math
import time
import urllib.request
import uuid

from .log import NULL

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MODEL = 'jev-1.14.0'                  # `box` questions need 1.14; images are an experimental feature and must be switched on with a header
IMAGE_HEADERS = {'TypeSafe-Danger-Zone-Images': 'true'}
LIMITS = {'side': (280, 1568), 'pixels': (78_400, 2_458_624)}      # TypeSafe refuses (never resizes) anything outside these


class JevError(Exception):
    pass


def post(endpoint, body, key, deadline, headers=None):
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), method='POST',
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(req, timeout=deadline) as response:
        return response.read(200_000).decode()


def check_image(shot):
    w, h = shot['width'], shot['height']
    if not all(LIMITS['side'][0] <= v <= LIMITS['side'][1] for v in (w, h)) or not LIMITS['pixels'][0] <= w * h <= LIMITS['pixels'][1]:
        raise JevError(f'the screenshot is {w}x{h}, which JEV would refuse')


class Jev:
    def __init__(self, key, transport=post, deadline=20, log=NULL):
        self.key, self.transport, self.deadline, self.log = key, transport, deadline, log

    def ask(self, text, shot, choices, boxes=None, yesno=None):
        """text: the state. shot: None, or {data (base64 JPEG), width, height, file?} to show JEV the window as well (needed for any box question).
        choices: {name: {'instructions', 'options': {id: description}}}; boxes / yesno: {name: instructions}.
        -> {choice name: (id, probability), box name: {'left','right','top','bottom','confidence'}, yes/no name: probability}"""
        state, assets, headers = text, None, None
        if shot:
            check_image(shot)
            ref = str(uuid.uuid4())
            state = f'{text}\n\nWhat the browser window shows right now: {ref}'
            assets, headers = {ref: {'type': 'image', 'format': 'jpg', 'data_base64': shot['data']}}, IMAGE_HEADERS
        questions = {n: {'type': 'choice', 'instructions': q['instructions'], 'criteria': q['options']} for n, q in choices.items()}
        questions.update({n: {'type': 'box', 'instructions': i} for n, i in (boxes or {}).items()})
        questions.update({n: {'type': 'noul', 'instructions': i} for n, i in (yesno or {}).items()})
        body = {'model': MODEL, 'state': state, **({'assets': assets} if assets else {}), 'questions': questions}
        sent = {'state': state, 'questions': {**{n: q['options'] for n, q in choices.items()}, **{n: {} for n in {**(boxes or {}), **(yesno or {})}}},
                'asked': {n: q['instructions'] for n, q in questions.items()},
                'image': {'file': shot.get('file'), 'width': shot['width'], 'height': shot['height'], 'bytes': len(shot['data']) * 3 // 4} if shot else None}
        started, raw = time.monotonic(), None
        try:
            raw = self.transport(ENDPOINT, body, self.key, self.deadline, headers)
            data = json.loads(raw)
            answers = self.check(data, {n: q['options'] for n, q in choices.items()}, list(boxes or {}), list(yesno or {}))
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            self.log.emit('jev_call', **sent, ms=int((time.monotonic() - started) * 1000), raw=(raw or '')[:30000], error=error)
            raise exc if isinstance(exc, JevError) else JevError(f'JEV did not answer ({error})') from exc
        self.log.emit('jev_call', **sent, ms=int((time.monotonic() - started) * 1000), raw=raw[:30000], usage=data.get('usage'))
        return answers

    @staticmethod
    def check(data, options, boxes=(), yesno=()):
        """Every question must come back answered in its own form. Anything else is an error."""
        if not isinstance(data, dict) or data.get('model') != MODEL or not isinstance(data.get('answers'), dict):
            raise JevError('JEV sent an unusable answer')
        out = {}
        for name, opts in options.items():
            a = data['answers'].get(name)
            if not isinstance(a, dict) or a.get('type') != 'choice':
                raise JevError(f'{name}: not a choice')
            choice, probs = a.get('choice'), a.get('probabilities')
            ok = isinstance(probs, dict) and set(probs) == set(opts) and all(_unit(v) for v in probs.values())
            if choice not in opts or not ok or not math.isclose(sum(probs.values()), 1.0, abs_tol=0.05) or probs[choice] < max(probs.values()) - 1e-9:
                raise JevError(f'{name}: bad choice or probabilities')
            out[name] = (choice, float(probs[choice]))
        for name in boxes:
            a = data['answers'].get(name)
            box = a.get('box') if isinstance(a, dict) and a.get('type') == 'box' else None
            if not isinstance(box, dict) or not all(_unit(box.get(k)) for k in ('left', 'right', 'top', 'bottom')) or not _unit(a.get('confidence')) \
                    or not box['left'] < box['right'] or not box['top'] < box['bottom']:
                raise JevError(f'{name}: not a usable box')
            out[name] = {**{k: float(box[k]) for k in ('left', 'right', 'top', 'bottom')}, 'confidence': float(a['confidence'])}
        for name in yesno:
            a = data['answers'].get(name)
            if not isinstance(a, dict) or a.get('type') != 'noul' or not _unit(a.get('noul')):
                raise JevError(f'{name}: not a yes/no')
            out[name] = float(a['noul'])
        return out


def _unit(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1
