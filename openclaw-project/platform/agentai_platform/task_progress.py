"""Agent-reported work/checkpoints. Display only: never approves, launches or settles execution."""
from __future__ import annotations
import json
import re
from .activity import clean
from .events import EventService
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict

TOOL_NAME = 'lumina_task_update'
STEP_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['id', 'title', 'status'], 'properties': {
    'id': {'type': 'string', 'pattern': '^[a-z][a-z0-9_-]{0,47}$'},
    'title': {'type': 'string', 'minLength': 1, 'maxLength': 100},
    'checkpoint': {'type': 'string', 'minLength': 1, 'maxLength': 240},
    'result': {'type': 'string', 'minLength': 1, 'maxLength': 240},
    'status': {'type': 'string', 'enum': ['pending', 'running', 'done', 'blocked', 'failed', 'skipped']}}}
TOOL = {'name': TOOL_NAME, 'description': (
    'Update the Active Task checklist for your current request. Display only; grants no approval. '
    'For simple work use direct mode and append actual work as you go, with the current step last and earlier finished steps done. '
    'When planning is useful, use plan mode with 2-8 short phases and a concrete checkpoint per phase. '
    'Send the complete list with stable IDs on each update. Mark a phase done only after its checkpoint is met, with a short result; '
    'mark blocked/failed honestly. Do not invent progress or ask for approval just to plan. '
    'Call with {} to read your current task_id and progress revision (also for native goals). Use that revision and a unique update_id, reused only for an identical retry. '
    'The reply returns the suggested bullet plan and checkpoint instructions to follow.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False,
        'required': ['task_id', 'update_id', 'revision', 'mode', 'steps'], 'properties': {
            'task_id': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'update_id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,64}$'},
            'revision': {'type': 'integer', 'minimum': 0},
            'mode': {'type': 'string', 'enum': ['direct', 'plan']},
            'steps': {'type': 'array', 'minItems': 1, 'maxItems': 24, 'items': STEP_SCHEMA}}}}
TOOL['inputSchema']['anyOf'] = [{'maxProperties': 0}, {'required': TOOL['inputSchema'].pop('required')}]
TERMINAL = {'done', 'skipped'}
TRANSITIONS = {'pending': {'pending', 'running', 'skipped'}, 'running': {'running', 'done', 'blocked', 'failed'},
               'blocked': {'blocked', 'running', 'failed', 'skipped'}, 'failed': {'failed', 'running', 'skipped'},
               'done': {'done'}, 'skipped': {'skipped'}}


def validate(arguments):
    if not isinstance(arguments, dict) or set(arguments) != {'task_id', 'update_id', 'revision', 'mode', 'steps'}:
        raise ValueError('Send task_id, update_id, revision, mode and steps only.')
    if not isinstance(arguments['task_id'], str) or not 1 <= len(arguments['task_id']) <= 128:
        raise ValueError('Invalid task_id.')
    if not isinstance(arguments['update_id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', arguments['update_id']):
        raise ValueError('Invalid update_id.')
    if type(arguments['revision']) is not int or arguments['revision'] < 0 or arguments['mode'] not in ('direct', 'plan'):
        raise ValueError('Invalid revision or mode.')
    steps = arguments['steps']; mode = arguments['mode']
    if not isinstance(steps, list) or not (2 if mode == 'plan' else 1) <= len(steps) <= (8 if mode == 'plan' else 24):
        raise ValueError('Use 2-8 plan phases or 1-24 direct work steps.')
    out, seen = [], set()
    for raw in steps:
        if not isinstance(raw, dict) or set(raw) - {'id', 'title', 'status', 'checkpoint', 'result'}:
            raise ValueError('Unknown step fields.')
        sid, status = raw.get('id'), raw.get('status')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', sid) or sid in seen:
            raise ValueError('Step IDs must be unique short lowercase identifiers.')
        if not isinstance(status, str) or status not in TRANSITIONS:
            raise ValueError('Invalid step status.')
        seen.add(sid); step = {'id': sid, 'status': status}
        for key, limit in [('title', 100), ('checkpoint', 240), ('result', 240)]:
            value = raw.get(key)
            if key == 'title' or value is not None or (key == 'checkpoint' and mode == 'plan') or (key == 'result' and status == 'done' and mode == 'plan'):
                if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
                    raise ValueError(f'{key} requires 1-{limit} characters; planned completion needs a checkpoint result.')
                step[key] = clean(value, limit)
        out.append(step)
    live = [s for s in out if s['status'] in ('running', 'blocked', 'failed')]
    if len(live) > 1:
        raise ValueError('Only one phase may be current. Finish it before starting another.')
    if live and any(s['status'] == 'pending' for s in out[:out.index(live[0])]):
        raise ValueError('Work through the suggested plan in order.')
    if mode == 'direct' and (any(s['status'] == 'pending' for s in out) or (live and out[-1] != live[0])):
        raise ValueError('Direct work lists finished steps first and current work last; do not pre-plan it.')
    return out


class TaskProgressTool:
    def __init__(self, store):
        self.store, self.coordinator, self.events = store, Coordinator(store), EventService(store)

    def call(self, account, arguments, closed=lambda: False, name=TOOL_NAME):
        try:
            if arguments == {}:
                return self.current(account)
            steps = validate(arguments)
            if closed():
                return 'The connection closed; progress was not changed.', True
            task = arguments['task_id']
            with self.coordinator.transaction() as con:
                row = con.execute("""SELECT r.id FROM customer_requests r JOIN accounts a ON a.id=r.account_id
                    WHERE r.account_id=? AND r.id=? AND a.status='active' AND r.state IN ('starting','running')
                    AND r.closing=0 AND r.cancel_requested=0""", (account, task)).fetchone()
                if not row:
                    raise ValueError('This request is not running for this cell; progress was not changed.')
                history = con.execute("SELECT public_payload FROM events WHERE account_id=? AND task_id=? AND kind='task_steps' ORDER BY sequence DESC", (account, task)).fetchall()
                previous = json.loads(history[0][0]) if history else None
                for h in history:
                    saved = json.loads(h[0])
                    if saved['update_id'] == arguments['update_id']:
                        if saved['mode'] != arguments['mode'] or saved['steps'] != steps:
                            raise ValueError('update_id already used with different content.')
                        return self.reply(saved), False
                revision = previous['revision'] if previous else 0
                if arguments['revision'] != revision:
                    return 'Stale progress revision. Current snapshot: ' + json.dumps(previous or {'revision': 0}), True
                if previous:
                    old = previous['steps']
                    if arguments['mode'] != previous['mode']:
                        raise ValueError('Keep the chosen mode for this task; append or revise pending work as needed.')
                    if len(steps) < len(old) or [s['id'] for s in steps[:len(old)]] != [s['id'] for s in old]:
                        raise ValueError('Preserve existing step IDs and order; append new work when needed.')
                    for before, after in zip(old, steps):
                        if after['status'] not in TRANSITIONS[before['status']]:
                            raise ValueError('Invalid transition for ' + before['id'])
                        if before['status'] != 'pending' and any(before.get(k) != after.get(k) for k in ('title', 'checkpoint')):
                            raise ValueError('Do not rewrite work that has started.')
                        if before['status'] in TERMINAL and before != after:
                            raise ValueError('Do not rewrite finished work.')
                    for s in steps[len(old):]:
                        if s['status'] not in ('pending', 'running'):
                            raise ValueError('New work must start pending or running.')
                elif any(s['status'] not in ('pending', 'running') for s in steps):
                    raise ValueError('Start progress before reporting completion.')
                payload = {'revision': revision + 1, 'update_id': arguments['update_id'], 'mode': arguments['mode'], 'steps': steps}
                self.events.append_in(con, account, task, 'task_steps', payload, 'agent')
            return self.reply(payload), False
        except (ValueError, Conflict) as error:
            return str(error), True

    def current(self, account):
        """Read-only recovery for native goals/restarts, which retain the customer's raw objective."""
        with self.store.connect() as con:
            rows = con.execute("""SELECT r.id FROM customer_requests r JOIN accounts a ON a.id=r.account_id
                WHERE r.account_id=? AND a.status='active' AND r.state IN ('starting','running')
                AND r.closing=0 AND r.cancel_requested=0 LIMIT 2""", (account,)).fetchall()
            if len(rows) != 1:
                return 'No single active request is available for this cell.', True
            task = rows[0]['id']
            saved = con.execute("SELECT public_payload FROM events WHERE account_id=? AND task_id=? AND kind='task_steps' ORDER BY sequence DESC LIMIT 1", (account, task)).fetchone()
            snapshot = json.loads(saved[0]) if saved else {'revision': 0, 'steps': []}
        return 'Current task progress (read only): ' + json.dumps({'task_id': task, **{k: v for k, v in snapshot.items() if k != 'source'}}) + '. Use this task_id and revision for your next update. Choose direct execution unless a concise checkpoint plan helps; update statuses as work actually changes.', False

    @staticmethod
    def reply(snapshot):
        lines = [f'Active Task updated. revision={snapshot["revision"]}. Suggested work:']
        for s in snapshot['steps']:
            lines.append(f'- [{s["status"]}] {s["id"]}: {s["title"]}' + (f' — Checkpoint: {s["checkpoint"]}' if s.get('checkpoint') else ''))
        lines.append('Execute the current step. Report status changes with this tool; mark done only after checking the result, then start the next phase. Report blocked or failed when needed. This is progress reporting, not permission to perform a gated action.')
        return '\n'.join(lines)
