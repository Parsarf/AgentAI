"""When JEV is shown a picture instead of the page's controls, where the page is scrolled to, and the nudge after a run of scrolls.

All of it is a pure function of what the runner reported and how the last steps went, so every rule can be tested without a browser or a model.
Nothing here can widen what the browser may do: the code rules in loop.py (payment, sign-in, human checks, sensitive buttons) run regardless.
"""
from __future__ import annotations

COVERED_SHARE, MIN_VISIBLE = 0.4, 3      # a picture when at least this share of at least this many controls in the window have something on top of them
SCROLL_HINT_AFTER = 3                    # identical scrolls in a row before JEV is reminded that scrolling is not getting anywhere
SCROLL_CLAUDE_AFTER = 6                  # ... and before Claude takes the page
REPEAT_AFTER = 2                         # the same JEV step this many times in a row with nothing happening: Claude takes the page
NOTHING_AFTER = 3                        # this many JEV steps in a row (any steps) that changed nothing or failed: Claude takes the page
PICTURE_FAILS = frozenset({'covered'})   # a runner refusal that means "something is on top of it"
JEV_FAILS = frozenset({'stale', 'no_option', 'not_a_field', 'action_failed', 'disabled', 'bad_coordinates'})   # JEV's step could not be carried out: Claude looks at this page


def position(snap):
    """-> (words for JEV or '', True when the bottom of the page is in the window). Nothing is claimed when the runner did not say."""
    height, window, scroll = snap.get('height'), snap.get('window'), snap.get('scroll') or 0
    if not height or not window:
        return '', False
    room = height - window
    if room <= 8:
        return 'the whole page fits in the window (nothing to scroll)', True
    tall = f'the page is about {height / window:.1f} windows tall'
    if scroll >= room - 4:
        return f'at the very bottom (nothing more below); {tall}', True
    if scroll <= 4:
        return f'at the top; {tall}', False
    return f'{round(scroll / room * 100)}% of the way down; {tall}', False


def scroll_run(history):
    """How many of the most recent steps in a row were scrolls (either direction)."""
    n = 0
    for h in reversed(history):
        if h.get('action') != 'scroll':
            break
        n += 1
    return n


def hint(snap, history):
    """A nudge, not a stop: after several scrolls in a row JEV is reminded that scrolling alone is not getting it anywhere. '' when there is nothing to say."""
    n = scroll_run(history)
    if n < SCROLL_HINT_AFTER:
        return ''
    bottom = position(snap)[1]
    return (f'Hint: you have scrolled {n} times in a row without doing anything else' + (' and you are now at the bottom of the page' if bottom else '') + '. '
            'Scrolling more is unlikely to help. Look for a control that moves you toward the goal instead (a search button or box, a menu, a category or a product link).')


def did_nothing(h):
    """A step that failed, or after which the page looked exactly the same."""
    return h.get('result') != 'ok' or h.get('changed') is False


def _same(a, b):
    """The same step: the same move on the same thing (scrolling down and scrolling up are different moves)."""
    return (a.get('action'), a.get('label'), a.get('move')) == (b.get('action'), b.get('label'), b.get('move'))


def covered_share(snap):
    """-> (controls in the window, how many of them have something on top)."""
    visible = [e for e in snap.get('elements') or [] if e.get('in_view') and e.get('covered') is not None]
    return len(visible), sum(1 for e in visible if e.get('covered'))


def choose_mode(snap, candidates, history):
    """-> ('controls' | 'picture', why). Decided fresh on every step from the page as it is right now and how the last step went. A runner that does not report
    what covers what (an older one) never gets a picture step: it has no way to take one."""
    if snap.get('window') is None:
        return 'controls', ''
    if not candidates:
        return 'picture', 'the page lists no controls'
    visible, covered = covered_share(snap)
    if visible >= MIN_VISIBLE and covered / visible >= COVERED_SHARE:
        return 'picture', f'{covered} of the {visible} controls in the window are covered'
    if history and history[-1].get('result') in PICTURE_FAILS:
        return 'picture', 'the last click was refused: something is on top of it'
    return 'controls', ''


def claude_reason(history):
    """Why Claude, not JEV, should decide the next step on this page ('' = JEV goes on). Only JEV's own steps count: Claude's stumbles are the ladder's business."""
    tail = []
    for h in reversed([h for h in history if h.get('action') != 'wait']):         # a wait neither counts nor breaks a run (it is how a slow page is given time)
        if h.get('by') != 'jev':
            break                                                                  # the unbroken run of JEV's own steps at the end of the history
        tail.append(h)
    if tail and tail[0].get('result') in JEV_FAILS:
        return f'JEV\'s last step could not be carried out ({tail[0]["result"]})'
    if len(tail) >= REPEAT_AFTER and all(did_nothing(h) and _same(h, tail[0]) for h in tail[:REPEAT_AFTER]):
        return f'JEV repeated the same step {REPEAT_AFTER} times and nothing happened'
    if len(tail) >= NOTHING_AFTER and all(did_nothing(h) for h in tail[:NOTHING_AFTER]):
        return f'the last {NOTHING_AFTER} JEV steps changed nothing'
    if scroll_run(history) >= SCROLL_CLAUDE_AFTER and history and history[-1].get('by') == 'jev':
        return f'JEV has only scrolled for {SCROLL_CLAUDE_AFTER} steps'
    return ''
