"""Child process of the experimental engine: runs ONE jev-ultrafast task and reports it as JSON lines on stdout.

Run it with the python of the jev-ultrafast environment (it imports `jev_ultrafast`, which the platform's own python does not have). The request is one JSON line on
stdin: {"url", "goal", "out", "max_steps"}. Keys are in the environment, never in argv. The host (ultrafast.py) reads the lines, enforces the time limit, the address
rules and the owner's switch, and kills this process to stop a task; the `with` below then closes the task's own Chrome tab.

Lines: {"t":"opened","url"} | {"t":"step","n","action","kind","url","changed","confidence","shot"} | {"t":"final","status","reason","url"}.
Typed text and page text are never written to the lines: the host's trace and the customer's step list get what was done, not what was typed.
"""
from __future__ import annotations
import base64
import json
import re
import sys
from pathlib import Path

MAX_SHOTS = 999                                         # shot-NNN.jpg: the host serves only names of this shape


def emit(**line):
    sys.stdout.write(json.dumps(line, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def save_shot(out: Path, n: int, page: dict) -> str:
    """The picture of the page after step n, or '' when there is none."""
    raw = page.get('screenshot')
    if not raw or n > MAX_SHOTS:
        return ''
    name = f'shot-{n:03d}.jpg'
    try:
        (out / name).write_bytes(base64.b64decode(raw))
    except (OSError, ValueError):
        return ''
    return name


def reason_for(status: str, steps: int) -> str:
    if status == 'done':
        return 'the browser agent decided the task was finished'
    if status == 'blocked':
        return 'the browser agent could not continue'
    return f'step limit reached ({steps})'


def main() -> int:
    request = json.loads(sys.stdin.readline())
    out, max_steps = Path(request['out']), int(request['max_steps'])
    from jev_ultrafast import Agent                      # imported late: this file is importable (and its helpers testable) without the environment
    status, url, shown = 'error', request['url'], 0
    with Agent(request['url'], request['goal'], screenshots=True) as agent:
        emit(t='opened', url=agent.state['page'].get('url', url))
        for state in agent.run():
            history = state['history']
            while shown < len(history):
                entry = history[shown]
                shown += 1
                emit(t='step', n=entry['step'], action=re.sub(r'\s+', ' ', str(entry['action']))[:80], kind=entry['kind'], url=entry['url'],
                     changed=entry['page_changed'], confidence=entry['confidence'], shot=save_shot(out, entry['step'], state['page']))
            url = state['page'].get('url', url)
            if len(history) >= max_steps and state['status'] not in ('done', 'blocked'):
                status = 'max_steps'
                break
        else:
            status = agent.state['status']               # the loop ended by itself: 'done' or 'blocked'
    emit(t='final', status=status, reason=reason_for(status, shown), url=url)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
