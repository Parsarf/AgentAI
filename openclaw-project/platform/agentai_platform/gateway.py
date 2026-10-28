"""Customer chat's client for the native OpenClaw Gateway of one cell (installed runtime 2026.9.6, protocol 4).

OpenClaw owns the run: model calls, tool calls, tool-result continuation, session ordering, steering and goals. Lumina only starts runs, asks the runtime when they
ended, and reads their results. Everything below is what the installed runtime does, checked against it (not against newer documentation):

- ``chat.send`` is idempotent per ``idempotencyKey`` and the key IS the run id. A repeat returns the existing run (``status`` ok when it already ended, in_flight
  while it runs); it never starts a second one. ``queueMode: "steer"`` injects the message into the session's active run (the steered input's own run id then
  reports ``ok`` with no reply of its own: the answer arrives in the active run's transcript); on an idle session it simply starts a run.
- ``agent.wait`` reports one run's end: ``ok`` with ``terminalReply`` and ``terminalReceipt`` (``successfulToolNames``), ``error`` (``error: "aborted"`` after
  ``chat.abort``), or ``timeout``/``pending`` while it still runs. A wait never stops the run. An unknown run id also reads ``timeout``, so it can only be settled
  through the transcript row ``<runId>:user`` that every admitted input leaves.
- ``chat.history`` rows carry ``__openclaw.runId`` (assistant rows) and ``idempotencyKey`` (user rows, ``<runId>:user``). A reply to a STEERED input carries a runtime-made run id of
  its own, not the key that was sent, so a reply is attributed to the input it follows (``after``: the key of the most recent user row before it), never to a run id alone.
- A goal is durable session state (``sessions.describe`` -> ``session.goal``) started with ``chat.send`` + ``intent: {kind: "session-goal-start"}``; the runtime
  does not start another turn by itself when a turn ends with the goal still active. ``sessions.goal.update`` pause/resume/block/complete/edit and ``clear`` take an
  operation id that makes a retry safe; ``resume`` starts a run.
- ``ask_user`` needs a verified user profile that the bridge's backend connection does not have, so cells deny it (see lifecycle/cell_config.py).
- After a restart the runtime resumes an interrupted main-session turn by itself when the turn was running. An input it had ACCEPTED BUT NOT STARTED comes back as an
  `interrupted` entry of `pendingInputs` (same run id) that nothing runs by itself (only a browser outbox would re-admit it) and that `chat.send` refuses to take again under
  the same key (UNAVAILABLE). The same text under a NEW key runs once, and the interrupted entry stays inert; `history` reports these as `pending` so the driver can tell.
  A cell is never stopped under a live run on purpose (the request is aborted first); this is what an unplanned stop looks like.

The binding (which cell) is resolved by the host bridge from the account; no browser-supplied URL, token, RPC name or session key is ever accepted.
"""
from __future__ import annotations
from dataclasses import replace
import re
import time
import uuid
from . import activity
from .adapters import CapabilityUnavailable, GatewayCapabilities

SUPPORTED_PROTOCOL_VERSION = 4   # installed 2026.9.6 negotiated protocol 4 in the 2026-10-12 live probe
IDENTIFIER = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
GOAL_STATES = ('active', 'paused', 'blocked', 'budget_limited', 'usage_limited', 'complete')


def session_ref(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('invalid session reference')
    return value


def negotiate(caps: GatewayCapabilities) -> GatewayCapabilities:
    """Fail closed: keep only probed capabilities on the supported protocol."""
    if caps.protocol_version != SUPPORTED_PROTOCOL_VERSION or not caps.live_probed:
        return replace(caps, send=False, history=False, events=False, abort=False, wait=False, goals=False)
    return caps


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str))
    return ''


def _goal(raw):
    """The runtime's goal object, reduced to what Lumina uses."""
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), str):
        return None
    return {'id': raw['id'], 'status': raw.get('status') if raw.get('status') in GOAL_STATES else 'unknown', 'objective': str(raw.get('objective') or '')[:300],
            'tokens_used': raw.get('tokensUsed') if type(raw.get('tokensUsed')) is int else 0, 'note': str(raw.get('lastStatusNote') or '')[:300]}


class NativeGateway:
    """Gateway client over an injected ``rpc(method, params) -> dict`` callable.

    The callable is the bridge client (the app never holds a cell token or a docker handle). Raises CapabilityUnavailable for any refusal or malformed reply.
    """
    METHODS = ('hello', 'sessions.create', 'sessions.describe', 'chat.send', 'chat.history', 'chat.abort', 'agent.wait', 'sessions.goal.update', 'sessions.goal.clear',
               'usage.snapshot', 'workspace.collect', 'cell.status', 'tools.active')

    def __init__(self, rpc):
        self._rpc = rpc
        self._caps = None

    def _call(self, method, params=None):
        if method not in self.METHODS:
            raise ValueError('unsupported rpc method')
        result = self._rpc(method, params or {})
        if not isinstance(result, dict) or '__error__' in result:        # the bridge's marker for a refused call; a run's own `error` field is a result, not a refusal
            raise CapabilityUnavailable('gateway call unavailable')
        return result

    def capabilities(self):
        if self._caps is None:
            try:
                hello = self._call('hello')
            except (CapabilityUnavailable, OSError, TimeoutError):
                self._caps = GatewayCapabilities('unverified', 0, False, False, False, False, False)
                return self._caps
            version = hello.get('protocol')
            methods = set(hello.get('methods') or ())
            self._caps = negotiate(GatewayCapabilities(
                str(hello.get('runtimeVersion', 'unverified')), version if type(version) is int else 0,
                'chat.send' in methods, 'chat.history' in methods, True, 'chat.abort' in methods, True,
                wait='agent.wait' in methods, goals={'sessions.describe', 'sessions.goal.update'} <= methods))
        return self._caps

    def require(self, operation):
        caps = self.capabilities()
        if operation not in {'send', 'history', 'abort', 'wait', 'goals'} or not getattr(caps, operation):
            raise CapabilityUnavailable('installed gateway does not support ' + operation)
        return caps

    def active_sessions(self):
        turns = self._call('tools.active').get('turns')
        if not isinstance(turns, list) or len(turns) > 32 or any(not isinstance(t, dict) or not isinstance(t.get('session_key'), str) or not isinstance(t.get('run_id'), str) for t in turns):
            raise CapabilityUnavailable('native turn state unavailable')
        return turns

    def open_session(self, operation_id, label):
        self.require('send')
        result = self._call('sessions.create', {'label': label[:64]})
        return session_ref(result.get('key')), False, None

    def send(self, session, key, message, *, queue_mode=None, goal_issued_ms=None):
        """Hand one input to the runtime. Idempotent per `key` (which becomes the run id): a repeat never starts a second run.
        -> {'run_id', 'status': started|in_flight|ok, 'duplicate', 'goal'}. `goal_issued_ms` starts a session goal with this message as its objective."""
        self.require('send')
        params = {'sessionKey': session_ref(session), 'message': message, 'idempotencyKey': session_ref(key)}
        if queue_mode:
            params['queueMode'] = queue_mode
        if goal_issued_ms is not None:
            self.require('goals')
            params['intent'] = {'kind': 'session-goal-start', 'version': 1, 'issuedAtMs': int(goal_issued_ms)}
        result = self._call('chat.send', params)
        if result.get('status') not in ('started', 'in_flight', 'ok') or not isinstance(result.get('runId'), str):
            raise CapabilityUnavailable('send admission not confirmed')
        return {'run_id': result['runId'], 'status': result['status'], 'duplicate': result['status'] != 'started', 'goal': _goal(result.get('goal'))}

    def wait(self, run_id, timeout_ms):
        """How is this run doing? -> {'status': ok|error|running, 'aborted', 'error', 'text', 'disposition', 'tools'}. 'running' covers timeout, pending and unknown."""
        self.require('wait')
        result = self._call('agent.wait', {'runId': session_ref(run_id), 'timeoutMs': int(timeout_ms)})
        status = result.get('status')
        if status == 'ok':
            reply, receipt = result.get('terminalReply') or {}, result.get('terminalReceipt') or {}
            tools = [t for t in receipt.get('successfulToolNames') or [] if isinstance(t, str)]
            return {'status': 'ok', 'aborted': False, 'error': None, 'text': reply.get('text') if reply.get('disposition') == 'visible' and isinstance(reply.get('text'), str) else None,
                    'disposition': reply.get('disposition') or receipt.get('terminalDisposition'), 'tools': tools}
        if status == 'error':
            aborted = result.get('error') == 'aborted' or result.get('stopReason') == 'rpc'
            return {'status': 'error', 'aborted': aborted, 'error': str(result.get('error') or result.get('stopReason') or 'error')[:200], 'text': None, 'disposition': None, 'tools': []}
        return {'status': 'running', 'aborted': False, 'error': None, 'text': None, 'disposition': None, 'tools': []}

    def abort(self, session, run_id=None):
        """Stop generation (it does not undo what a tool already did). -> the run ids the runtime stopped; raises unless the runtime confirms."""
        self.require('abort')
        params = {'sessionKey': session_ref(session)}
        if run_id:
            params['runId'] = session_ref(run_id)
        result = self._call('chat.abort', params)
        if result.get('aborted') is not True and result.get('ok') is not True:
            raise CapabilityUnavailable('abort not confirmed')
        return {'run_ids': [r for r in result.get('runIds') or [] if isinstance(r, str)]}

    def history(self, session, cursor=None):
        """The session's tail as normalized rows: {'id','role','content','seq','run_id','idempotency_key','after'}. A customer row carries the key it was sent under; an agent row carries
        `after`, the key of the input it follows (that is what ties a reply to its request, including the reply to a steered input) and its run id."""
        self.require('history')
        params = {'sessionKey': session_ref(session)}
        if cursor is not None:
            params['cursor'] = cursor
        result = self._call('chat.history', params)
        kind = result.get('kind', 'tail')
        if kind not in {'tail', 'delta', 'reset'}:
            raise CapabilityUnavailable('unsupported history response')
        rows, after, annotated = [], None, []
        for m in result.get('messages') or []:
            if not isinstance(m, dict):
                continue
            meta = m.get('__openclaw') or {}
            role = {'assistant': 'agent', 'user': 'customer'}.get(m.get('role'))
            idem = m.get('idempotencyKey') or meta.get('idempotencyKey')
            idem = idem if isinstance(idem, str) else None
            if role == 'customer':
                after = idem[:-5] if idem and idem.endswith(':user') else None       # the input this user row is (None: not one of ours)
            annotated.append({**m, '__after': after} if role == 'agent' else m)
            native_id, text = meta.get('id'), _text(m.get('content'))
            if role and isinstance(native_id, str) and text:
                rows.append({'id': native_id, 'role': role, 'content': text, 'seq': meta.get('seq'), 'run_id': meta.get('runId') if isinstance(meta.get('runId'), str) else None,
                             'idempotency_key': idem, 'after': after if role == 'agent' else None})
        info = result.get('sessionInfo') or {}
        pending = result.get('pendingInputs')
        items = pending.get('items') if isinstance(pending, dict) else (pending if isinstance(pending, list) else [])
        queued = pending.get('total') if isinstance(pending, dict) else (len(pending) if isinstance(pending, list) else 0)
        active = bool(info.get('hasActiveRun')) or (type(queued) is int and queued > 0 and any(not isinstance(i, dict) or i.get('state') != 'interrupted' for i in items or []))
        waiting = [{'run_id': i.get('runId'), 'state': i.get('state')} for i in items or [] if isinstance(i, dict) and isinstance(i.get('runId'), str)]
        return {'kind': kind, 'messages': rows, 'cursor': None, 'active_run': active, 'pending': waiting, 'activity': activity.extract(annotated)}

    def session_goal(self, session):
        """The session's goal, or None."""
        self.require('goals')
        described = self._call('sessions.describe', {'key': session_ref(session)})
        return _goal((described.get('session') or {}).get('goal'))

    def goal_update(self, session, goal_id, action, operation_id, note=None, objective=None, issued_ms=None):
        """pause | resume | block | complete | edit. A retry with the same operation id is a replay, never a second change. resume starts a run -> its run id."""
        self.require('goals')
        params = {'sessionKey': session_ref(session), 'goalId': session_ref(goal_id), 'operationId': session_ref(operation_id), 'action': action,
                  'issuedAtMs': int(issued_ms if issued_ms is not None else time.time() * 1000)}
        if note:
            params['note'] = note[:2000]
        if objective:
            params['objective'] = objective
        result = self._call('sessions.goal.update', params)
        return {'status': result.get('status'), 'goal': _goal(result.get('goal')), 'run_id': result.get('runId') if isinstance(result.get('runId'), str) else None}

    def goal_clear(self, session, goal_id, operation_id, issued_ms=None):
        self.require('goals')
        self._call('sessions.goal.clear', {'sessionKey': session_ref(session), 'goalId': session_ref(goal_id), 'operationId': session_ref(operation_id),
                                           'issuedAtMs': int(issued_ms if issued_ms is not None else time.time() * 1000)})

    def cell_running(self):
        """Host-observed container state, independent of the runtime websocket. Unknown is never stopped."""
        state = self._call('cell.status').get('running')
        if type(state) is not bool:
            raise CapabilityUnavailable('cell status unavailable')
        return state

    def usage_snapshot(self):
        return int(self._call('usage.snapshot')['spend_microusd'])

    def workspace_files(self, since):
        """Files the assistant wrote since `since` (epoch seconds): [(relative path, bytes)]."""
        import base64
        out = []
        for item in self._call('workspace.collect', {'since': int(since)}).get('files') or []:
            if isinstance(item, dict) and isinstance(item.get('path'), str) and isinstance(item.get('data_b64'), str):
                out.append((item['path'], base64.b64decode(item['data_b64'])))
        return out


class SyntheticGateway:
    """Deterministic in-memory stand-in that follows the same run contract as the installed runtime, for local flows and tests only.
    Never installed in the worker entry point or any request path.

    A run is started by `send`, lasts `polls` calls of `wait` (each reporting it as still running), then ends: the assistant row is written and `script(message, session)`
    may add tool names, an error, extra rows or a goal change. Steering joins the active run; the same key never starts a second run; abort ends a run as aborted."""

    def __init__(self, *, protocol_version=SUPPORTED_PROTOCOL_VERSION, abort_supported=True, polls=0, script=None,
                 fail_after_ack=False, timeout_after_write=False):
        self.protocol_version, self.abort_supported, self.polls = protocol_version, abort_supported, polls
        self.script = script
        self.fail_after_ack, self.timeout_after_write = fail_after_ack, timeout_after_write
        self.sessions: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.interrupted: set[str] = set()       # inputs a restart left accepted-but-unstarted: inert, and refused under the same key
        self.calls: list[tuple] = []
        self.on_wait = None          # hook(run) called at each wait: tests use it to cancel, steer or break things mid-run
        self.on_history = None

    # -- capabilities --------------------------------------------------------------------------------------------------------------------------
    def capabilities(self):
        return negotiate(GatewayCapabilities('synthetic-2026.9.6', self.protocol_version, True, True, True, self.abort_supported, True, wait=True, goals=True))

    def require(self, operation: str):
        caps = self.capabilities()
        if operation not in {'send', 'history', 'abort', 'wait', 'goals'} or not getattr(caps, operation):
            raise CapabilityUnavailable('installed gateway does not support ' + operation)
        return caps

    # -- sessions ------------------------------------------------------------------------------------------------------------------------------
    def open_session(self, operation_id: str, label: str):
        self.require('send')
        key = 'agent:main:synthetic:' + uuid.uuid4().hex[:16]
        self.sessions[key] = {'rows': [], 'goal': None}
        return key, False, None

    def _row(self, session, role, content, run_id=None, key=None):
        rows = self.sessions[session]['rows']
        seq = len(rows) + 1
        row = {'id': f'm{seq}', 'role': role, 'content': content, 'seq': seq, 'run_id': run_id, 'idempotency_key': key}
        rows.append(row)
        return row

    def active_run(self, session):
        return next((r for r in self.runs.values() if r['session'] == session and r['state'] in ('running', 'queued') and not r.get('merged')), None)

    def send(self, session, key, message, *, queue_mode=None, goal_issued_ms=None):
        self.require('send')
        self.calls.append(('send', session, key, queue_mode))
        if session not in self.sessions:
            raise CapabilityUnavailable('unknown session')
        if key in self.interrupted:
            raise CapabilityUnavailable('UNAVAILABLE')            # the runtime does not take an interrupted input again under its old key
        if key in self.runs:                                   # idempotent: never a second run for the same key
            run = self.runs[key]
            return {'run_id': key, 'status': 'ok' if run['state'] in ('ok', 'error') else 'in_flight', 'duplicate': True, 'goal': None}
        active = self.active_run(session)
        joins = active is not None and queue_mode == 'steer'
        if not joins:
            self._row(session, 'customer', message, key=key + ':user')
        goal = None
        if goal_issued_ms is not None:
            self.sessions[session]['goal'] = goal = {'id': 'goal-' + key, 'status': 'active', 'objective': message[:300], 'tokens_used': 0, 'note': ''}
        run = {'id': key, 'session': session, 'message': message, 'polls_left': self.polls, 'state': 'running', 'text': None, 'tools': [], 'error': None, 'steered': [], 'kind': queue_mode or 'turn'}
        if joins:
            run.update(state='ok', merged=True)                 # joins the active run: no reply of its own; its user row lands when the run takes it up, after the run's first answer
            active['steered'].append((key, message))
        elif active is not None:
            run['state'] = 'queued'                             # waits for the session lane
        self.runs[key] = run
        if self.timeout_after_write:
            raise TimeoutError('native outcome unknown after write')   # the write landed (the run exists); the caller never saw the answer and may safely send the same key again
        if self.fail_after_ack:
            raise RuntimeError('gateway lost after acknowledgement')
        return {'run_id': key, 'status': 'started', 'duplicate': False, 'goal': goal}

    # -- run lifecycle -------------------------------------------------------------------------------------------------------------------------
    def _finish(self, run):
        outcome = (self.script(run['message'], run, self) if self.script else None) or {}
        run['tools'] = outcome.get('tools', run['tools'])
        if outcome.get('error'):
            run.update(state='error', error=outcome['error'])
            return
        text = str(outcome.get('text', 'ack ' + run['id'])).strip()          # the runtime's history trims what the model wrote
        run['text'] = text
        if text:
            self._row(run['session'], 'agent', text, run['id'])
        for key, extra in run['steered']:                       # each steered input is answered in order, under a run id the runtime makes up (not the key it was sent under)
            self._row(run['session'], 'customer', extra, key=key + ':user')
            self._row(run['session'], 'agent', 'ack ' + extra[:40], 'rt-' + uuid.uuid4().hex[:12])
        run['state'] = 'ok'
        goal = self.sessions[run['session']]['goal']
        if goal and outcome.get('goal') in GOAL_STATES:
            goal['status'] = outcome['goal']

    def wait(self, run_id, timeout_ms):
        self.require('wait')
        self.calls.append(('wait', run_id))
        run = self.runs.get(run_id)
        if run is None:
            return {'status': 'running', 'aborted': False, 'error': None, 'text': None, 'disposition': None, 'tools': []}
        if self.on_wait:
            self.on_wait(run)
        if run['state'] == 'queued':
            if self.active_run(run['session']) is run or self.active_run(run['session']) is None:
                run['state'] = 'running'
            else:
                return {'status': 'running', 'aborted': False, 'error': None, 'text': None, 'disposition': None, 'tools': []}
        if run['state'] == 'running':
            if run['polls_left'] > 0:
                run['polls_left'] -= 1
                return {'status': 'running', 'aborted': False, 'error': None, 'text': None, 'disposition': None, 'tools': []}
            self._finish(run)
        if run['state'] == 'ok':
            return {'status': 'ok', 'aborted': False, 'error': None, 'text': run['text'], 'disposition': 'visible' if run['text'] else 'silent', 'tools': run['tools']}
        return {'status': 'error', 'aborted': run['error'] == 'aborted', 'error': run['error'], 'text': None, 'disposition': None, 'tools': []}

    def abort(self, session, run_id=None):
        self.require('abort')
        self.calls.append(('abort', session, run_id))
        stopped = []
        for run in self.runs.values():
            if run['session'] == session and run['state'] in ('running', 'queued') and (run_id is None or run['id'] == run_id):
                run.update(state='error', error='aborted')
                stopped.append(run['id'])
        return {'run_ids': stopped}

    def history(self, session, cursor=None):
        self.require('history')
        self.calls.append(('history', session, cursor))
        if self.on_history:
            self.on_history()
        if session not in self.sessions:
            raise CapabilityUnavailable('unknown session')
        rows, after = [], None
        for r in self.sessions[session]['rows']:
            if r['role'] == 'customer':
                key = r.get('idempotency_key')
                after = key[:-5] if key and key.endswith(':user') else None
            rows.append({**r, 'after': after if r['role'] == 'agent' else None})
        pending = [{'run_id': k, 'state': 'interrupted'} for k in sorted(self.interrupted)]
        return {'kind': 'tail', 'messages': rows, 'cursor': None, 'active_run': self.active_run(session) is not None, 'pending': pending, 'activity': []}

    # -- goals ---------------------------------------------------------------------------------------------------------------------------------
    def session_goal(self, session):
        self.require('goals')
        goal = self.sessions[session]['goal']
        return dict(goal) if goal else None

    def goal_update(self, session, goal_id, action, operation_id, note=None, objective=None, issued_ms=None):
        self.require('goals')
        self.calls.append(('goal_update', session, action, operation_id))
        goal = self.sessions[session]['goal']
        if goal is None or goal['id'] != goal_id:
            raise CapabilityUnavailable('goal not found')
        goal['status'] = {'pause': 'paused', 'resume': 'active', 'block': 'blocked', 'complete': 'complete', 'edit': goal['status']}[action]
        goal['note'] = (note or '')[:300]
        if objective:
            goal['objective'] = objective[:300]
        run_id = None
        if action == 'resume':
            self.send(session, operation_id, 'Continue pursuing the current goal.')
            run_id = operation_id
        return {'status': 'started' if run_id else 'updated', 'goal': dict(goal), 'run_id': run_id}

    def goal_clear(self, session, goal_id, operation_id, issued_ms=None):
        self.require('goals')
        self.sessions[session]['goal'] = None
