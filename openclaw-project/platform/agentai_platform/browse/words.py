"""What a customer reads for one step the browser took (stdlib only; reliability plan, Part 4).

A step used to be noted as `Clicked “Men” · JEV` or `Clicked “Expand Men” · Assistant (failed: covered)`: who decided the step is Lumina's inner working, and
`covered` is the runner's word. A step is now said the way a person would say it: what was done, or what could not be done and why. The words are fixed; the only
thing taken from the page is the control's own label, as before.

`step_words` is used where the note is written (browse/adapter.py). `reworded` reads a note that was written before this, so an older task's record reads the same way.
"""
from __future__ import annotations
import re

DONE = {'click': 'Clicked', 'type': 'Typed into', 'select': 'Chose in', 'press': 'Pressed a key', 'scroll': 'Scrolled', 'back': 'Went back', 'wait': 'Waited', 'read': 'Read the page'}
TRIED = {'click': 'click', 'type': 'type into', 'select': 'choose in', 'press': 'press a key', 'scroll': 'scroll', 'back': 'go back', 'wait': 'wait', 'read': 'read the page'}
# Why a step did not work, by the result the runner or the loop gave it. Anything not listed is "it did not work": never the code itself.
PROBLEMS = {
    'covered': 'something on the page was covering it', 'action_failed': 'the page did not respond', 'timeout': 'the page did not respond in time',
    'stale': 'the page had changed', 'left_the_site': 'it would have left the site', 'no_option': 'that choice is not on the page', 'not_a_field': 'it is not something that can be typed into',
    'url_blocked': 'that address is not allowed', 'navigation_failed': 'the page did not load', 'key_not_allowed': 'that key is not allowed',
}
NOT_DONE = 'Could not '        # how a step that did not work begins: the timeline reads a failed step by it


def step_words(action, label='', result='ok') -> str:
    """One step, in a customer's words. `label` is the control's own label on the page (or '')."""
    action, label = str(action or ''), f' “{label}”' if label else ''
    if result == 'ok':
        return (DONE.get(action) or 'Did a step') + label
    return f'{NOT_DONE}{TRIED.get(action, "do a step")}{label}: {PROBLEMS.get(str(result), "it did not work")}'


_OLD = re.compile(r'^(?P<what>.+?) · (?P<who>[A-Za-z]{2,20})(?: \(failed: (?P<result>[a-z_]{1,40})\))?$', re.S)
_OLD_VERBS = (('Typed into', 'type'), ('Chose in', 'select'), ('Went back', 'back'), ('Clicked', 'click'), ('Pressed', 'press'), ('Scrolled', 'scroll'), ('Waited', 'wait'))


def reworded(text) -> str:
    """A step note as it reads now. A note in the old form is turned into the new one; anything else (a note already in the new form, "Opened ...") comes back as it is."""
    text = str(text or '')
    old = _OLD.match(text)
    if not old:
        return text
    what, result = old.group('what'), old.group('result')
    for verb, action in _OLD_VERBS:
        if what == verb or what.startswith(verb + ' “'):
            label = what[len(verb):].strip().strip('“”')
            return step_words(action, label, result or 'ok')
    return what if not result else f'{what}: {PROBLEMS.get(result, "it did not work")}'


def failed(text) -> bool:
    return str(text or '').startswith(NOT_DONE)
