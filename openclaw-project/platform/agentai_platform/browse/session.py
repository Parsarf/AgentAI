"""Client for the browse runner: one JSON object per line each way, strict deadlines, nothing else."""
from __future__ import annotations
import json
import subprocess
import threading
import time
from collections import deque

from .trace import NULL


class RunnerError(Exception):
    pass


class ProcessTransport:
    """Spawns `argv` (e.g. node runner.mjs locally, or docker exec into the stage) and speaks JSON lines to it."""

    def __init__(self, argv, env=None, cwd=None):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd, text=True, bufsize=1)
        self._lines = []
        self.stderr_tail = deque(maxlen=20)          # the runner's last words, for the trace when it dies (read off a pipe so it can never fill up and block it)
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self._cv = threading.Condition()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            with self._cv:
                self._lines.append(line)
                self._cv.notify_all()
        with self._cv:
            self._lines.append(None)
            self._cv.notify_all()

    def _drain_stderr(self):
        try:
            for line in self.proc.stderr:
                self.stderr_tail.append(line.rstrip()[:300])
        except Exception:
            pass

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + '\n')
        self.proc.stdin.flush()

    def recv(self, timeout):
        with self._cv:
            if not self._cv.wait_for(lambda: self._lines, timeout=timeout):
                raise TimeoutError('runner did not answer in time')
            line = self._lines.pop(0)
        if line is None:
            raise RunnerError('runner exited')
        return json.loads(line)

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


class Session:
    DEADLINES = {'open': 40, 'snapshot': 20, 'act': 30, 'screenshot': 20}

    def __init__(self, transport, trace=NULL):
        self.t, self._id, self.trace = transport, 0, trace

    def call(self, cmd, **params):
        self._id += 1
        started = time.monotonic()
        # What is recorded about a call is which command, on which element, and how it went: never the text typed or the label.
        info = {'cmd': cmd, **{k: params[k] for k in ('action', 'ref') if k in params}}
        try:
            self.t.send({'id': self._id, 'cmd': cmd, **params})
            reply = self.t.recv(self.DEADLINES.get(cmd, 20))
            if reply.get('id') != self._id:
                raise RunnerError('out-of-order reply')
        except Exception as exc:
            self.trace.emit('runner_error', **info, ms=int((time.monotonic() - started) * 1000), why=type(exc).__name__ + (f': {exc}' if str(exc) else ''),
                            stderr=list(getattr(self.t, 'stderr_tail', ()))[-8:])
            raise
        fields = {'ok': bool(reply.get('ok')), 'ms': int((time.monotonic() - started) * 1000)}
        if reply.get('error'):
            fields['error'] = reply['error']
        for key in ('page_fp', 'status'):
            if reply.get(key) is not None:
                fields[key] = reply[key]
        self.trace.emit('runner', **info, **fields)
        return reply

    def open(self, url): return self.call('open', url=url)
    def snapshot(self): return self.call('snapshot')
    def screenshot(self): return self.call('screenshot')

    def act(self, action, ref=None, value=None, label=None):
        params = {'action': action}
        if ref is not None:
            params['ref'] = ref
            params['expect'] = {'label': label}
        if value is not None:
            params['value'] = value
        return self.call('act', **params)

    def close(self):
        try:
            self.t.send({'id': 0, 'cmd': 'close'})
        except Exception:
            pass
        self.t.close()
