"""The host-side sequence that serves one customer request with a native OpenClaw run.

OpenClaw owns the execution: model calls, tool calls, tool results, steering, goals. This driver is the admission and settlement around it, in this order:

1. repeat the account/reservation checks after the claim, make sure no other run owns the session, and hand the message over (``chat.send``; the idempotency key is the
   run id, so a resend after a crash can never start a second run);
2. ask the runtime when the run ended (``agent.wait``) in short slices; between slices look after Stop, the lease, the spending limit, the per-run time limit and
   people the run is waiting for;
3. when no run is owed any more, close the request: mirror the replies of its runs, save files and cards, judge the outcome (outcome.py), settle the spend.

Nothing here reads the assistant's prose for commands. Browser work reaches the runtime as a native tool (tool_relay.py); a person it needs is noticed from the
browser job's own state and parks the request (it gives up the running slot, not its cell or reservation).
"""
from __future__ import annotations
import hashlib
import json
import os
import time
import uuid
from . import activity as activity_mod, outcome as outcome_mod
from .adapters import CapabilityUnavailable
from .browse.untrusted import neutralize
from .budget import BudgetLedger
from .events import EventService
from .gateway import SyntheticGateway
from .genui import document as gen_document, prompts as gen_prompts
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .request_queue import Defer, Parked, Recover, RequestClaim, RequestQueue, RequestReceipt
from .security import Principal

MAX_TRANSCRIPT_CHARS = 16000
WAIT_SLICE_MS = 3000          # one agent.wait; Stop, the lease and the limits are looked after between slices
RUN_TIMEOUT = 900             # seconds one run may take (not counting time spent waiting for a person)
PARK_LIMIT = 1800             # seconds a request may wait parked before its run is stopped
OUTAGE_LIMIT = 90             # seconds the cell may be unreachable (restart, reconnect) before supervision gives up and leaves the request to be recovered
LOST_AFTER = 20               # seconds an input may stay unfinished before it is presented to the runtime again (then 40, 80, at most 120)
GOAL_CHAIN_LIMIT = 20         # turns of one "keep working until complete" goal; the customer can resume after
HUMAN_WAIT = {'asking': 'browser_question', 'paused': 'browser_takeover'}       # browse job states that mean a person has the wheel
LIVE_STATES = ('pending', 'acknowledged', 'uncertain')
KINDS_THAT_START_RUNS = ('turn', 'goal_start', 'goal_resume', 'goal_continue')
GOAL_OPEN = ('paused', 'blocked', 'budget_limited', 'usage_limited')
CONTINUE_TEXT = 'Continue pursuing the current goal.'
RETRY_NOTE = ('This is a retry of an earlier attempt that did not finish. Look at this conversation first, see what was already done (files written, pages visited, '
              'items added) and do not repeat an action that already happened; carry on from there.')
MEDIA = {'.txt': 'text/plain', '.md': 'text/markdown', '.csv': 'text/csv', '.json': 'application/json', '.py': 'text/x-python',
         '.js': 'text/javascript', '.ts': 'text/plain', '.tsx': 'text/plain', '.jsx': 'text/plain', '.html': 'text/html', '.css': 'text/css',
         '.sql': 'text/plain', '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


class ChatDriver:
    """Reference trusted-host execution sequence for chat requests.

    Follows the worker boundary: repeat account authorization after the claim, require the active reservation before any native effect, record every delivery,
    and reconcile by run id. Cancellation aborts the scoped run(s) and is confirmed by the runtime before it is reported; abort stops generation without undoing effects.
    """

    def __init__(self, store, *, ledger: BudgetLedger, gateway_factory, clock=time.time, events: EventService | None = None, sleep=None, pause=0.25, wait_ms=WAIT_SLICE_MS,
                 run_timeout=RUN_TIMEOUT, usage_wait=45, spend_check_seconds=20, park_limit=PARK_LIMIT, goal_chain_limit=GOAL_CHAIN_LIMIT, outage_limit=OUTAGE_LIMIT, heartbeat=None, genui=None,
                 artifacts=None, display=None, browse_factory=None, queue=None):
        self.browse_factory = browse_factory   # callable(account_id) -> BrowseRpc: only to stop browser jobs when their request ends; the jobs run inside the runtime's tool call
        self.display = display                 # routing.display.DisplayDecider: JEV may choose a layout for a plain-text reply (owner switch jev_display); None = never asked
        self.genui = genui                     # GenUiRuntime: plan/execute prompts and plan-reply handling
        self.heartbeat = heartbeat             # callable(claim): keeps the queue lease alive during long runs
        self.sleep = sleep if sleep is not None else (lambda seconds: None)
        self.pause, self.wait_ms, self.run_timeout, self.usage_wait = pause, wait_ms, run_timeout, usage_wait
        self.spend_check_seconds, self.park_limit, self.goal_chain_limit, self.outage_limit = spend_check_seconds, park_limit, goal_chain_limit, outage_limit
        self.store = store
        self.ledger = ledger
        self.gateway_factory = gateway_factory
        self.events = events
        self.artifacts = artifacts
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)
        self.queue = queue or RequestQueue(store, clock=clock)

    # -- small helpers -------------------------------------------------------------------------------------------------------------------------
    def _emit(self, claim, kind: str, payload: dict | None = None, source: str = 'worker'):
        # Timeline appends are best-effort: a failed event write degrades the timeline view, never the task or its budget state.
        if self.events is None:
            return
        try:
            self.events.append(claim.account_id, claim.request_id, kind, payload, source)
        except Exception:
            pass

    def preflight(self):
        caps = self.gateway_factory(None).capabilities()
        for operation in ('send', 'history', 'wait'):
            if not getattr(caps, operation):
                raise CapabilityUnavailable('gateway probe did not verify ' + operation)

    def _require(self, gateway):
        caps = gateway.capabilities()
        for operation in ('send', 'history', 'wait'):
            if not getattr(caps, operation):
                raise CapabilityUnavailable('gateway probe did not verify ' + operation)
        return caps

    def _deliveries(self, claim, *, states=None):
        with self.store.connect() as con:
            rows = [dict(r) for r in con.execute('SELECT * FROM chat_deliveries WHERE account_id=? AND request_id=? ORDER BY attempt', (claim.account_id, claim.request_id)).fetchall()]
        return [r for r in rows if states is None or r['state'] in states]

    def _cancel_requested(self, claim):
        with self.coordinator.transaction() as con:
            return bool(con.execute('SELECT cancel_requested FROM customer_requests WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()[0])

    def _set_delivery(self, claim, attempt, state, **fields):
        columns = {'run_id': 'native_run_id', 'ack_seq': 'ack_message_seq', 'deadline': 'deadline_epoch', 'ended': 'ended_epoch', 'status': 'native_status', 'tools': 'tools_json'}
        sets, values = ['state=?', 'updated_epoch=?'], [state, int(self.clock())]
        for name, value in fields.items():
            if value is not None:
                sets.append(columns[name] + '=?')
                values.append(value)
        with self.coordinator.transaction() as con:
            con.execute(f'UPDATE chat_deliveries SET {",".join(sets)} WHERE account_id=? AND request_id=? AND attempt=?', (*values, claim.account_id, claim.request_id, attempt))

    # -- admission after the claim -------------------------------------------------------------------------------------------------------------
    def _admit(self, claim):
        with self.coordinator.transaction() as con:
            self.store._authorize(con, Principal(claim.account_id, claim.actor_id, 'customer'))
            reservation = con.execute('SELECT state FROM task_reservations WHERE account_id=? AND task_id=?', (claim.account_id, claim.request_id)).fetchone()
            if not reservation or reservation['state'] != 'active':
                raise Conflict('task not admitted')
            task = con.execute('SELECT state FROM tasks WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()
            if not task or task[0] not in ('queued', 'running'):
                raise Conflict('task not dispatchable')
            conversation = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?', (claim.account_id, claim.conversation_id)).fetchone()
            if conversation is None:
                raise Conflict('claim conversation missing')
            row = con.execute('SELECT cancel_requested,intent,context_json,goal_mode,retry_of FROM customer_requests WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()
            return {'session': conversation[0], 'cancelled': bool(row['cancel_requested']), 'intent': row['intent'] or 'chat', 'context': json.loads(row['context_json'] or '{}'),
                    'goal_mode': bool(row['goal_mode']), 'retry_of': row['retry_of']}

    def _mark_running(self, claim):
        with self.coordinator.transaction() as con:
            con.execute("UPDATE tasks SET state='running' WHERE account_id=? AND id=? AND state IN ('queued','running')", (claim.account_id, claim.request_id))

    # -- entry points --------------------------------------------------------------------------------------------------------------------------
    def execute(self, claim: RequestClaim):
        """Start (or, after a park or a crash, carry on supervising) the runs of this request. -> RequestReceipt | Parked | Defer."""
        if claim.conversation_id is None:
            raise ValueError('chat driver requires a conversation binding')
        gateway = self.gateway_factory(claim)
        self._require(gateway)
        info = self._admit(claim)
        if not self._deliveries(claim):
            if info['cancelled']:
                return self._close(claim, 'cancelled', 'Cancelled before execution', verdict=outcome_mod.judge(native={}, cancelled=True))      # nothing was sent, nothing to settle
            started = self._begin(claim, gateway, info)
            if started is not None:
                return started
            info = {**info, 'session': self._session(claim)}
        else:
            self._reassert(claim, gateway, info['session'] or self._session(claim))       # a carried-on request (parked, recovered): make sure the runtime still has its inputs
        return self._supervise(claim, gateway, info)

    def _session(self, claim):
        with self.store.connect() as con:
            row = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?', (claim.account_id, claim.conversation_id)).fetchone()
        return row[0] if row else None

    # -- 1. hand the message over --------------------------------------------------------------------------------------------------------------
    def _begin(self, claim, gateway, info):
        session = info['session']
        if session is None:
            session, _started, _error = gateway.open_session(uuid.uuid4().hex, 'chat-' + claim.request_id[:16])
            with self.coordinator.transaction() as con:
                con.execute('UPDATE conversations SET native_session_ref=? WHERE account_id=? AND id=?', (session, claim.account_id, claim.conversation_id))
        elif not self._quiesced(claim, gateway, session):
            return Defer('the session still has a run that something else owns')
        self._mark_running(claim)
        self._emit(claim, 'task_started', {'summary': 'Your assistant is ready. Reading your message.'})
        kind, payload, goal_ms = self._plan_first_delivery(claim, gateway, session, info)
        with self.coordinator.transaction() as con:
            attempt = con.execute('SELECT coalesce(max(attempt),0)+1 FROM chat_deliveries WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchone()[0]
            key = f'{claim.request_id}-a{attempt}'
            now = int(self.clock())
            con.execute('''INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,created_epoch,updated_epoch,kind,goal_issued_ms,payload)
                VALUES (?,?,?,?,?,'pending',?,?,?,?,?,?)''', (claim.account_id, claim.request_id, attempt, key, hashlib.sha256(payload.encode()).hexdigest(), key, now, now, kind, goal_ms, payload))
        before = self._usage_before(gateway)
        if before is not None:
            with self.coordinator.transaction() as con:
                con.execute('UPDATE chat_deliveries SET usage_before_microusd=? WHERE account_id=? AND request_id=? AND attempt=?', (before, claim.account_id, claim.request_id, attempt))
        return None

    def _quiesced(self, claim, gateway, session):
        """Execution ownership comes before new work: no run may be going on in this session unless a live request of this account owns it. A run nobody owns (the runtime resumed an
        interrupted turn by itself, or its request is over) is stopped here; one a live request owns means this request must wait its turn."""
        page = gateway.history(session)
        if not page['active_run']:
            return True
        with self.store.connect() as con:
            owners = con.execute('''SELECT d.native_run_id FROM chat_deliveries d JOIN customer_requests r ON r.account_id=d.account_id AND r.id=d.request_id
                WHERE d.account_id=? AND d.request_id<>? AND r.conversation_id=? AND r.state IN ('starting','running','uncertain') AND d.state IN ('acknowledged','uncertain','pending')''',
                                (claim.account_id, claim.request_id, claim.conversation_id)).fetchall()
        if owners:
            return False
        gateway.abort(session)                 # nothing owns the run: it must not keep running beside the new work
        for _ in range(20):
            if not gateway.history(session)['active_run']:
                return True
            self.sleep(self.pause)
        return False

    def _plan_first_delivery(self, claim, gateway, session, info):
        """-> (kind, the text handed to the runtime, goal start time or None). The text is the customer's message (or the plan/phase prompt) with a short Lumina context block;
        no tool protocol: the runtime offers its own tools, including the browser."""
        intent, context = info['intent'], info['context']
        if intent in ('goal_resume', 'goal_continue'):
            return ('goal_resume' if intent == 'goal_resume' else 'goal_continue'), CONTINUE_TEXT, None
        if info['goal_mode']:
            goal = gateway.session_goal(session) if gateway.capabilities().goals else None
            if goal is not None and info['retry_of'] is None and intent in ('chat', 'browse'):
                gateway.goal_clear(session, goal['id'], 'replace-' + claim.request_id[:20])      # the customer asked for a new objective
                goal = None
            if goal is None:
                return 'goal_start', self._outgoing(claim, info, notes=False), int(self.clock() * 1000)       # the message IS the goal's objective: no context block in it
            return ('goal_resume' if goal['status'] in GOAL_OPEN else 'goal_continue'), CONTINUE_TEXT, None
        return 'turn', self._outgoing(claim, info), None

    def _outgoing(self, claim, info, notes=True):
        intent, context = info['intent'], info['context']
        text = self.genui.outgoing(claim, intent, context) if self.genui else claim.message
        if notes:
            text = gen_prompts.progress_prompt(claim.request_id) + ('\nThis request only drafts a plan. Do not execute its phases; the customer launches the editable plan separately.\n' if intent == 'plan' else '\n') + text
        if intent not in ('chat', 'browse') or not notes:
            return text                                    # plan, execute and phase prompts are complete as they are
        notes = []
        if intent == 'browse':
            notes.append('The customer chose Browse mode. Use the Lumina browser tool (find it with tool_search: "lumina browser") for what they ask, then tell them what it found.')
        if context.get('mode') == 'text':
            notes.append('The customer chose Text mode: answer in plain text and do not use the browser.')
        if context.get('mode') != 'text' and context.get('ui') in ('medium', 'interactive'):
            notes.append(gen_document.tier_section(context['ui']).rstrip())         # composed-answer instructions for this message only; basic and Text mode send nothing
        if info['retry_of']:
            notes.append(RETRY_NOTE)
        known = self._known_about(claim.account_id)
        if known:
            notes.append('What the customer asked Lumina to remember:\n' + '\n'.join('- ' + k for k in known[:30]))
        if not notes:
            return text
        return '[Lumina context for the assistant only. The customer does not see this.]\n' + '\n'.join(notes) + '\n\nCustomer message:\n' + text

    def _known_about(self, account_id):
        """Short lines about what the customer asked Lumina to remember. Names only: a saved login or card is never described beyond its label."""
        lines = []
        try:
            from . import saved
            with self.store.connect() as con:
                lines = [neutralize(f'{k}: {v}', 120) for k, v in saved.choices(con, account_id).items()]
        except Exception:
            pass
        try:
            from . import vault
            with self.store.connect() as con:
                for item in vault.list_items(con, account_id):
                    lines.append(neutralize(('A saved login for ' + item['site']) if item['kind'] == 'login' else 'A saved card: ' + item['label'], 120) + ' (Lumina asks before using it)')
        except Exception:
            pass                                   # no vault on this host, or it cannot be read: the choices above still go
        return lines

    def _present(self, claim, gateway, session, delivery):
        """_deliver, and if the runtime refuses to take the input again because a restart left it `interrupted`, present the same text under a fresh key (the interrupted entry stays
        inert, so the input runs once). The delivery then carries the new key; the old one is kept as its operation id."""
        try:
            return self._deliver(claim, gateway, session, delivery)
        except CapabilityUnavailable:
            if delivery['kind'] not in ('turn', 'steer', 'goal_start', 'goal_continue') or not delivery['native_run_id'] and delivery['state'] == 'pending':
                raise
            try:
                waiting = {p['run_id']: p['state'] for p in gateway.history(session).get('pending') or []}
            except CapabilityUnavailable:
                raise
            if waiting.get(delivery['idempotency_key']) != 'interrupted':
                raise
            fresh = f"{delivery['idempotency_key'].split('.r')[0]}.r{int(self.clock())}"
            kind, payload, goal_ms = delivery['kind'], delivery['payload'], delivery['goal_issued_ms']
            if kind == 'goal_start':
                kind, payload, goal_ms = 'goal_continue', CONTINUE_TEXT, None             # the goal was saved with the interrupted input: continue it, do not start it again
            with self.coordinator.transaction() as con:
                con.execute('''UPDATE chat_deliveries SET idempotency_key=?,native_run_id=NULL,kind=?,payload=?,goal_issued_ms=?,updated_epoch=? WHERE account_id=? AND request_id=? AND attempt=?''',
                            (fresh, kind, payload, goal_ms, int(self.clock()), claim.account_id, claim.request_id, delivery['attempt']))
            self._emit(claim, 'progress', {'summary': 'Your assistant restarted; your message was handed over again.', 'step': 'working'}, 'gateway')
            return self._deliver(claim, gateway, session, {**delivery, 'idempotency_key': fresh, 'native_run_id': None, 'kind': kind, 'payload': payload, 'goal_issued_ms': goal_ms})

    def _deliver(self, claim, gateway, session, delivery):
        """Hand one delivery to the runtime. Safe to repeat: the key is the run id, so a resend after a crash never starts a second run."""
        try:
            if delivery['kind'] == 'goal_resume':
                goal = gateway.session_goal(session)
                if goal is None:
                    ack = gateway.send(session, delivery['idempotency_key'], delivery['payload'] or CONTINUE_TEXT)
                elif goal['status'] == 'active':
                    ack = gateway.send(session, delivery['idempotency_key'], delivery['payload'] or CONTINUE_TEXT)
                else:
                    done = gateway.goal_update(session, goal['id'], 'resume', delivery['idempotency_key'], note='Resumed by the customer.')
                    if not done['run_id']:
                        raise CapabilityUnavailable('resume did not start a run')
                    ack = {'run_id': done['run_id']}
            else:
                ack = gateway.send(session, delivery['idempotency_key'], delivery['payload'], queue_mode='steer' if delivery['kind'] == 'steer' else None,
                                   goal_issued_ms=delivery['goal_issued_ms'] if delivery['kind'] == 'goal_start' else None)
        except Exception:
            self._set_delivery(claim, delivery['attempt'], 'uncertain')
            raise
        self._set_delivery(claim, delivery['attempt'], 'acknowledged', run_id=ack['run_id'], deadline=None if delivery['deadline_epoch'] else int(self.clock()) + self.run_timeout)       # presenting an input again never buys it more time
        if delivery['attempt'] == 1 and delivery['state'] == 'pending':
            self._emit(claim, 'progress', {'summary': 'The assistant has your message and is working on it.', 'step': 'working'}, 'gateway')

    # -- 2. supervise: ask the runtime when the run ended ------------------------------------------------------------------------------------------
    def _supervise(self, claim, gateway, info):
        session = info['session'] or self._session(claim)
        seen = self._seen_activity(claim)
        spend, outage, nudged = {'next': 0}, None, {}
        while True:
            if self._cancel_requested(claim):
                return self._stop(claim, gateway, session)
            if self.heartbeat is not None:
                self.heartbeat(claim)
            owed = self._deliveries(claim, states=LIVE_STATES)
            if not owed:
                if self.queue.close_gate(claim):
                    break
                continue
            delivery = owed[0]
            if delivery['state'] in ('pending', 'uncertain') and not delivery['native_run_id'] or delivery['state'] == 'pending':
                self._present(claim, gateway, session, delivery)
                continue
            try:
                result = gateway.wait(delivery['native_run_id'] or delivery['idempotency_key'], self.wait_ms)
            except CapabilityUnavailable:
                if self._cell_gone(gateway):
                    return self._interrupted(claim, gateway)
                # The cell went away for a moment (a restart, a reconnect). The run is the runtime's, so this is waiting, not failing: for a while.
                outage = outage if outage is not None else self.clock()
                if self.clock() - outage > self.outage_limit:
                    raise
                self.sleep(self.pause * 4)
                continue
            if outage is not None:
                outage = None
                self._reassert(claim, gateway, session)          # it came back: a restart may have lost an input it had accepted but not started
                continue
            self._mirror(claim, gateway, session, seen)
            if result['status'] == 'running':
                reason = self._human_wait(claim)
                if reason:
                    return Parked(reason)
                if delivery['deadline_epoch'] and self.clock() >= delivery['deadline_epoch']:
                    return self._timed_out(claim, gateway, session, delivery)
                over = self._over_budget(claim, gateway, spend)
                if over:
                    return self._budget_stop(claim, gateway, session)
                self._present_again_if_unheard(claim, gateway, session, delivery, nudged)
                self.sleep(self.pause)
                continue
            self._end_delivery(claim, delivery, result)
        return self._finish(claim, gateway, {**info, 'session': session})

    def _reassert(self, claim, gateway, session):
        """Present every live input to the runtime again. Safe by construction: the idempotency key is the run id, so an input the runtime still has (or already finished) answers
        in_flight or ok and starts nothing, and one it lost in a restart starts now, once. This is how a request survives a cell restart with exactly one run."""
        for delivery in self._deliveries(claim, states=LIVE_STATES):
            if delivery['kind'] == 'goal_resume' and not delivery['native_run_id']:
                continue                                         # not yet handed over: the loop delivers it
            try:
                self._present(claim, gateway, session, delivery)
            except CapabilityUnavailable:
                pass                                              # still unreachable: the supervision loop notices and waits

    def _present_again_if_unheard(self, claim, gateway, session, delivery, nudged):
        """A run the runtime has not finished reads as "still running" whether it is really running or it never heard of the input (a restart can lose one it had accepted but not
        started). Telling them apart is not needed: presenting the input again is a no-op for a live run (in_flight) or a finished one (ok) and starts a lost one, once. So an input
        that has been quiet is presented again on a growing gap (LOST_AFTER, doubling, at most two minutes). Never buys the run more time."""
        now = self.clock()
        last, gap = nudged.get(delivery['attempt'], (delivery['updated_epoch'], LOST_AFTER))
        if now - last < gap:
            return
        nudged[delivery['attempt']] = (now, min(gap * 2, 120))
        try:
            self._present(claim, gateway, session, delivery)
        except CapabilityUnavailable:
            pass

    def _end_delivery(self, claim, delivery, result):
        if result['status'] == 'ok':
            state, status = 'completed', 'ok'
        elif result['aborted']:
            state, status = 'aborted', 'aborted'
        else:
            state, status = 'failed', 'error:' + str(result['error'] or 'error')[:150]
        self._set_delivery(claim, delivery['attempt'], state, ended=int(self.clock()), status=status, tools=json.dumps(result['tools']) if result['tools'] else None)

    # -- progress for the customer (display only; completion never comes from here) ------------------------------------------------------------
    def _seen_activity(self, claim):
        seen = set()
        try:
            with self.store.connect() as con:
                for row in con.execute("SELECT public_payload FROM events WHERE account_id=? AND task_id=? AND kind='activity'", (claim.account_id, claim.request_id)).fetchall():
                    payload = json.loads(row[0])
                    seen.add((payload.get('ref'), payload.get('status')))
        except Exception:
            pass
        return seen

    def _mirror(self, claim, gateway, session, seen):
        """Copy the replies of THIS request's runs into the transcript as they land, and show the tool work they did. Attribution is by native run id."""
        try:
            page = gateway.history(session)
        except CapabilityUnavailable:
            return 0
        deliveries = self._deliveries(claim)
        runs = {d['native_run_id'] for d in deliveries if d['native_run_id']}
        keys = {d['idempotency_key'] for d in deliveries}
        mine = lambda row: row.get('run_id') in runs or row.get('after') in keys         # a steered input's reply has a run id of its own: it is tied to the input it follows
        rows = [r for r in page['messages'] if r['role'] == 'agent' and mine(r)]
        with self.coordinator.transaction() as con:
            added = self._absorb(con, claim, rows)
        for item in page.get('activity') or []:
            if not mine(item):
                continue
            key = (item['ref'], item['status'])
            if key in seen:
                continue
            seen.add(key)
            self._emit(claim, 'activity', {k: v for k, v in item.items() if k not in ('run_id', 'after')}, 'gateway')
        return added

    def _absorb(self, con, claim, rows):
        added = 0
        for row in rows:
            native_id, content = row.get('id'), row.get('content')
            if not isinstance(native_id, str) or not isinstance(content, str) or not content or len(content) > MAX_TRANSCRIPT_CHARS:
                continue
            added += con.execute('''INSERT OR IGNORE INTO chat_messages(account_id,conversation_id,request_id,provenance,content,native_message_id)
                VALUES (?,?,?,'agent',?,?)''', (claim.account_id, claim.conversation_id, claim.request_id, content, native_id)).rowcount
        return added

    def _human_wait(self, claim):
        """Is the run waiting for a person? The browser tool runs inside the runtime's tool call; its job says when it needs the customer (a question, or the customer driving)."""
        with self.store.connect() as con:
            row = con.execute('SELECT status FROM browse_runs WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchone()
        return HUMAN_WAIT.get(row['status']) if row else None

    # -- limits --------------------------------------------------------------------------------------------------------------------------------
    def _usage_before(self, gateway):
        snapshot = getattr(gateway, 'usage_snapshot', None)
        if snapshot is None:
            return None
        try:
            return snapshot()
        except Exception:
            return None

    def _reserved(self, claim):
        with self.store.connect() as con:
            row = con.execute('SELECT amount_microusd FROM task_reservations WHERE account_id=? AND task_id=?', (claim.account_id, claim.request_id)).fetchone()
        return int(row[0]) if row else None

    def _over_budget(self, claim, gateway, spend):
        """The customer's spending limit holds while a run is going, not only at admission: a run that has spent its reservation is stopped."""
        if self.clock() < spend['next']:
            return False
        spend['next'] = self.clock() + self.spend_check_seconds
        reserved = self._reserved(claim)
        first = next(iter(self._deliveries(claim)), None)
        if not reserved or not first or first['usage_before_microusd'] is None or getattr(gateway, 'usage_snapshot', None) is None:
            return False
        try:
            return gateway.usage_snapshot() - first['usage_before_microusd'] >= reserved
        except Exception:
            return False

    def _abort_all(self, claim, gateway, session):
        """Stop every run of the session and wait until the runtime says each owed run is over. Raises when it cannot be confirmed (the request stays recoverable)."""
        if not gateway.capabilities().abort:
            raise CapabilityUnavailable('native abort unsupported; cancellation intent stays recorded')
        gateway.abort(session)
        for delivery in self._deliveries(claim, states=LIVE_STATES):
            if delivery['state'] == 'pending' and not delivery['native_run_id']:
                self._set_delivery(claim, delivery['attempt'], 'aborted', ended=int(self.clock()), status='aborted')       # never reached the runtime
                continue
            run = delivery['native_run_id'] or delivery['idempotency_key']
            for _ in range(30):
                result = gateway.wait(run, 1000)
                if result['status'] != 'running':
                    self._end_delivery(claim, delivery, result)
                    break
                self.sleep(self.pause)
            else:
                if not delivery['native_run_id'] or not gateway.history(session)['active_run']:
                    # The runtime has no word of this run and nothing is running in the session (a restart lost it): there is nothing left to stop.
                    self._set_delivery(claim, delivery['attempt'], 'aborted', ended=int(self.clock()), status='aborted')
                else:
                    raise CapabilityUnavailable('the runtime has not confirmed the run is over')

    def _stop_browser_jobs(self, claim):
        if self.browse_factory is None:
            return
        try:
            from .browse import sessions as browse_sessions
            with self.store.connect() as con:
                jobs = [claim.request_id] + [r[0] for r in con.execute('SELECT job_id FROM browse_sessions WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchall()]
            rpc = self.browse_factory(claim.account_id)
            for job in jobs:
                try:
                    rpc('cancel', request_id=job)
                except Exception:
                    pass
        except Exception:
            pass

    def _release_waiting_browser_jobs(self, claim):
        """The run is over: a browser job still waiting for the assistant's next step will never get one. A job in a hand-off window for the customer is left alone."""
        if self.browse_factory is None:
            return
        try:
            from .browse import sessions as browse_sessions
            with self.store.connect() as con:
                jobs = [claim.request_id] + [r[0] for r in con.execute('SELECT job_id FROM browse_sessions WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchall()]
            rpc = self.browse_factory(claim.account_id)
            for job in jobs:
                try:
                    rpc('agent_release', request_id=job)
                except Exception:
                    pass
        except Exception:
            pass

    def _pause_goal(self, claim, gateway, session, note):
        """A stopped, timed-out or over-budget run never leaves its goal active: nothing may pick it up again unless the customer resumes it."""
        try:
            if gateway.capabilities().goals:
                goal = gateway.session_goal(session)
                if goal is not None and goal['status'] == 'active':
                    gateway.goal_update(session, goal['id'], 'pause', f'pause-{claim.request_id[:16]}-{uuid.uuid4().hex[:8]}', note=note)
        except Exception:
            pass

    def _stop(self, claim, gateway, session):
        """The customer pressed Stop (or was revoked). Abort, wait for the runtime to confirm, pause the goal, then close as cancelled."""
        self._stop_browser_jobs(claim)
        if self._cell_gone(gateway):
            return self._interrupted(claim, gateway)
        self._abort_all(claim, gateway, session)
        self._pause_goal(claim, gateway, session, 'Stopped by the customer.')
        self._emit(claim, 'progress', {'summary': 'Cancellation confirmed by the runtime.'}, 'gateway')
        self._mirror(claim, gateway, session, set())
        return self._close(claim, 'cancelled', 'Cancelled during execution', gateway, self._before(claim), verdict=outcome_mod.judge(native={}, cancelled=True))

    def _timed_out(self, claim, gateway, session, delivery):
        self._abort_all(claim, gateway, session)
        self._stop_browser_jobs(claim)
        self._pause_goal(claim, gateway, session, 'The run took too long and was stopped.')
        self._emit(claim, 'progress', {'summary': 'The run took too long and was stopped.'}, 'gateway')
        return self._close(claim, 'failed', 'The assistant took too long and was stopped. Please try a smaller request.', gateway, self._before(claim),
                           verdict=outcome_mod.Verdict('failed', 'unverified', 'The assistant took too long and was stopped.', ''))

    def _budget_stop(self, claim, gateway, session):
        self._abort_all(claim, gateway, session)
        self._stop_browser_jobs(claim)
        self._pause_goal(claim, gateway, session, 'The spending limit for this task was reached.')
        self._mirror(claim, gateway, session, set())
        self._emit(claim, 'budget', {'note': 'The spending limit for this task was reached.'}, 'gateway')
        note = 'The spending limit for this task was reached, so the work was stopped.'
        return self._close(claim, 'completed', self._last_reply(claim) or note, gateway, self._before(claim),
                           verdict=outcome_mod.Verdict('partial', 'unverified', note, 'Stopped: ' + note))

    def _before(self, claim):
        first = next(iter(self._deliveries(claim)), None)
        return first['usage_before_microusd'] if first else None

    # -- 3. close the request ------------------------------------------------------------------------------------------------------------------
    def _last_reply(self, claim):
        with self.store.connect() as con:
            row = con.execute("SELECT content FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance='agent' ORDER BY id DESC LIMIT 1",
                              (claim.account_id, claim.conversation_id, claim.request_id)).fetchone()
        return row[0] if row else None

    def _finish(self, claim, gateway, info):
        session = info['session']
        self._mirror(claim, gateway, session, self._seen_activity(claim))
        deliveries = self._deliveries(claim)
        starters = [d for d in deliveries if d['kind'] in KINDS_THAT_START_RUNS]
        last = starters[-1] if starters else deliveries[-1]
        native = {'status': 'ok' if last['state'] == 'completed' else 'error', 'aborted': last['state'] == 'aborted',
                  'error': (last['native_status'] or '').removeprefix('error:') or None}
        if native['status'] != 'ok':
            return self._failed(claim, gateway, session, native)
        if info['intent'] == 'plan' and self.genui is not None:
            repaired = self._plan_reply(claim, gateway, info, session)
            if isinstance(repaired, RequestReceipt) or isinstance(repaired, (Parked, Defer)):
                return repaired
        self._release_waiting_browser_jobs(claim)
        self._capture_files(claim, gateway, since=min((d['created_epoch'] for d in deliveries), default=int(self.clock())) - 5)
        if self.genui is not None and info['intent'] != 'plan':
            made = 0
            try:
                made = self.genui.blocks.attach_cards(claim.account_id, claim.conversation_id, claim.request_id)
            except Exception:
                pass                        # a card that cannot be stored never fails the answer; the text stays
            if not made and self.display is not None:
                self._choose_display(claim)
        goal = self._goal(gateway, session) if (info['goal_mode'] or info['intent'] in ('goal_continue', 'goal_resume')) else None
        jobs, steps = self._browser_evidence(claim)
        reply = self._last_reply(claim)
        continuing = bool(goal and goal['status'] == 'active' and self._chain_length(claim) < self.goal_chain_limit)
        verdict = outcome_mod.judge(native=native, goal=goal, jobs=jobs, steps=steps, artifacts=self._artifact_count(claim), reply=bool(reply or last['native_status'] == 'ok'),
                                    goal_continuing=continuing)
        if verdict.line and reply and len(reply) + len(verdict.line) + 2 <= MAX_TRANSCRIPT_CHARS:
            self._append_line(claim, verdict.line)
            reply = self._last_reply(claim)
        public = reply if reply else 'Completed without an agent transcript row; reconcile history before relying on this result.'
        self._emit(claim, 'result', {'summary': public[:500], 'outcome': verdict.outcome, 'verify_level': verdict.verification})
        return self._close(claim, 'completed', public, gateway, self._before(claim), verdict=verdict, continue_goal=continuing)

    def _failed(self, claim, gateway, session, native):
        self._stop_browser_jobs(claim)
        self._pause_goal(claim, gateway, session, 'The run ended with an error.')
        message = 'The assistant took too long and was stopped. Please try a smaller request.' if 'timeout' in str(native['error']) else 'The assistant could not finish this request. Nothing more will run; please try again.'
        self._emit(claim, 'error', {'summary': message, 'category': 'runtime'}, 'gateway')
        state = 'cancelled' if native['aborted'] and self._cancel_requested(claim) else 'failed'
        return self._close(claim, state, message if state == 'failed' else 'Cancelled during execution', gateway, self._before(claim),
                           verdict=outcome_mod.judge(native=native, cancelled=state == 'cancelled'))

    def _goal(self, gateway, session):
        try:
            return gateway.session_goal(session) if gateway.capabilities().goals else None
        except CapabilityUnavailable:
            return None

    def _chain_length(self, claim):
        with self.store.connect() as con:
            return con.execute('''WITH RECURSIVE chain(id) AS (SELECT ? UNION ALL SELECT r.continues FROM customer_requests r JOIN chain c ON r.id=c.id AND r.account_id=? WHERE r.continues IS NOT NULL)
                SELECT count(*) FROM chain''', (claim.request_id, claim.account_id)).fetchone()[0]

    def _append_line(self, claim, line):
        try:
            with self.coordinator.transaction() as con:
                row = con.execute("SELECT id,content FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance='agent' ORDER BY id DESC LIMIT 1",
                                  (claim.account_id, claim.conversation_id, claim.request_id)).fetchone()
                if row:
                    con.execute('UPDATE chat_messages SET content=? WHERE id=?', (row['content'].rstrip() + '\n\n' + line, row['id']))
        except Exception:
            pass                                                           # a line that cannot be stored never fails the answer; the outcome is still on the result event

    def _browser_evidence(self, claim):
        """The request's browser jobs (oldest first) and the steps they took, from the rows the browser tool keeps: what outcome.py judges, never page text."""
        jobs, steps = [], []
        try:
            with self.store.connect() as con:
                run = con.execute('SELECT status,url,reason FROM browse_runs WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchone()
                if run:
                    jobs.append({'state': run['status'], 'url': run['url'], 'reason': run['reason']})
                for r in con.execute('SELECT data_json FROM browse_steps WHERE account_id=? AND request_id=? AND kind=? ORDER BY n', (claim.account_id, claim.request_id, 'step')).fetchall():
                    try:
                        steps.append(json.loads(r[0]))
                    except ValueError:
                        pass
        except Exception:
            pass
        return jobs, steps

    def _artifact_count(self, claim):
        with self.store.connect() as con:
            return con.execute("SELECT COUNT(*) FROM events WHERE account_id=? AND task_id=? AND kind='artifact'", (claim.account_id, claim.request_id)).fetchone()[0]

    def _plan_reply(self, claim, gateway, info, session):
        """A plan request's reply must be a valid plan; one bounded repair turn in the same session, then the plain reply is shown as text."""
        reply = self._last_reply(claim) or ''
        plan, reason = self.genui.validate_reply(reply)
        if plan is None and not any(d['kind'] == 'turn' and d['attempt'] > 1 for d in self._deliveries(claim)):
            from .genui import prompts as gen_prompts
            self._emit(claim, 'progress', {'summary': 'The plan needs a correction; asking once more.'}, 'gateway')
            payload = gen_prompts.repair_prompt(reason)
            with self.coordinator.transaction() as con:
                attempt = con.execute('SELECT coalesce(max(attempt),0)+1 FROM chat_deliveries WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchone()[0]
                key, now = f'{claim.request_id}-a{attempt}', int(self.clock())
                con.execute('''INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,created_epoch,updated_epoch,kind,payload)
                    VALUES (?,?,?,?,?,'pending',?,?,?,'turn',?)''', (claim.account_id, claim.request_id, attempt, key, hashlib.sha256(payload.encode()).hexdigest(), key, now, now, payload))
            return self._supervise(claim, gateway, info)
        if plan is not None:
            self.genui.attach_plan(claim, info['context'], plan)
            self._emit(claim, 'progress', {'summary': 'Plan drafted and ready to edit.'}, 'gateway')
        else:
            self._emit(claim, 'progress', {'summary': 'The reply could not be shown as a plan; showing it as text.'}, 'gateway')
        return None

    def _choose_display(self, claim):
        """The assistant answered in plain text: let JEV choose how that text is laid out (or leave it plain). Never fails the answer."""
        try:
            reply = self._last_reply(claim)
            decide = getattr(self.display, 'decide', None)
            style, plan = (decide(reply) if decide else (self.display.choose(reply), None)) if reply else (None, None)
            if style:
                self.genui.blocks.add_display(claim.account_id, claim.conversation_id, claim.request_id, style, plan)
        except Exception:
            pass

    def _capture_files(self, claim, gateway, since):
        """Save the files the assistant wrote during this task as versioned downloads. Best-effort: never fails the task."""
        collect = getattr(gateway, 'workspace_files', None)
        if self.artifacts is None or collect is None:
            return
        try:
            with self.store.connect() as con:
                row = con.execute('SELECT project_id FROM conversations WHERE account_id=? AND id=?', (claim.account_id, claim.conversation_id)).fetchone()
            if row is None:
                return
            from .files import ALLOWLIST, sniff
            for path, data in collect(since):
                ext = os.path.splitext(path)[1].lower()
                kinds = ALLOWLIST.get(ext)
                kind = sniff(data)
                if not kinds or (kind not in kinds and not (kind == 'text' and 'json' in kinds)):
                    continue
                if 'json' in kinds:
                    try:
                        json.loads(data.decode('utf-8'))
                    except ValueError:
                        continue
                saved = self.artifacts.capture_or_version(account_id=claim.account_id, project_id=row['project_id'], task_id=claim.request_id,
                                                          name=path.replace('/', '_')[:128], media_type=MEDIA.get(ext, 'application/octet-stream'), data=data)
                if saved:
                    self._emit(claim, 'artifact', {'artifact_id': saved['artifact_id'], 'version': saved['version'], 'name': path.replace('/', '_')[:128],
                                                   'sha256': saved['sha256']}, 'gateway')
        except Exception:
            pass

    # -- usage and settlement ------------------------------------------------------------------------------------------------------------------
    def _reconcile_usage(self, gateway, claim, before):
        """Record what the provider key actually spent for this task as a ledger receipt.

        Falls back to the reserved upper bound when provider spend cannot be read, so the slot never wedges and the customer is never under-charged silently.
        Spend lands at the provider a little after the run: the reading is taken again until it holds still.
        """
        snapshot = getattr(gateway, 'usage_snapshot', None)
        if snapshot is None:
            return
        reserved = self._reserved(claim)
        amount, version, last = None, 'reservation-upper-bound-v1', None
        if before is not None:
            deadline = self.clock() + self.usage_wait
            stable = 0
            while True:
                try:
                    now_spend = snapshot()
                except Exception:
                    break
                stable = stable + 1 if now_spend == last else 0
                last = now_spend
                if stable >= 1 and now_spend > before:
                    amount, version = now_spend - before, 'litellm-reported-v1'
                    break
                if self.clock() >= deadline:
                    if now_spend >= before:
                        amount, version = now_spend - before, 'litellm-reported-v1'
                    break
                self.sleep(self.pause)
        if amount is None:
            amount = reserved if reserved else 0
        digest = hashlib.sha256(json.dumps({'before': before, 'after': last, 'task': claim.request_id}).encode()).hexdigest()
        self.ledger.receipt(account=claim.account_id, task=claim.request_id, provider='litellm',
                            request='litellm-' + claim.request_id, amount_microusd=int(amount),
                            observed_epoch=int(self.clock()), price_version=version, payload_hash=digest)

    def _close(self, claim, state, public_result, gateway=None, before=None, *, verdict=None, continue_goal=False):
        # Usage must reconcile before the global slot hands over (queue.finish rechecks).
        with self.store.connect() as con:
            funded = con.execute('SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=?', (claim.account_id, claim.request_id)).fetchone()
        if funded:   # a request that never got a reservation has nothing to reconcile or settle
            if gateway is not None:
                self._reconcile_usage(gateway, claim, before)
            self.ledger.settle(account=claim.account_id, task=claim.request_id, effects_quiesced=True, all_routes_reconciled=True)
        outcome = verdict.outcome if verdict else state
        task_state = {'completed': 'completed', 'partial': 'completed', 'blocked': 'blocked', 'failed': 'failed', 'cancelled': 'cancelled'}[outcome]
        with self.coordinator.transaction() as con:
            con.execute('UPDATE tasks SET state=? WHERE account_id=? AND id=?', (task_state, claim.account_id, claim.request_id))
            self.coordinator._audit(con, claim.account_id, 'worker', claim.request_id, 'chat.' + state, 'completed')
        return RequestReceipt(claim.account_id, claim.request_id, claim.fence, state, public_result[:MAX_TRANSCRIPT_CHARS], True,
                              outcome=outcome, outcome_note=verdict.note if verdict else '', verification=verdict.verification if verdict else None, continue_goal=continue_goal)

    # -- parked requests, crash recovery, last resort ------------------------------------------------------------------------------------------
    def check_parked(self, claim):
        """-> 'waiting' (a person still has the wheel), 'ready' (they handed it back: carry on) or 'ended' (the run ended, was stopped, or waited too long: close it)."""
        if self._cancel_requested(claim):
            return 'ended'
        try:
            gateway = self.gateway_factory(claim)
            owed = self._deliveries(claim, states=LIVE_STATES)
            for delivery in owed:
                if delivery['native_run_id'] and gateway.wait(delivery['native_run_id'], 0)['status'] != 'running':
                    return 'ended'
        except CapabilityUnavailable:
            return 'waiting'
        with self.store.connect() as con:
            parked = con.execute('SELECT parked_epoch FROM customer_requests WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()
        since = parked['parked_epoch'] if parked and parked['parked_epoch'] else int(self.clock())
        if self._human_wait(claim):
            if self.clock() - since >= self.park_limit:
                return 'ended'
            return 'waiting'
        self._extend_deadlines(claim, int(self.clock()) - since)      # the time a person took does not count against the run
        return 'ready'

    def _extend_deadlines(self, claim, seconds):
        if seconds <= 0:
            return
        with self.coordinator.transaction() as con:
            con.execute("UPDATE chat_deliveries SET deadline_epoch=deadline_epoch+? WHERE account_id=? AND request_id=? AND state IN ('acknowledged','uncertain') AND deadline_epoch IS NOT NULL",
                        (seconds, claim.account_id, claim.request_id))

    def abandon(self, claim: RequestClaim):
        """Last resort for a request whose runtime cannot be reached for a long time: fail it and charge the reserved upper bound."""
        for delivery in self._deliveries(claim, states=LIVE_STATES):
            self._set_delivery(claim, delivery['attempt'], 'aborted', ended=int(self.clock()), status='aborted')
        self._emit(claim, 'progress', {'summary': 'The runtime could not be reached; the request was stopped.'}, 'reconciler')
        self._stop_browser_jobs(claim)

        class _Blind:
            def usage_snapshot(self): raise RuntimeError('runtime unreachable')
        return self._close(claim, 'failed', 'The assistant could not be reached for this request, so it was stopped. Please try again.', _Blind(), None,
                           verdict=outcome_mod.Verdict('failed', 'unverified', 'The assistant could not be reached.', ''))

    @staticmethod
    def _cell_gone(gateway):
        probe = getattr(gateway, 'cell_running', None)
        try:
            return probe is not None and probe() is False
        except Exception:
            return False                         # a timeout or refusal proves nothing about execution

    def _browser_stopped(self, claim):
        """An external browser must also stop before releasing the execution slot."""
        with self.store.connect() as con:
            jobs = [claim.request_id] + [r[0] for r in con.execute('SELECT job_id FROM browse_sessions WHERE account_id=? AND request_id=?', (claim.account_id, claim.request_id)).fetchall()]
            active = con.execute("SELECT 1 FROM browse_runs WHERE account_id=? AND request_id=? AND status IN ('queued','running','handoff','paused','asking')", (claim.account_id, claim.request_id)).fetchone()
        if self.browse_factory is None:
            return active is None
        from .browse.client import BrowseJobUnknown
        rpc = self.browse_factory(claim.account_id)
        for job in jobs:
            try:
                state = rpc('poll', request_id=job, since=0).get('state')
            except BrowseJobUnknown:
                continue                         # service restart destroyed this job
            except Exception:
                return False
            if state not in ('done', 'error', 'cancelled', 'blocked', 'budget', 'deadline', 'max_steps', 'stuck', 'stopped'):
                return False
        return True

    def _interrupted(self, claim, gateway):
        """Only called after the host confirms the container is stopped. No model calls or replay."""
        cancelled = self._cancel_requested(claim)
        self._stop_browser_jobs(claim)             # an external browser can outlive the assistant
        if not self._browser_stopped(claim):
            raise CapabilityUnavailable('waiting for browser cancellation confirmation')
        for delivery in self._deliveries(claim, states=LIVE_STATES):
            self._set_delivery(claim, delivery['attempt'], 'aborted' if cancelled else 'failed',
                               ended=int(self.clock()), status='container_stopped')
        state = 'cancelled' if cancelled else 'failed'
        note = 'Stopped at your request.' if cancelled else 'The assistant stopped unexpectedly. Please try again.'
        self._emit(claim, 'progress' if cancelled else 'error', {'summary': note}, 'reconciler')
        verdict = outcome_mod.judge(native={}, cancelled=True) if cancelled else outcome_mod.Verdict('failed', 'unverified', note, '')
        return self._close(claim, state, note, gateway, self._before(claim), verdict=verdict)

    def reconcile(self, claim: RequestClaim):
        """A request left uncertain (crash, lease loss). The run is the runtime's, so there is nothing to guess: if the runtime can be reached, supervision simply carries on from
        the stored deliveries (a send whose outcome was unknown is repeated under the same key, which cannot start a second run); if no input was ever recorded, nothing ran."""
        if claim.conversation_id is None:
            raise ValueError('chat driver requires a conversation binding')
        if not self._deliveries(claim):
            return self._close(claim, 'failed', 'Your request could not be started. Nothing was charged. Please send it again.',
                               verdict=outcome_mod.Verdict('failed', 'unverified', 'It could not be started.', ''))
        gateway = self.gateway_factory(claim)
        if self._cell_gone(gateway):
            return self._interrupted(claim, gateway)
        try:
            self._require(gateway)
        except CapabilityUnavailable:
            return None
        return Recover()


def synthetic_gateway_factory(gateway: SyntheticGateway):
    def factory(claim):
        return gateway
    return factory
