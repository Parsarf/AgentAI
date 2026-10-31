"""Talks to the Node runner (runner/runner.mjs), which drives Chrome: one JSON line out, one back."""
import itertools
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .log import NULL

RUNNER = Path(__file__).resolve().parent.parent / 'runner' / 'runner.mjs'
CHROME_CANDIDATES = ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium',
                     '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser')


def find_chrome():
    return os.environ.get('BROWSE_CHROME') or next((p for p in CHROME_CANDIDATES if Path(p).exists()), None) or shutil.which('chromium') or shutil.which('google-chrome')


class Browser:
    def __init__(self, headless=False, log=NULL, shots_dir=None):
        self.log = log
        chrome = find_chrome()
        if not chrome:
            raise RuntimeError('Chrome was not found. Install Google Chrome or set BROWSE_CHROME to a Chrome or Chromium binary.')
        env = {**os.environ, 'BROWSE_CHROME': chrome, 'BROWSE_HEADLESS': '1' if headless else '0', **({'BROWSE_SHOTS': str(shots_dir)} if shots_dir else {})}
        self.proc = subprocess.Popen(['node', str(RUNNER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(RUNNER.parent), text=True, bufsize=1)
        self.ids = itertools.count(1)
        threading.Thread(target=self._drain, daemon=True).start()
        log.emit('browser_start', chrome=chrome, headless=headless)

    def _drain(self):
        """Whatever the runner prints to its own error output (crashes, blocked requests) goes to the log."""
        try:
            for text in self.proc.stderr:
                text = text.rstrip()[:500]
                self.log.emit('runner_event' if text.startswith('event ') else 'runner_stderr', text=text.removeprefix('event '))
        except Exception:
            pass

    def call(self, cmd, **params):
        rid = next(self.ids)
        started = time.monotonic()
        info = {'cmd': cmd, **{k: params[k] for k in ('url', 'action', 'ref', 'x', 'y') if params.get(k) is not None}}
        try:
            self.proc.stdin.write(json.dumps({'id': rid, 'cmd': cmd, **params}) + '\n')
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError('the browser process exited')
            reply = json.loads(line)
        except Exception as exc:
            self.log.emit('runner_error', **info, ms=int((time.monotonic() - started) * 1000), error=f'{type(exc).__name__}: {exc}')
            raise
        self.log.emit('runner', **info, ms=int((time.monotonic() - started) * 1000), ok=bool(reply.get('ok')), error=reply.get('error'),
                      now_at=(reply.get('page') or {}).get('url'), controls=len((reply.get('page') or {}).get('elements') or []))
        return reply

    def open(self, url):
        return self.call('open', url=url)                      # -> {ok, page}

    def look(self):
        return self.call('look')                               # -> {ok, page}: the page as it is right now

    def shot(self):
        return self.call('shot')                               # -> {ok, data (base64 JPEG), width, height, view: {w, h}, file?}: the window as it looks right now

    def probe(self, x, y):
        return self.call('probe', x=x, y=y)                    # -> {ok, hit: {tag, type, label, editable, disabled} | None}: what is under that point

    def act(self, action, ref=None, x=None, y=None, value=None):
        return self.call('act', action=action, ref=ref, x=x, y=y, value=value)     # -> {ok, error?}: click | type | select (by number), clickat | typeat (at a point), scroll_down | press_enter

    def close(self):
        try:
            self.call('close')
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except Exception:
                pass
