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
import traceback
import uuid
import logging

from agentai_platform.live import now as live_now
from .ladder import Decision, Handover, Ladder, Refused, parse_decision, render
from .goals import goal_parts
from .loop import BrowseRunner, Policy
from .session import Session
from .trace import NULL, Trace
from .loop import _where
from agentai_platform.privacy import scrub

log = logging.getLogger('agentai.browse')

REQUEST_ID = re.compile(r'^[a-f0-9]{32}$')
URL_IN_TEXT = re.compile(r'https?://[^\s<>"\')]+', re.I)
FILE = re.compile(r'^shot-\d{3}\.jpg$')
FINAL = ('done', 'handoff', 'stopped', 'blocked', 'budget', 'error', 'cancelled', 'stuck', 'max_steps', 'deadline')
TAKEOVER_SECONDS = 600
QUEUE_GRACE_SECONDS = 120                     # a hand-off window shrinks to this once another browser task is waiting for the one stage (an active user keeps it alive)
MIN_FREE_BYTES = 2 * 1024 ** 3                 # a browser stage needs ~1.5 GiB; below this we wait instead of starving everyone's chats
MEMORY_WAIT_SECONDS = 120
SNAPSHOT_EVERY_SECONDS = 4
SCREENSHOT_RETENTION_SECONDS = 24 * 3600    # pages can show personal data: screenshots are deleted a day after the task
PURGE_EVERY_SECONDS = 900                     # ...and this is how often the service looks for them, whether or not any task is running
MAX_CALLS = 60
MAX_URL_CHARS = 2048                          # an address typed in the live view's address bar
# A 16k request plus 12k of saved context and JSON quoting overhead.
MAX_GOAL_CHARS = 48_000
MAX_RPC_BYTES = 1 << 20  # bounded wire size, including escaped Unicode


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


def watch_purge(service, stop, every=PURGE_EVERY_SECONDS, sleep=time.sleep):
    """Enforce the retention promise on a timer. Cleaning only at start-up and when a task ends meant that after a quiet stretch the last customer's
    screenshots and live frame stayed on disk well past a day."""
    while not stop.is_set():
        try:
            service.purge()
        except Exception:
            pass
        sleep(every)


# What the owner reads to judge JEV and the hand-over to the assistant: acted steps by who decided them (jev_acted + agent_step = steps taken), how often JEV handed over
# (jev_too_complex, jev_misses, no_change_loops, claude_page_takeovers), and what the assistant did for JEV (agent_text, agent_answer).
STAT_KEYS = ('jev_calls', 'ask_answered', 'ask_remembered', 'jev_acted', 'jev_typed_from_goal', 'agent_step', 'agent_text', 'agent_answer', 'jev_needs_user', 'jev_too_complex', 'jev_misses',
             'jev_ask', 'no_change_loops', 'claude_page_takeovers', 'other_step', 'helper_text')


class BrowseError(Exception):
    pass


ASK_SECONDS = 300                              # a question waits this long for an answer (each click on the page while choosing renews it)
AGENT_WAIT_SECONDS = 180                       # how long the loop waits for the assistant's next step before it gives the task up
AGENT_RETRIES = 3                              # an invalid step is handed back to the assistant to correct this many times in a row
AGENT_STEP_FIELDS = ('action', 'ref', 'value', 'answer', 'reason', 'question', 'field', 'options', 'fields')
MAX_OBSERVATION = 9000
MAX_PREFS = 40


def clean_vault(items):
    """The readable part of what the customer keeps, so the run can offer it on a sign-in or payment page. A secret is never part of this."""
    out = []
    if isinstance(items, list):
        for i in items[:30]:
            if isinstance(i, dict) and i.get('kind') in ('login', 'card') and isinstance(i.get('id'), str) and i['id'] and all(isinstance(i.get(k, ''), str) for k in ('label', 'site')):
                out.append({'id': i['id'][:40], 'kind': i['kind'], 'label': i.get('label', '')[:80], 'site': i.get('site', '')[:120]})
    return out


def clean_prefs(prefs):
    """Saved choices the host hands to a run: short plain words by field. Never secrets (logins and cards do not travel this way)."""
    out = {}
    if isinstance(prefs, dict):
        for k, v in list(prefs.items())[:MAX_PREFS]:
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                out[k.strip().lower()[:30]] = v.strip()[:80]
    return out


class Job:
    def __init__(self, account, request_id, goal, start_url, max_cost, max_steps, max_seconds):
        self.account, self.id, self.goal, self.start_url = account, request_id, goal, start_url
        self.max_cost, self.max_steps, self.max_seconds = max_cost, max_steps, max_seconds
        self.state, self.reason, self.answer, self.url, self.pending = 'queued', '', None, '', None
        self.events, self.cost, self.calls, self.cancel = [], 0, 0, threading.Event()
        self.session, self.takeover_until, self.lock = None, 0.0, threading.Lock()
        self.engine = 'runner'                      # 'runner' (the host's Docker stage) | 'native' (the cell's own browser) | 'local' (the customer's own Chrome, through the extension); recorded on the job, never switched mid-run
        self.last_shot = 0.0
        self.trace = NULL                           # set when the run starts: the operator's record (trace.py)
        self.pause_req = threading.Event()          # the user asked for the wheel; the loop acknowledges at the next step boundary (state -> 'paused')
        self.stats = dict.fromkeys(STAT_KEYS, 0)
        self.observation, self.obs_n = None, 0      # while the assistant is asked for the next step: {'n', 'text'}
        self.agent_box, self.agent_ev = None, threading.Event()
        self.vault = []                             # the customer's saved logins and cards, readable part only (label, site, hint): the secrets never travel with the task
        self.prefs = {}                             # what the customer chose before, by field (size -> M); handed to the loop so it does not ask twice
        self.question, self.answer_box, self.answer_ev = None, None, threading.Event()      # a question waiting for the customer: {'id','title','field','options','menu'}

    def add(self, kind, data):
        with self.lock:
            self.events.append({'n': len(self.events) + 1, 'kind': kind, **data})


class BrowseService:
    def __init__(self, *, spawn, jev_for=lambda account: None, root, jev_mode='live', clock=time.monotonic,
                 takeover_seconds=TAKEOVER_SECONDS, start_picker=None, free_memory=None, sleep=time.sleep, native_spawn=None, engine_for=lambda account: 'runner', switch_for=None, local_spawn=None, devices=None):
        """spawn(job_id, out_dir) -> transport; jev_for(account) -> JevChooser|None. The only model the service itself calls is JEV: every step JEV hands over goes to the
        account's own assistant, which answers through agent_step().
        native_spawn(account, job_id, out_dir) -> transport on the account's own cell browser; local_spawn(account, job_id, out_dir) -> transport on the customer's own paired Chrome
        (raises BrowseError when it is not connected); engine_for(account) -> 'runner' | 'native' | 'local' says which a new job uses (an engine without its spawn falls back to 'runner');
        switch_for(account) -> switch(key) -> bool reads the account's safety switches (read again at every step, so a change in the menu applies at once)."""
        self.spawn, self.jev_for, self.root, self.jev_mode, self.clock = spawn, jev_for, Path(root), jev_mode, clock
        self.native_spawn, self.local_spawn, self.engine_for, self._account_slots = native_spawn, local_spawn, engine_for, {}
        self.devices = devices                      # a DeviceDesk (browse/devices.py) when the customers' own Chrome is switched on, else None
        self.switch_for = switch_for or (lambda account: (lambda key: True))      # switch_for(account) -> switch(key) -> bool: the account's safety switches (agentai_platform/safety.py); everything is on unless the owner turned it off
        self.free_memory, self.sleep = free_memory or available_memory, sleep
        self.takeover_seconds, self.jobs, self._slot, self._guard = takeover_seconds, {}, threading.Semaphore(1), threading.Lock()

    # ------------------------------------------------------------------ public operations (all scoped to the caller's account)
    def start(self, account, request_id, goal, *, start_url=None, max_cost_microusd=1_000_000, max_steps=25, max_seconds=600, prefs=None, vault=None):
        if not REQUEST_ID.fullmatch(request_id or '') or not isinstance(goal, str) or not 3 <= len(goal) <= MAX_GOAL_CHARS:
            raise BrowseError('invalid job')
        max_cost = min(int(max_cost_microusd), 5_000_000)
        with self._guard:
            existing = self.jobs.get(request_id)
            if existing:
                if existing.account != account:
                    raise BrowseError('unavailable')
                return {'ok': True, 'state': existing.state}            # idempotent
            job = Job(account, request_id, goal, start_url, max_cost, min(int(max_steps), 40), min(int(max_seconds), 900))
            job.prefs = clean_prefs(prefs)
            job.vault = clean_vault(vault)
            job.engine = self._engine(account)
            self.jobs[request_id] = job
            self._make_room(job)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return {'ok': True, 'state': 'queued'}

    def _engine(self, account):
        """The hands a new job gets. Asked only when there is somewhere other than the host stage to run; a choice we cannot serve is the host stage."""
        spawns = {'native': self.native_spawn, 'local': self.local_spawn}
        if all(v is None for v in spawns.values()):
            return 'runner'
        wanted = self.engine_for(account)
        return wanted if spawns.get(wanted) is not None else 'runner'

    def _window(self):
        """Seconds a hand-off stays open. Nobody waiting: the full window. Someone waiting for the one browser stage: a short grace, because an idle
        window would otherwise hold the stage (and make that customer's next task sit in 'queued') for up to ten minutes."""
        return min(self.takeover_seconds, QUEUE_GRACE_SECONDS) if any(j.state == 'queued' for j in list(self.jobs.values())) else self.takeover_seconds

    def _make_room(self, new_job):
        """A new browser task is about to wait for the stage. A hand-off that is only waiting out its window (its agent has finished) is closed at once if it is
        the same customer's (they moved on), or shortened to the grace period if it is somebody else's. A customer who has the wheel (paused) is never cut off."""
        now = self.clock()
        for other in list(self.jobs.values()):
            if other is new_job or other.state != 'handoff':
                continue
            other.takeover_until = 0 if other.account == new_job.account else min(other.takeover_until, now + QUEUE_GRACE_SECONDS)

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
                'cost_microusd': job.cost, 'events': events, 'takeover': job.state in ('handoff', 'paused', 'asking') and self.clock() < job.takeover_until,
                'pausing': job.state == 'running' and job.pause_req.is_set(), 'jev': dict(job.stats), 'question': self._public_question(job),
                'observation': job.observation if job.state == 'running' else None}

    def cancel(self, account, request_id):
        job = self._job(account, request_id)
        job.trace.emit('user', what='stopped the task', state=job.state)
        job.cancel.set()
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
        if job.state not in ('queued', 'running', 'paused', 'handoff', 'asking'):
            raise BrowseError('not available')
        if job.state in ('queued', 'running'):                     # a task still waiting for the stage pauses at its first step boundary
            job.pause_req.set()
        job.trace.emit('user', what='asked for the wheel', state=job.state)
        return {'ok': True, 'state': job.state}

    def resume(self, account, request_id):
        job = self._job(account, request_id)
        job.pause_req.clear()
        job.trace.emit('user', what='gave the wheel back', state=job.state)
        if job.state == 'handoff':
            job.takeover_until = 0
        return {'ok': True}

    def agent_step(self, account, request_id, step):
        """The assistant's next step, while the loop is waiting for it. Only the fields of a step are kept, bounded; the loop turns it into a decision and runs every rule on it."""
        job = self._job(account, request_id)
        if not isinstance(step, dict):
            raise BrowseError('invalid step')
        clean = {k: step[k] for k in AGENT_STEP_FIELDS if k in step}
        for key in ('action', 'value', 'answer', 'reason', 'question', 'field'):
            if key in clean and (not isinstance(clean[key], str) or len(clean[key]) > 4000):
                raise BrowseError('invalid step')
        if 'ref' in clean and (isinstance(clean['ref'], bool) or not isinstance(clean['ref'], (int, str)) or len(str(clean['ref'])) > 8):
            raise BrowseError('invalid step')
        for key in ('options', 'fields'):
            if key in clean and (not isinstance(clean[key], list) or len(clean[key]) > 20 or any(isinstance(v, bool) or not isinstance(v, (int, str)) or len(str(v)) > 8 for v in clean[key])):
                raise BrowseError('invalid step')
        with job.lock:
            if job.observation is None or job.state != 'running':
                raise BrowseError('not waiting for a step')
            job.observation = None
            job.agent_box = clean
            job.agent_ev.set()
        job.trace.emit('agent', what='gave a step', action=clean.get('action'))
        return {'ok': True}

    def agent_release(self, account, request_id):
        """The request that handed a page to its assistant is over and no step is coming: end the job now instead of after the wait. Only a job that is waiting for the assistant is touched."""
        job = self._job(account, request_id)
        with job.lock:
            waiting = job.observation is not None
        if waiting:
            job.trace.emit('agent', what='released: the request ended')
            job.cancel.set()
        return {'ok': True, 'released': waiting}

    @staticmethod
    def _public_question(job):
        q = job.question
        if not q:
            return None
        return {'id': q['id'], 'title': q['title'], 'field': q['field'], 'menu': q['menu'], 'use': q.get('use', ''), 'kind': q.get('kind', 'choice'),
                'options': [{'id': o['id'], 'label': o['label'], **({'item': o['item']} if o.get('item') else {})} for o in q['options']],
                **({'fields': [{'id': f['id'], 'label': f['label'], 'key': f['key'], 'sensitive': f['sensitive'], 'input_type': f['input_type'], 'prefill': f.get('prefill', '')} for f in q['fields']]} if q.get('fields') else {})}

    def _ask_gate(self, job):
        """The loop reached a choice the customer should make. Block here (the page stays as it is) until they answer, press Continue after choosing on the page,
        or the wait runs out. -> (answer | None, seconds waited)."""
        def gate(question, step):
            began = self.clock()
            with job.lock:
                job.answer_ev.clear()
                job.answer_box = None
                job.question = {**question, 'id': uuid.uuid4().hex[:12]}
                job.state = 'asking'
                job.takeover_until = began + ASK_SECONDS
            job.add('status', {'state': 'asking', 'reason': 'waiting for your choice'})
            job.trace.emit('ask_wait', options=len(question['options']), field=question.get('field'))
            while not job.answer_ev.is_set() and not job.cancel.is_set() and self.clock() < job.takeover_until:
                job.answer_ev.wait(0.05) if self.sleep is time.sleep else self.sleep(0.05)
            with job.lock:
                answer, job.answer_box, job.question = job.answer_box, None, None
                job.state = 'running'
            job.add('status', {'state': 'running', 'reason': 'Lumina continues'})
            return answer, self.clock() - began
        return gate

    def answer(self, account, request_id, question_id, *, option=None, resume=False, secret=None, fields=None):
        """The customer's reply to the open question: one of its options, or `resume` after choosing on the page themselves."""
        job = self._job(account, request_id)
        with job.lock:
            q = job.question
            if job.state != 'asking' or not q or q['id'] != question_id:
                raise BrowseError('not available')
            if fields is not None:                                  # the details of a form, typed by the customer one field at a time
                if q.get('kind') != 'fields' or option is not None or resume or not isinstance(fields, dict):
                    raise BrowseError('invalid answer')
                allowed = {f['id']: f for f in q['fields'] if not f['sensitive']}
                clean = {}
                for k, v in fields.items():
                    if k not in allowed or not isinstance(v, str) or len(v) > 200:
                        raise BrowseError('invalid answer')
                    if v.strip():
                        clean[k] = v.strip()
                if not clean:
                    raise BrowseError('invalid answer')
                job.answer_box = {'fields': clean}
                job.answer_ev.set()
                keys = {k: allowed[k]['key'] for k in clean}
                job.trace.emit('user', what='gave the details a form needed', fields=len(clean))
                return {'ok': True, 'field': '', 'label': None, 'keys': keys}
            if q.get('kind') == 'fields' and option is not None:
                raise BrowseError('invalid answer')
            chosen = next((o for o in q['options'] if o['id'] == option), None) if option is not None else None
            if option is not None and chosen is None:
                raise BrowseError('invalid answer')
            if option is None and not resume:
                raise BrowseError('invalid answer')
            if chosen is not None and chosen.get('item') and not (isinstance(secret, dict) and 0 < len(secret) <= 8 and all(isinstance(v, (str, int)) for v in secret.values())):
                raise BrowseError('invalid answer')               # using a saved item needs the item
            job.answer_box = ({'option': chosen['id'], **({'secret': dict(secret)} if chosen.get('item') else {})}) if chosen else {'resume': True}
            job.answer_ev.set()
        job.trace.emit('user', what='approved using a saved ' + str(q.get('use')) if chosen and chosen.get('item') else 'answered a question' if chosen else 'continued after choosing on the page')
        return {'ok': True, 'field': q['field'], 'label': chosen['label'] if chosen else None}

    def _agent_gate(self, job):
        """The loop reached a step JEV could not take. Show the assistant the page and wait for its answer (a step it sends through agent_step). An invalid step is handed back
        with the reason, a few times; no answer within the wait ends the task. Nothing the assistant sends skips a rule: the loop gates the decision like any other."""
        def gate(goal, history, page, candidates, handover, look):
            began = self.clock()
            body = render(goal, history, page, candidates)
            if not candidates:
                body += '\n\n(This page lists no controls you can use. You can scroll, go back, wait, ask, or stop.)'
            problem = ''
            for _ in range(AGENT_RETRIES):
                text = f'Handed to you because: {handover.why}.' + (f'\n{handover.hint}' if handover.hint else '') + (f'\nYour last step was not valid ({problem}). Send a valid one.' if problem else '') + '\n\n' + body
                with job.lock:
                    job.agent_ev.clear()
                    job.agent_box = None
                    job.obs_n += 1
                    job.observation = {'n': job.obs_n, 'text': text[:MAX_OBSERVATION], **({'image': look.shot['data']} if look is not None and look.shot else {})}
                job.add('status', {'state': 'running', 'reason': 'the assistant is choosing the next step'})
                while not job.agent_ev.is_set() and not job.cancel.is_set() and self.clock() - began < AGENT_WAIT_SECONDS:
                    job.agent_ev.wait(0.05) if self.sleep is time.sleep else self.sleep(0.05)
                with job.lock:
                    box, job.agent_box, job.observation = job.agent_box, None, None
                if job.cancel.is_set():
                    return Decision('stop', 'rule', 'stopped by you')
                if box is None:
                    return Decision('stop', 'rule', 'the assistant did not send a next step')
                try:
                    d = parse_decision(json.dumps(box), candidates, 'agent')
                    if d.kind == 'ask' and not d.question:
                        raise ValueError('ask without a question')
                    return d
                except ValueError as exc:
                    problem = str(exc)[:80]
                    job.trace.emit('agent', what='invalid step', why=problem)
            return Decision('stop', 'rule', 'the assistant sent steps that could not be used')
        return gate

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
        if job.state not in ('handoff', 'paused', 'asking') or self.clock() >= job.takeover_until or job.session is None:
            raise BrowseError('not available')
        if action not in ('click', 'type', 'key', 'scroll', 'goto', 'back', 'forward', 'reload'):
            raise BrowseError('invalid action')
        if action == 'goto' and not (isinstance(text, str) and len(text) <= MAX_URL_CHARS and Policy(read_only=True).url_ok(text)):
            raise BrowseError('address not allowed')          # the same domain rules as the agent; the stage also refuses private and internal addresses on every request
        with job.lock:
            if job.state not in ('handoff', 'paused', 'asking'):             # re-checked under the lock: the agent may have just resumed
                raise BrowseError('not available')
            reply = job.session.call('xy', action=action, x=x, y=y, text=text)
        if reply.get('ok'):
            job.takeover_until = self.clock() + (self._window() if job.state == 'handoff' else ASK_SECONDS if job.state == 'asking' else self.takeover_seconds)
            if job.state in ('paused', 'asking'):
                job.add('control', {'action': action, 'by': 'you'})        # the live view shows the result; the record keeps what kind of input, never the text typed
            elif self.clock() - job.last_shot >= SNAPSHOT_EVERY_SECONDS:
                # The live picture shows the result at once; this stored snapshot is only the fallback for a viewer without live frames, so
                # it is taken at most every few seconds instead of after every click (each one used to hold up the next input).
                job.last_shot = self.clock()
                shot = job.session.screenshot()
                if shot.get('ok'):
                    job.add('screenshot', {'file': shot['file'], 'by': 'you'})
        return {'ok': bool(reply.get('ok')), 'error': reply.get('error')}

    def cancel_all(self):
        """Kill switch: stop every queued or running browser task now."""
        n = 0
        for job in list(self.jobs.values()):
            if job.state in ('queued', 'running', 'handoff', 'paused', 'asking') and not job.cancel.is_set():
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
        job.trace.emit('user', what='released the browser', state=job.state)
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
            if not REQUEST_ID.fullmatch(path.name) or (job is not None and job.state in ('queued', 'running', 'handoff', 'paused', 'asking')):
                continue
            try:
                if now() - path.stat().st_mtime > max_age and self._may_purge(path, job):
                    shutil.rmtree(path, ignore_errors=True); removed += 1
            except OSError:
                continue
        return removed

    def _may_purge(self, path, job):
        """False only when the folder's account switched `screenshot_retention` off (its pictures are then kept until it is switched back on). An unknown owner is purged."""
        try:
            account = job.account if job is not None else (path / 'account').read_text().strip()
        except OSError:
            return True
        return self.switch_for(account)('screenshot_retention') if account else True

    # ------------------------------------------------------------------ job thread
    def _admit(self, job):
        def admit(kind):
            if job.cancel.is_set():
                return False
            if kind == 'jev':
                return job.calls < MAX_CALLS * 2
            return False
        return admit

    def _pick_start(self, job):
        """Where the browser begins: the address the task names. The assistant always names the site (the tool requires it), so nothing here has to guess one."""
        found = URL_IN_TEXT.search(goal_parts(job.goal)[0])
        candidate = job.start_url or (found.group(0).rstrip('.,;') if found else None)
        if candidate:
            return candidate
        raise BrowseError('Could not choose a starting page. Please include the website URL in your request.')

    def _crash_trace(self, job, exc, what):
        """Where an unexpected failure happened: the error type, its short redacted text and the code lines it passed through (file and line, not values)."""
        frames = [f'{Path(f.filename).name}:{f.lineno} {f.name}' for f in traceback.extract_tb(exc.__traceback__)][-8:]
        try:
            (job.trace if job.trace is not NULL else Trace(self.root / job.id / 'trace.jsonl')).emit('crash', what=what, error=type(exc).__name__, why=str(exc), frames=frames)
            log.warning('browse: %s failed (%s: %s); trace %s', job.id, type(exc).__name__, scrub(str(exc), 120, force=True), self.root / job.id / 'trace.jsonl')
        except Exception:
            pass

    def _slot_for(self, job):
        """The host's one Docker stage for a runner job; for a native or local job the browser is the account's own (in its cell, or on its computer), so the only thing to wait for is that account's previous browser job."""
        if job.engine == 'runner':
            return self._slot
        with self._guard:
            return self._account_slots.setdefault(job.account, threading.Semaphore(1))

    def _run(self, job):
        slot = self._slot_for(job)
        slot.acquire()
        stage = None
        try:
            if job.cancel.is_set():
                job.state, job.reason = 'cancelled', 'stopped by you'
                return
            if job.engine == 'runner' and not self._wait_for_memory(job):
                job.state = 'cancelled' if job.cancel.is_set() else 'error'
                job.reason = 'stopped by you' if job.cancel.is_set() else 'the server is busy right now; please try again in a minute'
                job.add('status', {'state': job.state, 'reason': job.reason})
                return
            job.state = 'running'
            out_dir = self.root / job.id / 'out'
            out_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(out_dir, 0o777)               # the stage runs as uid 1000; the directory holds only screenshots
            marker = self.root / job.id / 'account'          # which account owns this folder, for the purge after a restart (the `screenshot_retention` switch is the account's)
            marker.write_text(job.account); os.chmod(marker, 0o600)
            job.trace = trace = Trace(self.root / job.id / 'trace.jsonl')
            trace.emit('start', engine=job.engine, jev_mode=self.jev_mode, goal_chars=len(job.goal), max_steps=job.max_steps, max_seconds=job.max_seconds, max_cost_microusd=job.max_cost,
                       where=_where(job.start_url or ''))
            start = self._pick_start(job)
            transport = {'native': self.native_spawn, 'local': self.local_spawn}[job.engine](job.account, job.id, out_dir) if job.engine != 'runner' else self.spawn(job.id, out_dir)
            stage = transport
            job.session = session = Session(transport, trace=trace)
            jev = self.jev_for(job.account) if self.jev_mode != 'off' else None
            trace.emit('ready', start=_where(start), jev=jev is not None, decider=type(jev).__name__ if jev is not None else '')       # JevChooser (standard) | UltrafastChooser (the owner's switch is off)
            ladder = Ladder(admit=self._admit(job), jev=jev, agent=self._agent_gate(job), max_cost=job.max_cost, trace=trace, on_call=lambda: job.stats.__setitem__('jev_calls', job.stats['jev_calls'] + 1))

            def on_event(kind, data):
                job.add(kind, data)
                if kind in ('opened', 'step') and data.get('url'):
                    job.url = data['url']

            def on_stat(name, n=1):
                job.stats[name] = job.stats.get(name, 0) + n

            now_seq = [0]

            def on_now(by, mode, note):
                now_seq[0] += 1
                live_now.write(out_dir, now_seq[0], by, mode, note)      # who is deciding, for the live view (codes only)

            result = BrowseRunner(session, ladder, policy=Policy(read_only=True, switch=self.switch_for(job.account)), on_event=on_event, on_stat=on_stat, cancelled=job.cancel.is_set,
                                  max_steps=job.max_steps, max_seconds=job.max_seconds, pause_gate=self._pause_gate(job), trace=trace, on_now=on_now, ask_gate=self._ask_gate(job), prefs=job.prefs, vault=job.vault).run(job.goal, start)
            job.cost += result.cost_microusd
            job.answer, job.reason, job.pending = result.answer, result.reason, result.pending_action
            job.url = result.url or job.url
            if result.status == 'handoff':
                job.takeover_until = self.clock() + self._window()
                shot = session.screenshot()
                if shot.get('ok'):
                    job.add('screenshot', {'file': shot['file'], 'by': 'lumina'})
            job.state = result.status
            job.trace.emit('final', state=job.state, reason=job.reason, stats=dict(job.stats), cost_microusd=job.cost)
            log.info('browse: %s ended %s (%s); trace %s', job.id, job.state, scrub(job.reason, 120, force=True), self.root / job.id / 'trace.jsonl')
            job.add('status', {'state': job.state, 'reason': job.reason, 'stats': dict(job.stats)})       # kept with the run in browse_steps: no schema change needed
            while job.state == 'handoff' and self.clock() < job.takeover_until and not job.cancel.is_set():
                time.sleep(0.2)                    # the user may take over; the stage stays up only for this window
        except (BrowseError, Refused) as exc:
            self._crash_trace(job, exc, 'stopped before the run')
            job.state = 'budget' if isinstance(exc, Refused) else 'error'
            job.reason = 'The browser spending limit was reached before startup.' if isinstance(exc, Refused) else str(exc)
            job.add('status', {'state': job.state, 'reason': job.reason})
        except Exception as exc:                   # a crash must never leave the shared stage slot held
            self._crash_trace(job, exc, 'crash')
            job.state, job.reason = 'error', f'the browser run failed ({type(exc).__name__})'
            job.add('status', {'state': 'error', 'reason': job.reason})
        finally:
            if job.session is not None:
                job.session.close()
            elif stage is not None:
                stage.close()
            job.session = None
            slot.release()
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
                line = self.rfile.readline(MAX_RPC_BYTES + 1)
                if len(line) > MAX_RPC_BYTES:
                    raise BrowseError('request too large')
                req = json.loads(line)
                account, op = req['account_id'], req['op']
                if not isinstance(account, str):
                    raise BrowseError('invalid request')
                rid = req.get('request_id')
                if op == 'start':
                    out = service.start(account, rid, req['goal'], start_url=req.get('start_url'), max_cost_microusd=req.get('max_cost_microusd', 1_000_000),
                                        max_steps=req.get('max_steps', 25), max_seconds=req.get('max_seconds', 600), prefs=req.get('prefs'), vault=req.get('vault'))
                elif op == 'poll':
                    out = service.poll(account, rid, int(req.get('since', 0)))
                elif op == 'cancel':
                    out = service.cancel(account, rid)
                elif op == 'release':
                    out = service.release(account, rid)
                elif op == 'agent_release':
                    out = service.agent_release(account, rid)
                elif op == 'agent_step':
                    out = service.agent_step(account, rid, req.get('step'))
                elif op == 'pause':
                    out = service.pause(account, rid)
                elif op == 'resume':
                    out = service.resume(account, rid)
                elif op == 'answer':
                    out = service.answer(account, rid, str(req.get('question_id') or ''), option=req.get('option'), resume=bool(req.get('resume')), secret=req.get('secret'), fields=req.get('fields'))
                elif op == 'shot':
                    out = {'jpeg_b64': base64.b64encode(service.shot(account, rid, req.get('file'))).decode()}
                elif op == 'control':
                    out = service.control(account, rid, req.get('action'), x=req.get('x'), y=req.get('y'), text=req.get('text'))
                elif op in ('device_pair', 'device_list', 'device_revoke', 'device_use'):
                    if service.devices is None:
                        raise BrowseError('devices off')
                    out = (service.devices.pair(account) if op == 'device_pair' else service.devices.listing(account) if op == 'device_list'
                           else service.devices.use(account, req.get('on') is True) if op == 'device_use'
                           else service.devices.revoke(account, str(req.get('device_id') or '')[:40]))
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
