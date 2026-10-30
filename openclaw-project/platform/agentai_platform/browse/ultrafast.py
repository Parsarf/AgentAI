"""The experimental engine: browser-use's jev-ultrafast, run beside the standard browser for the owner's own testing.

jev-ultrafast is a whole loop (it chooses and it clicks), so it does not plug in as "hands" like the runner or the native browser: the service runs it in a child
process (ultrafast_driver.py, in its own python environment) and this module turns the child's JSON lines into the same steps, pictures and final state the Live view
already shows. It is an MVP that shares one Chrome profile and has none of the standard browser's stops (payment, sign-in, human checks), so the host adds what it can
from outside: only public http(s) addresses, the denied-sites list, the time and step limits, Stop, and the owner's switch (read again every quarter second: when the
temporary toggle expires the task is stopped).

Pure logic with an injected child, so every rule is tested without a browser or a model. The child never receives anything but the goal and a start address.
"""
from __future__ import annotations
import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .loop import DEFAULT_DENY
from .native_runner import url_allowed

POLL_SECONDS = 0.25
MAX_LINE = 8192
EOF = object()                                           # what a child's reader returns once its output has ended
FINAL = {'done': 'done', 'blocked': 'blocked', 'max_steps': 'max_steps'}


class Child:
    """A real child process: one JSON request line in, JSON lines out. A reader thread feeds a queue, so the host can keep watching the clock and the switch."""

    def __init__(self, argv, env, cwd=None, user=None):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=cwd, text=True, bufsize=1, start_new_session=True, user=user)
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self.q.put(line[:MAX_LINE])
        finally:
            self.q.put(EOF)

    def send(self, request: dict):
        self.proc.stdin.write(json.dumps(request) + '\n')
        self.proc.stdin.flush()

    def read(self, timeout):
        """-> a line, EOF, or None when nothing arrived within `timeout`."""
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def kill(self):
        """Stop the child and anything it started. SIGTERM first so its `with` closes the task's Chrome tab; SIGKILL if it does not leave."""
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except OSError:
            pass


def child_env(home, extra, typesafe_key, text_key) -> dict:
    """Everything the child's environment holds: nothing inherited from the service (which is root's), its two keys, one stable home (Browser Harness keeps a single background
    connection to the Chrome there and reuses it for every task), and the non-secret settings from harness.env (the Chrome's address). Browser Harness reports usage to PostHog and
    checks for updates unless told not to; those four switches go last, so harness.env cannot undo them."""
    return {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'BH_HOME': str(home), 'BH_RUNTIME_DIR': str(Path(home) / 'run'), **extra,
            'TYPESAFE_API_KEY': typesafe_key, 'TEXT_MODEL_API_KEY': text_key,
            'TEXT_MODEL_BASE_URL': 'https://openrouter.ai/api/v1', 'TEXT_MODEL': 'inception/mercury-2.5', 'TEXT_MODEL_REASONING': 'none',
            'BH_TELEMETRY': '0', 'BROWSER_HARNESS_TELEMETRY': '0', 'ANONYMIZED_TELEMETRY': 'false', 'BH_UPDATE_CHECK': '0'}


def address_ok(url) -> bool:
    """A public http(s) address that is not on the denied list. A blank page is not an address: it is allowed (the child opens one before the first page)."""
    if not url or str(url).startswith('about:'):
        return True
    if not url_allowed(url):
        return False
    return not DEFAULT_DENY.search((urlsplit(url).hostname or '').lower() + '.')


def run(*, child, request, trace, on_event, cancelled, allowed, clock=time.monotonic, max_seconds=600):
    """Drive one task. -> (status, reason, url). `status` is one of done | blocked | max_steps | deadline | cancelled | error.
    `allowed()` is the owner's switch (False stops the task); `cancelled()` is Stop."""
    start = request['url']
    if not address_ok(start) or start.startswith('about:'):
        return 'blocked', 'that site is not allowed', ''
    t0, url, bad_lines = clock(), start, 0

    def stop(status, reason, why):
        child.kill()
        trace.emit('stopped', why=why)
        return status, reason, url

    child.send(request)
    while True:
        if cancelled():
            return stop('cancelled', 'stopped by you', 'user')
        if not allowed():
            return stop('cancelled', 'the experimental browser was switched off', 'switch')
        if clock() - t0 > max_seconds:
            return stop('deadline', 'time limit reached', 'deadline')
        raw = child.read(POLL_SECONDS)
        if raw is None:
            continue
        if raw is EOF:
            trace.emit('child_ended', bad_lines=bad_lines)
            return 'error', 'the browser agent stopped unexpectedly', url
        try:
            line = json.loads(raw)
            kind = line['t']
        except (ValueError, KeyError, TypeError):
            bad_lines += 1                              # noise on stdout is counted, never shown
            continue
        if kind == 'opened':
            url = str(line.get('url') or url)
            if not address_ok(url):
                return stop('blocked', 'the page moved to a site that is not allowed', 'address')
            on_event('opened', {'url': url, 'title': ''})
        elif kind == 'step':
            url = str(line.get('url') or url)
            if not address_ok(url):
                return stop('blocked', 'the page moved to a site that is not allowed', 'address')
            n = int(line.get('n') or 0)
            entry = {'step': n, 'by': 'ultrafast', 'action': 'type' if line.get('kind') == 'fill' else str(line.get('kind') or 'click'), 'label': str(line.get('action') or '')[:80],
                     'result': 'ok', 'changed': line.get('changed'), 'confidence': line.get('confidence')}
            trace.emit('step', n=n, move=entry['action'], changed=entry['changed'], confidence=entry['confidence'])
            on_event('step', {**entry, 'url': url})
            if line.get('shot'):
                on_event('screenshot', {'file': str(line['shot']), 'step': n})
        elif kind == 'final':
            url = str(line.get('url') or url)
            status = FINAL.get(str(line.get('status')), 'error')
            return status, str(line.get('reason') or ''), url
