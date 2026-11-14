"""One customer-facing picture of a task, computed in one place (stdlib only).

Every surface (the chat's work card, the workspace, Activity, Home, the rail, the browser side panel) used to derive "what is Lumina doing" by itself, from
different endpoints, on different timers, so they could disagree. This module is the single derivation. It reads only what Lumina itself recorded:

    customer_requests   the state machine (request_states.py) and the verdict (outcome.py)
    events              the redacted public timeline (events.py): tool use, the assistant's own checklist, notes, errors, approvals
    mcp_calls           permission prompts that are waiting for the customer
    browse_runs         whether the browser is waiting for the customer
    artifacts           files the task saved

and turns it into fixed vocabulary. Nothing here is written by a model, except two things that are always labelled as the assistant's own report: the titles
of its checklist steps and the text of its replies (which this module never reads). Private model reasoning is not stored anywhere, so it cannot appear.

Two different questions stay separate all the way to the screen:

    phase     where the run is       queued | paused | starting | working | needs_you | stopping | reconnecting | ended
    outcome   what came of it        completed | partial | blocked | failed | cancelled, with verification verified | unverified | not_applicable

`detail(..., after=N)` is the cursor read: the view (small) plus only the timeline rows touched by events after sequence N. A client that reconnects with
its last cursor gets exactly what it missed; `after=0` is the whole record.
"""
from __future__ import annotations
import calendar
import hashlib
import json
import re
import time

from . import request_states
from .browse import job_states
from .security import NotFound, Principal

NOISE = re.compile(r'transcript update|^runtime accepted|^dispatched to', re.I)
MAX_ROWS = 400                       # timeline rows kept per task view (the newest); a task is capped at 2000 events anyway
TITLE_CHARS = 160

# What the customer reads while a tool is running. Fixed words per category; the detail (a query, a host, a path) is shown beside it, never inside it.
DOING = {'search': 'Searching the web', 'read': 'Reading a page', 'browse': 'Using the browser', 'command': 'Running a command',
         'file': 'Working with a file', 'subagent': 'Working with a helper', 'other': 'Using a tool'}
NEEDS = {
    'approval': 'Waiting for your permission',
    'browser_question': 'Waiting for your answer',
    'browser_control': 'You have the browser',
    'browser_handoff': 'Waiting for you in the browser',
    'location_permission': 'Waiting for location permission',
    'goal': 'Goal on hold',
    'paused': 'Paused',
}
BROWSER_NEEDS = {'asking': 'browser_question', 'paused': 'browser_control', 'handoff': 'browser_handoff'}
STEP_STATUSES = ('pending', 'running', 'done', 'blocked', 'failed', 'skipped')


def phase_of(row, *, waiting_on=None) -> str:
    """The run's phase from the request row (and whether something is waiting on the customer)."""
    state = row['state']
    if state in request_states.FINAL:
        return 'ended'
    if row['cancel_requested']:
        return 'stopping'
    if state == request_states.WAITING:
        return 'paused' if row['paused'] else 'queued'
    if state == request_states.STARTING:
        return 'starting'
    if state == request_states.UNCERTAIN:
        return 'reconnecting'
    return 'needs_you' if waiting_on else 'working'


def outcome_of(row):
    """-> (outcome, verification, note) for a finished request; (None, None, '') while it is not finished. A goal whose next turn is already admitted is not an ending."""
    if row['state'] not in request_states.FINAL:
        return None, None, ''
    outcome = row['outcome'] or row['state']
    verification = row['verification'] or ('not_applicable' if outcome in ('cancelled',) else 'unverified' if outcome == 'failed' else 'not_applicable')
    note = row['outcome_note'] or ''
    if outcome == 'failed' and not note:
        note = (row['result'] or '')[:300]
    return outcome, verification, note


def label_of(phase, row, *, activity=None, waiting_on=None, ahead=None) -> str:
    """The one line of status, from a fixed vocabulary."""
    if phase == 'queued':
        return 'Next in line' if ahead == 0 else 'Queued'
    if phase == 'paused':
        return 'Paused'
    if phase == 'starting':
        return 'Getting ready'
    if phase == 'reconnecting':
        return 'Reconnecting'
    if phase == 'stopping':
        return 'Stopping'
    if phase == 'needs_you':
        return NEEDS.get(waiting_on, 'Waiting for you')
    if phase == 'working':
        return activity['label'] if activity else 'Thinking'
    outcome, verification, _ = outcome_of(row)
    if outcome == 'completed':
        return 'Done · confirmed' if verification == 'verified' else 'Done · not confirmed' if verification == 'unverified' else 'Done'
    if outcome == 'partial':
        return 'Continuing towards your goal' if row['continue_goal'] else 'Partly done'
    return {'blocked': 'Blocked', 'failed': 'Failed', 'cancelled': 'Stopped'}.get(outcome, 'Ended')


def tone_of(phase, row) -> str:
    """How the status should be coloured: a task that ended partly or blocked is never shown as plain success, and never as a crash."""
    if phase in ('queued', 'starting', 'reconnecting', 'stopping'):
        return 'pending'
    if phase in ('paused', 'needs_you'):
        return 'attention'
    if phase == 'working':
        return 'live'
    outcome, verification, _ = outcome_of(row)
    if outcome == 'completed':
        return 'ok' if verification != 'unverified' else 'unsure'
    if outcome == 'partial':
        return 'live' if row['continue_goal'] else 'attention'
    return {'blocked': 'bad', 'failed': 'bad', 'cancelled': 'muted'}.get(outcome, 'muted')


def controls_of(row) -> dict:
    """What the customer can do to the task now. A run in progress cannot be paused (the assistant has no safe place to stop mid-run): it can be stopped or steered."""
    state = row['state']
    active = state in request_states.ACTIVE
    held = state == 'completed' and bool(row['goal_mode']) and not row['continue_goal'] and row['outcome'] in ('partial', 'blocked')
    return {'stop': active and not row['cancel_requested'], 'pause': state == 'waiting' and not row['paused'], 'resume': state == 'waiting' and bool(row['paused']),
            'retry': state in ('failed', 'cancelled'), 'goal_resume': held, 'goal_clear': held,
            'steer': state in request_states.LIVE and not row['cancel_requested'] and not row['closing']}


def _ms(created_at) -> int:
    """'2026-11-13T19:12:53.592Z' -> epoch milliseconds (0 when unreadable)."""
    try:
        head, _, frac = str(created_at).rstrip('Z').partition('.')
        return calendar.timegm(time.strptime(head, '%Y-%m-%dT%H:%M:%S')) * 1000 + int((frac + '000')[:3])
    except (ValueError, OverflowError):
        return 0


def _text(value, limit) -> str:
    return value[:limit] if isinstance(value, str) else ''


def timeline(events) -> list[dict]:
    """Public events (oldest first: {'sequence','kind','payload','created_at'}) -> one row per thing that happened.

    A tool call is ONE row: its 'running' event opens it and the matching 'done'/'failed' event closes it, wherever that lands among other calls, so calls that
    overlap in time are each shown truthfully (`group` names the set that ran together). `seq` is the newest event that touched the row: the cursor read
    returns a row again when it changes."""
    rows, by_ref, open_refs, group_of = [], {}, [], {}
    for e in events:
        p, seq, at = e.get('payload') or {}, e['sequence'], _ms(e.get('created_at'))
        kind = e['kind']
        if kind == 'activity':
            ref = _text(p.get('ref'), 128)
            if not ref:
                continue
            status = p.get('status') if p.get('status') in ('done', 'failed') else 'running'
            category = _text(p.get('category'), 20) or 'other'
            at_index = by_ref.get(ref)
            if at_index is None:
                row = {'key': ref, 'kind': 'tool', 'category': category, 'label': _text(p.get('label'), 80) or 'Used a tool', 'detail': _text(p.get('detail'), 400),
                       'output': _text(p.get('output'), 1500), 'status': status, 'at': at, 'ended_at': at if status != 'running' else None, 'first': seq, 'seq': seq, 'group': None}
                by_ref[ref] = len(rows)
                rows.append(row)
                if open_refs:                                    # it started while another call was still running: they ran together
                    lead = group_of.get(open_refs[0]) or open_refs[0]
                    for other in open_refs + [ref]:
                        group_of[other] = lead
                        rows[by_ref[other]]['group'] = lead
                if status == 'running':
                    open_refs.append(ref)
            else:
                row = rows[at_index]
                row.update(status=status, seq=seq, output=_text(p.get('output'), 1500) or row['output'], detail=_text(p.get('detail'), 400) or row['detail'])
                if status != 'running':
                    row['ended_at'] = at
                    if ref in open_refs:
                        open_refs.remove(ref)
        elif kind in ('progress', 'error'):
            text = _text(p.get('summary'), 300)
            if not text or NOISE.search(text):
                continue
            rows.append({'key': f'n{seq}', 'kind': 'error' if kind == 'error' else 'note', 'category': 'error' if kind == 'error' else 'note', 'label': text, 'detail': '', 'output': '',
                         'status': 'failed' if kind == 'error' else 'note', 'at': at, 'ended_at': at, 'first': seq, 'seq': seq, 'group': None})
        elif kind in ('approval_request', 'approval_decision'):
            call = _text(p.get('request_id'), 64)
            if not call:
                continue
            key = 'approval-' + call
            at_index = by_ref.get(key)
            decision = p.get('decision') if kind == 'approval_decision' and p.get('decision') in ('approved', 'declined', 'expired') else None
            if at_index is None:
                by_ref[key] = len(rows)
                rows.append({'key': key, 'kind': 'approval', 'category': 'approval', 'label': _text(p.get('summary'), 200) or 'Asked for your permission', 'detail': '', 'output': '',
                             'status': decision or 'waiting', 'at': at, 'ended_at': at if decision else None, 'first': seq, 'seq': seq, 'group': None})
            elif decision:
                rows[at_index].update(status=decision, ended_at=at, seq=seq)
        elif kind == 'artifact':
            name = _text(p.get('name'), 200)
            if name:
                rows.append({'key': f'f{seq}', 'kind': 'file', 'category': 'file', 'label': 'Saved a file', 'detail': name, 'output': '', 'status': 'done', 'at': at, 'ended_at': at,
                             'first': seq, 'seq': seq, 'group': None})
        elif kind == 'artifact_skipped':
            name = _text(p.get('name'), 200)
            if name:
                rows.append({'key': f'f{seq}', 'kind': 'file', 'category': 'file', 'label': 'Could not save a file', 'detail': f"{name}: {_text(p.get('reason'), 80)}", 'output': '',
                             'status': 'failed', 'at': at, 'ended_at': at, 'first': seq, 'seq': seq, 'group': None})
    return rows


def checklist(events, row):
    """The assistant's own checklist (its lumina_task_update reports), newest snapshot. Display only, and always labelled as the assistant's report.
    When the request is over, a step it left 'running' or 'pending' is not shown as still going: it failed, was stopped, or its completion was simply never reported."""
    latest = None
    for e in events:
        p = e.get('payload') or {}
        if e['kind'] != 'task_steps' or p.get('mode') not in ('direct', 'plan') or not isinstance(p.get('steps'), list) or not 0 < len(p['steps']) <= 24:
            continue
        if all(isinstance(s, dict) and isinstance(s.get('id'), str) and isinstance(s.get('title'), str) and s.get('status') in STEP_STATUSES for s in p['steps']):
            latest = p
    if latest is None:
        return None
    left = {'failed': 'failed', 'cancelled': 'stopped'}.get(row['state'], 'unreported')
    over = row['state'] in request_states.FINAL
    steps = [{'id': s['id'], 'title': s['title'][:100], 'status': left if over and s['status'] in ('running', 'pending') else s['status'],
              **({'checkpoint': s['checkpoint'][:240]} if isinstance(s.get('checkpoint'), str) else {}), **({'result': s['result'][:240]} if isinstance(s.get('result'), str) else {})}
             for s in latest['steps']]
    return {'mode': latest['mode'], 'steps': steps}


def _host(detail) -> str:
    host = str(detail or '').split('/', 1)[0].strip().lower()
    return host if re.fullmatch(r'[a-z0-9.-]{1,120}\.[a-z]{2,24}', host) else ''


def evidence(rows, artifacts, row, last_ms) -> dict:
    """What Lumina can show for the work: counts and names taken from its own records (never from the assistant's description of what it did)."""
    tools = [r for r in rows if r['kind'] == 'tool']
    sites = []
    for r in tools:
        host = _host(r['detail']) if r['category'] in ('read', 'browse') else ''
        if host and host not in sites:
            sites.append(host)
    files = []
    for r in tools:
        if r['category'] == 'file' and r['detail'] and r['label'].split(' ', 1)[0] in ('Wrote', 'Edited') and r['detail'] not in files:
            files.append(r['detail'])
    ended = row['state'] in request_states.FINAL
    return {'steps': len(tools), 'failed_steps': sum(1 for r in tools if r['status'] == 'failed'),
            'searches': sum(1 for r in tools if r['category'] == 'search'), 'commands': sum(1 for r in tools if r['category'] == 'command'),
            'sites': sites[:12], 'files': files[:12], 'saved': [{'id': a['id'], 'version': a['version'], 'name': a['display_name'], 'size': a['size_bytes']} for a in artifacts][:12],
            'approvals': [{'label': r['label'], 'decision': r['status']} for r in rows if r['kind'] == 'approval'][:12],
            'duration_s': max(0, round(last_ms / 1000) - int(row['created_epoch'])) if ended and last_ms else None}


def _approval(call, connections) -> dict:
    try:
        arguments = json.loads(call['arguments_json'])
    except (ValueError, TypeError):
        arguments = {}
    return {'kind': 'approval', 'id': call['id'], 'tool': call['tool_name'][:80], 'service': connections.get(call['connection_id'], ''), 'arguments': arguments if isinstance(arguments, dict) else {},
            'expires_epoch': call['expires_epoch']}


class WorkReader:
    """Account-scoped reads. Every method authorises the principal first, exactly like the routes it replaces."""

    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    # -- pieces ---------------------------------------------------------------------------------------------------------------------------------
    def _events(self, con, account, task, after=0):
        out = []
        for r in con.execute('SELECT sequence,kind,public_payload,created_at FROM events WHERE account_id=? AND task_id=? AND sequence>? ORDER BY sequence', (account, task, after)):
            payload = json.loads(r['public_payload'])
            payload.pop('source', None)
            out.append({'sequence': r['sequence'], 'kind': r['kind'], 'payload': payload, 'created_at': r['created_at']})
        return out

    def _waiting(self, con, account, now):
        """{request_id: [what is waiting on the customer]} for the account's unfinished requests: permission prompts, the browser, location."""
        waiting = {}
        connections = {r['id']: r['name'] for r in con.execute('SELECT id,name FROM mcp_connections WHERE account_id=?', (account,))} if self._has(con, 'mcp_connections') else {}
        if self._has(con, 'mcp_calls'):
            for call in con.execute("SELECT id,connection_id,tool_name,arguments_json,request_id,expires_epoch FROM mcp_calls WHERE account_id=? AND state='pending' AND expires_epoch>? ORDER BY created_epoch",
                                    (account, int(now))):
                waiting.setdefault(call['request_id'], []).append(_approval(call, connections))
        for run in con.execute(f"""SELECT b.request_id,b.status,b.pending_json FROM browse_runs b JOIN customer_requests r ON r.account_id=b.account_id AND r.id=b.request_id
                WHERE b.account_id=? AND b.status IN {job_states.sql_list(job_states.WAITING)} AND r.state IN {request_states.sql_list(request_states.ACTIVE)}""", (account,)):
            try:
                pending = json.loads(run['pending_json']) if run['pending_json'] else None
            except ValueError:
                pending = None
            waiting.setdefault(run['request_id'], []).append({'kind': BROWSER_NEEDS[run['status']], 'before': str((pending or {}).get('label') or '')[:200]})
        return waiting

    @staticmethod
    def _has(con, table):
        return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())

    @staticmethod
    def _follows(row):
        """The task this one carries on (a turn Lumina started after the customer answered a permission prompt), or None."""
        try:
            follows = json.loads(row['context_json'] or '{}').get('follows')
        except (ValueError, AttributeError):
            return None
        return follows if isinstance(follows, str) and re.fullmatch(r'[a-f0-9]{32}', follows) else None

    def _title(self, con, row):
        """What the customer asked for. A turn Lumina started itself is named after the task it continues, not after Lumina's own words to the assistant."""
        seen = 0
        while seen < 5:
            follows = self._follows(row)
            if not follows:
                break
            parent = con.execute('SELECT message,context_json FROM customer_requests WHERE account_id=? AND id=?', (row['account_id'], follows)).fetchone()
            if not parent:
                break
            row, seen = parent, seen + 1
        return (row['message'] or '')[:TITLE_CHARS]

    @staticmethod
    def _ahead(con, row):
        if row['state'] != 'waiting' or row['paused']:
            return None
        busy = con.execute('SELECT count(*) FROM request_slot').fetchone()[0]
        return busy + con.execute("SELECT count(*) FROM customer_requests WHERE state='waiting' AND paused=0 AND sequence<?", (row['sequence'],)).fetchone()[0]

    @staticmethod
    def _step_counts(con, account):
        """{task_id: how many tool calls it made}, for the list (so a line can say "6 steps" without loading every timeline)."""
        return {r[0]: r[1] for r in con.execute("""SELECT task_id,count(DISTINCT json_extract(public_payload,'$.ref')) FROM events
            WHERE account_id=? AND kind='activity' GROUP BY task_id""", (account,))}

    def _summary(self, con, row, waiting, *, rows=None, steps=None):
        """The small view every list shows. `rows` (the timeline) is only read for a run in progress, to say what it is doing right now."""
        needs = list(waiting.get(row['id'], []))
        if row['state'] == 'running' and row['parked_reason'] == 'location_permission':
            needs.append({'kind': 'location_permission'})
        waiting_on = needs[0]['kind'] if needs else ('browser_handoff' if row['state'] == 'running' and row['parked_reason'] else None)
        phase = phase_of(row, waiting_on=waiting_on)
        running = [r for r in rows or [] if r['kind'] == 'tool' and r['status'] == 'running'] if phase == 'working' else []
        now = [{'key': r['key'], 'category': r['category'], 'label': DOING.get(r['category'], DOING['other']), 'detail': r['detail']} for r in running]
        activity = now[-1] if now else None
        ahead = self._ahead(con, row)
        outcome, verification, note = outcome_of(row)
        controls = controls_of(row)
        attention = None
        if phase == 'needs_you':
            attention = waiting_on
        elif phase == 'paused':
            attention = 'paused'
        elif any(n['kind'] == 'approval' for n in needs):          # the run ended on "I need your permission": the prompt is still the customer's to answer
            attention = 'approval'
        elif controls['goal_resume']:
            attention = 'goal'
        label, tone = label_of(phase, row, activity=activity, waiting_on=waiting_on, ahead=ahead), tone_of(phase, row)
        if phase == 'ended' and attention == 'approval':           # the run is over but its question is not: say what is open, not "Done"
            label, tone = NEEDS['approval'], 'attention'
        return {'id': row['id'], 'conversation_id': row['conversation_id'], 'title': self._title(con, row), 'follows': self._follows(row), 'created_epoch': row['created_epoch'],
                'state': row['state'], 'phase': phase, 'label': label, 'tone': tone,
                'activity': activity, 'now': now, 'ahead': ahead, 'attention': attention, 'attention_label': NEEDS.get(attention, '') if attention else '',
                'outcome': outcome, 'verification': verification, 'note': note, 'goal': bool(row['goal_mode']), 'continuing': bool(row['continue_goal']), 'retry_of': row['retry_of'],
                'controls': controls, 'needs': needs, 'steps': steps if steps is not None else sum(1 for r in rows or [] if r['kind'] == 'tool')}

    # -- reads ----------------------------------------------------------------------------------------------------------------------------------
    def listing(self, principal: Principal) -> dict:
        """Every recent task of the account, newest first, with what needs the customer on top of the answer. `rev` changes exactly when anything shown changes."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            account = principal.account_id
            waiting = self._waiting(con, account, self.clock())
            tasks, counts = [], self._step_counts(con, account)
            for row in con.execute('SELECT * FROM customer_requests WHERE account_id=? ORDER BY sequence DESC LIMIT 100', (account,)).fetchall():
                rows = timeline(self._events(con, account, row['id'])) if row['state'] == 'running' and not row['cancel_requested'] else None
                tasks.append(self._summary(con, row, waiting, rows=rows, steps=counts.get(row['id'], 0)))
        out = {'tasks': tasks, 'attention': sum(1 for t in tasks if t['attention'])}
        out['rev'] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:16]
        return out

    def detail(self, principal: Principal, task_id: str, *, after: int = 0) -> dict:
        """One task in full: the view, and the timeline rows touched since `after` (0 = all of them)."""
        if type(after) is not int or after < 0:
            raise ValueError('invalid cursor')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            account = principal.account_id
            row = con.execute('SELECT * FROM customer_requests WHERE account_id=? AND id=?', (account, task_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            events = self._events(con, account, task_id)
            waiting = self._waiting(con, account, self.clock())
            artifacts = con.execute('SELECT id,version,display_name,size_bytes FROM artifacts WHERE account_id=? AND task_id=? ORDER BY created_at', (account, task_id)).fetchall()
            browser = con.execute('SELECT status,url FROM browse_runs WHERE account_id=? AND request_id=?', (account, task_id)).fetchone()
            messages = con.execute("SELECT count(*) FROM chat_messages WHERE account_id=? AND request_id=?", (account, task_id)).fetchone()[0]
            rows = timeline(events)
            asking = {n['id'] for n in waiting.get(task_id, []) if n['kind'] == 'approval'}
            for r in rows:                                       # a prompt nobody answered in time is not still "waiting"
                if r['kind'] == 'approval' and r['status'] == 'waiting' and r['key'].removeprefix('approval-') not in asking:
                    r['status'] = 'expired'
            view = self._summary(con, row, waiting, rows=rows)
        cursor = events[-1]['sequence'] if events else 0
        last_ms = _ms(events[-1]['created_at']) if events else 0
        view.update(request=view['title'] if view['follows'] else (row['message'] or ''), result=row['result'] if row['state'] == 'failed' else None, checklist=checklist(events, row),
                    evidence=evidence(rows, artifacts, row, last_ms), messages=messages, cancel_requested=bool(row['cancel_requested']),
                    browser={'status': browser['status'], 'live': browser['status'] in job_states.LIVE and row['state'] in request_states.ACTIVE,
                             'host': _host(re.sub(r'^https?://', '', browser['url'] or ''))} if browser else None,
                    ended_epoch=round(last_ms / 1000) if row['state'] in request_states.FINAL and last_ms else None)
        view['rev'] = hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest()[:16]
        kept = rows[-MAX_ROWS:]
        return {'task': view, 'rows': [r for r in kept if r['seq'] > after], 'cursor': cursor, 'trimmed': len(rows) - len(kept)}
