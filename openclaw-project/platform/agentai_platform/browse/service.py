"""Host service that runs browse jobs: one sandboxed Chromium stage at a time, the loop, takeover and screenshots.

Runs as root (it launches docker stages and reads tenant model keys); the app talks to it only over a private unix socket and
can only start/poll/cancel/control jobs that belong to its own account. Pure logic with injected spawn/LLM so it is testable offline.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import struct
import threading
import time
import uuid

from . import llm as llm_mod
from .ladder import JevChooser, Ladder
from .loop import BrowseRunner, Policy
from .session import Session

REQUEST_ID = re.compile(r'^[a-f0-9]{32}$')
URL_IN_TEXT = re.compile(r'https?://[^\s<>"\')]+', re.I)
FILE = re.compile(r'^shot-\d{3}\.jpg$')
FINAL = ('done', 'handoff', 'stopped', 'blocked', 'budget', 'error', 'cancelled', 'stuck', 'max_steps', 'deadline')
TAKEOVER_SECONDS = 600
MIN_FREE_BYTES = 2 * 1024 ** 3                 # a browser stage needs ~1.5 GiB; below this we wait instead of starving everyone's chats
MEMORY_WAIT_SECONDS = 120
SCREENSHOT_RETENTION_SECONDS = 24 * 3600    # pages can show personal data: screenshots are deleted a day after the task
MAX_CALLS = 60


def available_memory():
    try:
        with open('/proc/meminfo') as handle:
            for line in handle:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 1 << 62                               # unreadable (not Linux): do not block


def watch_kill_switch(service, is_on, stop, interval=3, sleep=time.sleep):
    """While the owner's browse_tasks switch is off, every running browser task is stopped within `interval` seconds."""
    while not stop.is_set():
        try:
            if not is_on():
                service.cancel_all()
        except Exception:
            pass
        sleep(interval)


class BrowseError(Exception):
    pass


class Job:
    def __init__(self, account, request_id, goal, start_url, max_cost, max_steps, max_seconds):
        self.account, self.id, self.goal, self.start_url = account, request_id, goal, start_url
        self.max_cost, self.max_steps, self.max_seconds = max_cost, max_steps, max_seconds
        self.state, self.reason, self.answer, self.url, self.pending = 'queued', '', None, '', None
        self.events, self.cost, self.calls, self.cancel = [], 0, 0, threading.Event()
        self.session, self.takeover_until, self.lock = None, 0.0, threading.Lock()
        self.pause_req = threading.Event()          # the user asked for the wheel; the loop acknowledges at the next step boundary (state -> 'paused')
        self.stats = {'jev_asked': 0, 'jev_agree': 0}

    def add(self, kind, data):
        with self.lock:
            self.events.append({'n': len(self.events) + 1, 'kind': kind, **data})


class BrowseService:
    def __init__(self, *, spawn, llm_for, jev_for=lambda account: None, root, jev_mode='shadow', clock=time.monotonic,
                 takeover_seconds=TAKEOVER_SECONDS, start_picker=None, free_memory=None, sleep=time.sleep):
        """spawn(job_id, out_dir) -> transport; llm_for(account) -> callable(tier, system, user); jev_for(account) -> JevChooser|None."""
        self.spawn, self.llm_for, self.jev_for, self.root, self.jev_mode, self.clock = spawn, llm_for, jev_for, Path(root), jev_mode, clock
        self.free_memory, self.sleep = free_memory or available_memory, sleep
        self.takeover_seconds, self.jobs, self._slot, self._guard = takeover_seconds, {}, threading.Semaphore(1), threading.Lock()

    # ------------------------------------------------------------------ public operations (all scoped to the caller's account)
    def start(self, account, request_id, goal, *, start_url=None, max_cost_microusd=1_000_000, max_steps=25, max_seconds=600):
        if not REQUEST_ID.fullmatch(request_id or '') or not isinstance(goal, str) or not 3 <= len(goal) <= 2000:
            raise BrowseError('invalid job')
        max_cost = min(int(max_cost_microusd), 5_000_000)
        with self._guard:
            existing = self.jobs.get(request_id)
            if existing:
                if existing.account != account:
                    raise BrowseError('unavailable')
                return {'ok': True, 'state': existing.state}            # idempotent
            job = Job(account, request_id, goal, start_url, max_cost, min(int(max_steps), 40), min(int(max_seconds), 900))
            self.jobs[request_id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return {'ok': True, 'state': 'queued'}

    def _job(self, account, request_id):
        job = self.jobs.get(request_id)
        if job is None or job.account != account:
            raise BrowseError('unavailable')
        return job

    def poll(self, account, request_id, since=0):
        job = self._job(account, request_id)
        with job.lock:
            events = [e for e in job.events if e['n'] > since]
        return {'state': job.state, 'reason': job.reason, 'answer': job.answer, 'url': job.url, 'pending_action': job.pending,
                'cost_microusd': job.cost, 'events': events, 'takeover': job.state in ('handoff', 'paused') and self.clock() < job.takeover_until,
                'pausing': job.state == 'running' and job.pause_req.is_set(), 'jev': dict(job.stats)}

    def cancel(self, account, request_id):
        self._job(account, request_id).cancel.set()
        return {'ok': True}

    def shot(self, account, request_id, name):
        self._job(account, request_id)
        if not FILE.fullmatch(name or ''):
            raise BrowseError('unavailable')
        path = self.root / request_id / 'out' / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise BrowseError('unavailable')
        return path.read_bytes()

    def pause(self, account, request_id):
        """Hop in at any time: the agent finishes the step it is on, then waits; the user can then click and type. Returns at once
        (the state turns 'paused' when the agent has stopped; until then control is refused so two hands never share the page)."""
        job = self._job(account, request_id)
        if job.state not in ('running', 'paused', 'handoff'):
            raise BrowseError('not available')
        if job.state == 'running':
            job.pause_req.set()
        return {'ok': True, 'state': job.state}

    def resume(self, account, request_id):
        job = self._job(account, request_id)
        job.pause_req.clear()
        if job.state == 'handoff':
            job.takeover_until = 0
        return {'ok': True}

    def _pause_gate(self, job):
        def gate():
            if not job.pause_req.is_set():
                return 0
            began = self.clock()
            job.state = 'paused'
            job.takeover_until = began + self.takeover_seconds     # idle limit: an abandoned pause hands the wheel back
            job.add('status', {'state': 'paused', 'reason': 'you took over'})
            while job.pause_req.is_set() and not job.cancel.is_set() and self.clock() < job.takeover_until:
                self.sleep(0.05)
            job.pause_req.clear()
            with job.lock:                                         # a click already on its way finishes before the agent touches the page again
                job.state = 'running'
            job.add('status', {'state': 'running', 'reason': 'Lumina continues'})
            return self.clock() - began
        return gate

    def control(self, account, request_id, action, *, x=None, y=None, text=None):
        """Takeover: after a hand-off, or while paused, only while the window is open, one action at a time."""
        job = self._job(account, request_id)
        if job.state not in ('handoff', 'paused') or self.clock() >= job.takeover_until or job.session is None:
            raise BrowseError('not available')
        if action not in ('click', 'type', 'key', 'scroll'):
            raise BrowseError('invalid action')
        with job.lock:
            if job.state not in ('handoff', 'paused'):             # re-checked under the lock: the agent may have just resumed
                raise BrowseError('not available')
            reply = job.session.call('xy', action=action, x=x, y=y, text=text)
        if reply.get('ok'):
            job.takeover_until = self.clock() + self.takeover_seconds
            if job.state == 'paused':
                job.add('control', {'action': action, 'by': 'you'})        # the live view shows the result; the record keeps what kind of input, never the text typed
            else:
                shot = job.session.screenshot()
                if shot.get('ok'):
                    job.add('screenshot', {'file': shot['file'], 'by': 'you'})
        return {'ok': bool(reply.get('ok')), 'error': reply.get('error')}

    def cancel_all(self):
        """Kill switch: stop every queued or running browser task now."""
        n = 0
        for job in list(self.jobs.values()):
            if job.state in ('queued', 'running', 'handoff', 'paused') and not job.cancel.is_set():
                job.cancel.set(); n += 1
        return n

    def _wait_for_memory(self, job):
        waited = 0
        while self.free_memory() < MIN_FREE_BYTES:
            if job.cancel.is_set() or waited >= MEMORY_WAIT_SECONDS:
                return False
            self.sleep(2); waited += 2
        return True

    def release(self, account, request_id):
        job = self._job(account, request_id)
        job.takeover_until = 0
        return {'ok': True}

    def purge(self, max_age=SCREENSHOT_RETENTION_SECONDS, now=time.time):
        """Delete screenshot folders of finished tasks older than max_age. Never touches a task that is still live."""
        removed = 0
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return 0
        for path in entries:
            job = self.jobs.get(path.name)
            if not REQUEST_ID.fullmatch(path.name) or (job is not None and job.state in ('queued', 'running', 'handoff', 'paused')):
                continue
            try:
                if now() - path.stat().st_mtime > max_age:
                    shutil.rmtree(path, ignore_errors=True); removed += 1
            except OSError:
                continue
        return removed

    # ------------------------------------------------------------------ job thread
    def _admit(self, job):
        def admit(kind):
            if job.cancel.is_set():
                return False
            if kind == 'jev':
                return job.calls < MAX_CALLS * 2
            est = llm_mod.MAX_CALL_ESTIMATE[kind]
            if job.cost + est > job.max_cost or job.calls >= MAX_CALLS:
                return False
            job.calls += 1
            return True
        return admit

    def _pick_start(self, job, llm):
        found = URL_IN_TEXT.search(job.goal)
        candidate = job.start_url or (found.group(0).rstrip('.,;') if found else None)
        if candidate:
            return candidate
        try:
            reply = llm('haiku', 'Reply with ONLY one https:// URL: the best well-known website to start this task. No other text.', job.goal[:500])
            job.cost += reply.get('cost_microusd', 0); job.calls += 1
            m = URL_IN_TEXT.search(reply['text'])
            if m:
                return m.group(0).rstrip('.,;')
        except Exception:
            pass
        return 'https://www.bing.com/'

    def _run(self, job):
        self._slot.acquire()
        stage = None
        try:
            if job.cancel.is_set():
                job.state, job.reason = 'cancelled', 'stopped by you'
                return
            if not self._wait_for_memory(job):
                job.state = 'cancelled' if job.cancel.is_set() else 'error'
                job.reason = 'stopped by you' if job.cancel.is_set() else 'the server is busy right now; please try again in a minute'
                job.add('status', {'state': job.state, 'reason': job.reason})
                return
            job.state = 'running'
            out_dir = self.root / job.id / 'out'
            out_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(out_dir, 0o777)               # the stage runs as uid 1000; the directory holds only screenshots
            llm = self.llm_for(job.account)
            start = self._pick_start(job, llm)
            transport = self.spawn(job.id, out_dir)
            stage = transport
            job.session = session = Session(transport)
            jev = self.jev_for(job.account) if self.jev_mode != 'off' else None

            def tracked(tier, system, user):
                reply = llm(tier, system, user)
                job.cost += reply.get('cost_microusd', 0)
                return {**reply, 'cost_microusd': 0}      # cost is added once here; the loop's own sum stays 0

            ladder = Ladder(tracked, admit=self._admit(job), jev=jev, shadow=(self.jev_mode == 'shadow'))

            def on_event(kind, data):
                if kind == 'step' and data.get('agree') is not None:
                    job.stats['jev_asked'] += 1
                    job.stats['jev_agree'] += 1 if data['agree'] else 0
                job.add(kind, data)
                if kind in ('opened', 'step') and data.get('url'):
                    job.url = data['url']

            result = BrowseRunner(session, ladder, policy=Policy(read_only=True), on_event=on_event, cancelled=job.cancel.is_set,
                                  max_steps=job.max_steps, max_seconds=job.max_seconds, pause_gate=self._pause_gate(job)).run(job.goal, start)
            job.cost += result.cost_microusd
            job.answer, job.reason, job.pending = result.answer, result.reason, result.pending_action
            job.url = result.url or job.url
            if result.status == 'handoff':
                job.takeover_until = self.clock() + self.takeover_seconds
                shot = session.screenshot()
                if shot.get('ok'):
                    job.add('screenshot', {'file': shot['file'], 'by': 'lumina'})
            job.state = result.status
            job.add('status', {'state': job.state, 'reason': job.reason})
            while job.state == 'handoff' and self.clock() < job.takeover_until and not job.cancel.is_set():
                time.sleep(0.2)                    # the user may take over; the stage stays up only for this window
        except Exception as exc:                   # a crash must never leave the shared stage slot held
            job.state, job.reason = 'error', f'the browser run failed ({type(exc).__name__})'
            job.add('status', {'state': 'error', 'reason': job.reason})
        finally:
            if job.session is not None:
                job.session.close()
            elif stage is not None:
                stage.close()
            job.session = None
            self._slot.release()
            self.purge()


# ---------------------------------------------------------------------- unix socket server
def linux_peer_uid(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]


def serve(service, path, *, allowed_uids, group_gid=None, peer_uid=linux_peer_uid):
    import base64

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            if peer_uid(self.request) not in allowed_uids:
                return
            try:
                req = json.loads(self.rfile.readline(65536))
                account, op = req['account_id'], req['op']
                if not isinstance(account, str):
                    raise BrowseError('invalid request')
                rid = req.get('request_id')
                if op == 'start':
                    out = service.start(account, rid, req['goal'], start_url=req.get('start_url'), max_cost_microusd=req.get('max_cost_microusd', 1_000_000),
                                        max_steps=req.get('max_steps', 25), max_seconds=req.get('max_seconds', 600))
                elif op == 'poll':
                    out = service.poll(account, rid, int(req.get('since', 0)))
                elif op == 'cancel':
                    out = service.cancel(account, rid)
                elif op == 'release':
                    out = service.release(account, rid)
                elif op == 'pause':
                    out = service.pause(account, rid)
                elif op == 'resume':
                    out = service.resume(account, rid)
                elif op == 'shot':
                    out = {'jpeg_b64': base64.b64encode(service.shot(account, rid, req.get('file'))).decode()}
                elif op == 'control':
                    out = service.control(account, rid, req.get('action'), x=req.get('x'), y=req.get('y'), text=req.get('text'))
                else:
                    raise BrowseError('unknown operation')
                reply = {'ok': True, 'result': out}
            except BrowseError as exc:
                reply = {'ok': False, 'error': str(exc)}
            except Exception:
                reply = {'ok': False, 'error': 'service error'}
            self.wfile.write((json.dumps(reply) + '\n').encode())

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    if os.path.exists(path):
        os.unlink(path)
    server = Server(path, Handler)
    os.chmod(path, 0o660)
    if group_gid is not None:
        os.chown(path, 0, group_gid)
    return server


def stage_argv(job_id, out_dir, runner_dir, image, *, name=None):
    """The fixed, hardened command for one browser stage. Nothing customer-supplied reaches it (job id is hex; paths are host-made)."""
    if not REQUEST_ID.fullmatch(job_id):
        raise ValueError('invalid job id')
    return ['docker', 'run', '--rm', '-i', '--name', name or f'lumina-browse-{job_id[:12]}', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '256',
            '--memory', '1536m', '--cpus', '1', '--user', '1000:1000', '-v', f'{runner_dir}:/job:ro', '-v', f'{out_dir}:/out:rw', '-w', '/job',
            '-e', 'HOME=/tmp/h', '-e', 'BROWSE_OUT=/out', '-e', 'BROWSE_CHROME=/usr/bin/chromium', '--entrypoint', 'node', image, 'runner.mjs']
