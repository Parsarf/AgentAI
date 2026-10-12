"""Customer chat: conversations, admission-gated sends and native delivery.

The customer surface owns projects/conversations/transcript metadata. Native
execution stays behind the Phase 5 admission fence and the global serial slot;
the driver here is the reference host-side sequence and is never installed in
a request path. Transcript authority: durable app rows map access; the native
session remains authoritative for execution and is reconciled by
native message identity, never by predicted positions.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from .adapters import CapabilityUnavailable
from .budget import BudgetDenied, BudgetLedger
from .events import EventService
from .gateway import SyntheticGateway
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .request_queue import RequestQueue, RequestClaim, RequestReceipt
from .security import NotFound, Principal

MAX_CONVERSATIONS_PER_PROJECT = 10
MAX_PROJECTS = 10  # product/plan.json max_projects; the numeric source of truth
MAX_TRANSCRIPT_CHARS = 16000
HISTORY_PAGES = 32
SETTLE_POLLS = 2   # consecutive idle history reads that end a run

BUDGET_CATEGORIES = (
    ('queue full', 'queue_full'),
    ('task allowance exhausted', 'task_allowance_exhausted'),
    ('account allowance exhausted', 'account_allowance_exhausted'),
    ('service allocation exhausted', 'service_allowance_exhausted'),
)


class UnmeasuredRoute:
    """Production default: no verified metered provider route exists, so no
    send can be funded. Requests stay waiting, like the request page."""

    def reservation(self, message: str):
        raise CapabilityUnavailable('provider route not measured')


class FixedRoute:
    """Test/diagnostic route yielding a verified per-message upper bound."""

    def __init__(self, amount_microusd: int, price_version: str = 'fixed-route-v1'):
        if type(amount_microusd) is not int or amount_microusd <= 0:
            raise ValueError('invalid fixed amount')
        self.amount, self.price_version = amount_microusd, price_version

    def reservation(self, message: str):
        return self.amount, self.price_version


def denial_category(error: BudgetDenied) -> str:
    text = str(error)
    for prefix, category in BUDGET_CATEGORIES:
        if text.startswith(prefix):
            return category
    return 'admission_unavailable'


class ChatService:
    def __init__(self, store, *, queue: RequestQueue, ledger: BudgetLedger, pricer=UnmeasuredRoute(),
                 clock=time.time, max_conversations_per_project=MAX_CONVERSATIONS_PER_PROJECT, execution=False):
        self.execution = bool(execution)   # owner switch state, shown to the customer UI
        self.store = store
        self.queue = queue
        self.ledger = ledger
        self.pricer = pricer
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)
        self.max_conversations_per_project = max_conversations_per_project

    def create_conversation(self, principal: Principal, project_id: str):
        identifier(project_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?', (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            count = con.execute('SELECT count(*) FROM conversations WHERE account_id=? AND project_id=?',
                                (principal.account_id, project_id)).fetchone()[0]
            if count >= self.max_conversations_per_project:
                raise Conflict('conversation limit reached')
            deployment = con.execute("""SELECT id FROM deployments WHERE account_id=? AND state NOT IN ('deleted','deleting')
                ORDER BY generation DESC,id DESC LIMIT 1""", (principal.account_id,)).fetchone()
            if not deployment:
                raise Conflict('account setup incomplete')
            conversation = uuid.uuid4().hex
            con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)',
                        (principal.account_id, project_id, conversation, deployment[0]))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, conversation, 'chat.conversation_create', 'completed')
            return {'id': conversation, 'project_id': project_id}

    def conversations(self, principal: Principal, project_id: str | None = None):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            sql = 'SELECT c.id,c.project_id,c.created_at FROM conversations c WHERE c.account_id=?'
            args: list = [principal.account_id]
            if project_id is not None:
                identifier(project_id)
                sql += ' AND c.project_id=?'
                args.append(project_id)
            return [dict(row) for row in con.execute(sql + ' ORDER BY c.created_at,c.id LIMIT 100', args).fetchall()]

    def conversation(self, principal: Principal, conversation_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT id,project_id,created_at FROM conversations WHERE account_id=? AND id=?',
                              (principal.account_id, conversation_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            return dict(row)

    def projects(self, principal: Principal):
        return self.store.list_projects(principal)

    def create_project(self, principal: Principal, name: str):
        if not isinstance(name, str) or not name.strip() or len(name) > 120 or '\x00' in name:
            raise ValueError('invalid project name')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            count = con.execute('SELECT count(*) FROM projects WHERE account_id=?', (principal.account_id,)).fetchone()[0]
            if count >= MAX_PROJECTS:
                raise Conflict('project limit reached')
            project = uuid.uuid4().hex
            con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (principal.account_id, project, name))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, project, 'chat.project_create', 'completed')
            return {'id': project, 'name': name}

    def send(self, principal: Principal, *, conversation_id: str, message: str, key: str,
             provenance: str = 'customer'):
        """One actionable request per send; admission via Phase 5 before any
        native effect. A repeat with the same key never starts a second task."""
        identifier(key)
        if not isinstance(message, str) or not message.strip() or len(message) > 16000 or '\x00' in message:
            raise ValueError('invalid message')
        self.conversation(principal, conversation_id)
        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id)
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT project_id FROM customer_requests WHERE account_id=? AND id=?',
                              (principal.account_id, result['id'])).fetchone()
            if not row:
                raise NotFound('unavailable')
            project_id = row['project_id']
            if not con.execute("""SELECT 1 FROM chat_messages WHERE account_id=? AND conversation_id=?
                AND request_id=? AND provenance IN ('customer','telegram')""",
                               (principal.account_id, conversation_id, result['id'])).fetchone():
                con.execute('''INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content)
                    VALUES (?,?,?,?,?)''', (principal.account_id, conversation_id, result['id'], provenance, message))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, result['id'], 'chat.send', 'completed')
        try:
            amount, price_version = self.pricer.reservation(message)
        except CapabilityUnavailable:
            # No verified route: the request waits unfunded, execution stays off.
            return {**result, 'conversation_id': conversation_id, 'execution_enabled': False,
                    'admission': 'route_unconfigured', 'price_version': None}
        try:
            self.ledger.admit(principal, task=result['id'], project=project_id, conversation=conversation_id,
                              key=key, amount_microusd=amount, upper_bound_verified=True)
        except BudgetDenied:
            # An unfundable request must not occupy the queue or the serial slot.
            self.queue.cancel(principal, result['id'])
            raise
        return {**result, 'conversation_id': conversation_id, 'execution_enabled': True,
                'admission': 'reserved', 'price_version': price_version}

    def messages(self, principal: Principal, conversation_id: str, *, after: int = 0, limit: int = 100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid pagination')
        self.conversation(principal, conversation_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('''SELECT id,request_id,provenance,content,created_at FROM chat_messages
                WHERE account_id=? AND conversation_id=? AND id>? ORDER BY id LIMIT ?''',
                (principal.account_id, conversation_id, after, limit)).fetchall()
            tasks = con.execute('''SELECT r.id,r.state,r.cancel_requested,r.result,r.created_epoch,t.state AS task_state,
                    t.budget_microusd,v.state AS reservation_state
                FROM customer_requests r LEFT JOIN tasks t ON t.account_id=r.account_id AND t.id=r.id
                LEFT JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND r.conversation_id=? ORDER BY r.sequence DESC LIMIT 20''',
                (principal.account_id, conversation_id)).fetchall()
            return {'conversation_id': conversation_id,
                    'messages': [dict(row) for row in rows], 'tasks': [dict(row) for row in tasks],
                    'execution_enabled': self.execution}

    def task(self, principal: Principal, request_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT r.id,r.state,r.cancel_requested,r.result,r.created_epoch,r.conversation_id,
                    t.state AS task_state,t.budget_microusd,v.state AS reservation_state
                FROM customer_requests r LEFT JOIN tasks t ON t.account_id=r.account_id AND t.id=r.id
                LEFT JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND r.id=?''', (principal.account_id, request_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            return {**dict(row), 'execution_enabled': self.execution}

    def cancel(self, principal: Principal, request_id: str):
        return self.queue.cancel(principal, request_id)


class ChatDriver:
    """Reference trusted-host execution sequence for chat requests.

    Follows the worker boundary: repeat account authorization after the
    claim, require the active reservation before any native effect, record
    every delivery attempt, reconcile by native receipts and never resend an
    unknown-outcome send. Cancellation intent aborts the scoped run; abort
    stops generation without undoing effects.
    """

    def __init__(self, store, *, ledger: BudgetLedger, gateway_factory, clock=time.time,
                 events: EventService | None = None, sleep=None, poll_interval=1.5, run_timeout=900, usage_wait=45, heartbeat=None):
        self.heartbeat = heartbeat   # callable(claim): keeps the queue lease alive during long runs
        self.sleep = sleep if sleep is not None else (lambda seconds: None)
        self.poll_interval, self.run_timeout, self.usage_wait = poll_interval, run_timeout, usage_wait
        self.store = store
        self.ledger = ledger
        self.gateway_factory = gateway_factory
        self.events = events
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)

    def _emit(self, claim, kind: str, payload: dict | None = None, source: str = 'worker'):
        # Timeline appends are best-effort: a failed event write degrades the
        # timeline view, never the task or its budget state.
        if self.events is None:
            return
        self.events.append(claim.account_id, claim.request_id, kind, payload, source)

    def preflight(self):
        gateway = self.gateway_factory(None)
        caps = gateway.capabilities()
        for operation in ('send', 'history'):
            if not getattr(caps, operation):
                raise CapabilityUnavailable('gateway probe did not verify ' + operation)

    def _start_delivery(self, con, claim):
        attempt = con.execute('SELECT coalesce(max(attempt),0) FROM chat_deliveries WHERE account_id=? AND request_id=?',
                              (claim.account_id, claim.request_id)).fetchone()[0] + 1
        operation_id = uuid.uuid4().hex
        now = int(self.clock())
        con.execute('''INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,
            native_operation_id,created_epoch,updated_epoch) VALUES (?,?,?,?,?,'pending',?,?,?)''',
            (claim.account_id, claim.request_id, attempt, claim.request_id + '-' + str(attempt), operation_id,
             operation_id, now, now))
        return attempt, operation_id

    def _set_delivery(self, con, claim, attempt, state, *, run_id=None, ack_seq=None):
        con.execute('''UPDATE chat_deliveries SET state=?,native_run_id=coalesce(?,native_run_id),
            ack_message_seq=coalesce(?,ack_message_seq),updated_epoch=? WHERE account_id=? AND request_id=? AND attempt=?''',
            (state, run_id, ack_seq, int(self.clock()), claim.account_id, claim.request_id, attempt))

    def _absorb(self, con, claim, messages):
        added = 0
        for row in messages:
            native_id, role, content = row.get('id'), row.get('role'), row.get('content')
            if not isinstance(native_id, str) or not isinstance(content, str) or not content or len(content) > MAX_TRANSCRIPT_CHARS:
                continue
            provenance = {'customer': 'customer', 'agent': 'agent', 'assistant': 'agent'}.get(role)
            if provenance == 'customer':
                con.execute('''UPDATE chat_messages SET native_message_id=? WHERE account_id=? AND conversation_id=?
                    AND request_id=? AND provenance='customer' AND native_message_id IS NULL''',
                    (native_id, claim.account_id, claim.conversation_id, claim.request_id))
            elif provenance == 'agent':
                added += con.execute('''INSERT OR IGNORE INTO chat_messages(account_id,conversation_id,request_id,provenance,content,native_message_id)
                    VALUES (?,?,?,'agent',?,?)''', (claim.account_id, claim.conversation_id, claim.request_id, content, native_id)).rowcount
        return added

    def _usage_before(self, gateway):
        snapshot = getattr(gateway, 'usage_snapshot', None)
        if snapshot is None:
            return None
        try:
            return snapshot()
        except Exception:
            return None

    def _reconcile_usage(self, gateway, claim, before):
        """Record what the provider key actually spent for this task as a ledger receipt.

        Falls back to the reserved upper bound when provider spend cannot be read,
        so the slot never wedges and the customer is never under-charged silently.
        """
        snapshot = getattr(gateway, 'usage_snapshot', None)
        if snapshot is None:
            return
        with self.store.connect() as con:
            reserved = con.execute('SELECT amount_microusd FROM task_reservations WHERE account_id=? AND task_id=?',
                                   (claim.account_id, claim.request_id)).fetchone()
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
                self.sleep(self.poll_interval)
        if amount is None:
            amount = reserved[0] if reserved else 0
        digest = hashlib.sha256(json.dumps({'before': before, 'after': last, 'task': claim.request_id}).encode()).hexdigest()
        self.ledger.receipt(account=claim.account_id, task=claim.request_id, provider='litellm',
                            request='litellm-' + claim.request_id, amount_microusd=int(amount),
                            observed_epoch=int(self.clock()), price_version=version, payload_hash=digest)

    def _close(self, claim, state, public_result, gateway=None, before=None):
        # Usage must reconcile before the global slot hands over (queue.finish rechecks).
        if gateway is not None:
            self._reconcile_usage(gateway, claim, before)
        self.ledger.settle(account=claim.account_id, task=claim.request_id,
                           effects_quiesced=True, all_routes_reconciled=True)
        with self.coordinator.transaction() as con:
            con.execute('UPDATE tasks SET state=? WHERE account_id=? AND id=?', (state, claim.account_id, claim.request_id))
            self.coordinator._audit(con, claim.account_id, 'worker', claim.request_id, 'chat.' + state, 'completed')
        return RequestReceipt(claim.account_id, claim.request_id, claim.fence, state, public_result[:MAX_TRANSCRIPT_CHARS], True)

    def _last_agent_message(self, con, account_id, conversation_id):
        row = con.execute("""SELECT content FROM chat_messages WHERE account_id=? AND conversation_id=? AND provenance='agent'
            ORDER BY id DESC LIMIT 1""", (account_id, conversation_id)).fetchone()
        return row[0] if row else None

    def execute(self, claim: RequestClaim):
        if claim.conversation_id is None:
            raise ValueError('chat driver requires a conversation binding')
        gateway = self.gateway_factory(claim)
        caps = gateway.capabilities()
        for operation in ('send', 'history'):
            if not getattr(caps, operation):
                raise CapabilityUnavailable('gateway probe did not verify ' + operation)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, Principal(claim.account_id, claim.actor_id, 'customer'))
            reservation = con.execute('SELECT state FROM task_reservations WHERE account_id=? AND task_id=?',
                                      (claim.account_id, claim.request_id)).fetchone()
            if not reservation or reservation['state'] != 'active':
                raise Conflict('task not admitted')
            task = con.execute('SELECT state FROM tasks WHERE account_id=? AND id=?',
                               (claim.account_id, claim.request_id)).fetchone()
            if not task or task[0] not in ('queued', 'running'):
                raise Conflict('task not dispatchable')
            conversation = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?',
                                       (claim.account_id, claim.conversation_id)).fetchone()
            if conversation is None:
                raise Conflict('claim conversation missing')
            session = conversation[0]
            pre_cancelled = bool(con.execute('SELECT cancel_requested FROM customer_requests WHERE account_id=? AND id=?',
                                             (claim.account_id, claim.request_id)).fetchone()[0])
            if pre_cancelled:
                attempt, _operation_id = self._start_delivery(con, claim)
                self._set_delivery(con, claim, attempt, 'aborted')
            else:
                con.execute("UPDATE tasks SET state='running' WHERE account_id=? AND id=?", (claim.account_id, claim.request_id))
                attempt, operation_id = self._start_delivery(con, claim)
        if pre_cancelled:
            # Aborted before any native effect; recorded, settled, no retry.
            return self._close(claim, 'cancelled', 'Cancelled before execution')
        self._emit(claim, 'task_started', {'summary': 'Dispatched to the isolated runtime.'})
        before = self._usage_before(gateway)
        if before is not None:
            with self.coordinator.transaction() as con:
                con.execute('UPDATE chat_deliveries SET usage_before_microusd=? WHERE account_id=? AND request_id=? AND attempt=?',
                            (before, claim.account_id, claim.request_id, attempt))
        try:
            if session is None:
                session, _run_started, _run_error = gateway.open_session(operation_id, 'chat-' + claim.request_id[:16])
                with self.coordinator.transaction() as con:
                    con.execute('UPDATE conversations SET native_session_ref=? WHERE account_id=? AND id=?',
                                (session, claim.account_id, claim.conversation_id))
            ack = gateway.send(session, operation_id, claim.message)
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, attempt, 'acknowledged', run_id=ack['run_id'], ack_seq=ack['message_seq'])
            self._emit(claim, 'progress', {'summary': 'Runtime accepted the request.'}, 'gateway')
        except Exception:
            # The native outcome is unknown; reconcile by receipts, never resend.
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, attempt, 'uncertain')
            raise
        cursor = None
        deadline = self.clock() + self.run_timeout
        new_agent_rows = idle_reads = pages = 0
        timed_out = False
        while True:
            with self.coordinator.transaction() as con:
                cancelled = bool(con.execute('SELECT cancel_requested FROM customer_requests WHERE account_id=? AND id=?',
                                             (claim.account_id, claim.request_id)).fetchone()[0])
            if cancelled:
                caps2 = gateway.capabilities()
                if not caps2.abort:
                    raise CapabilityUnavailable('native abort unsupported; cancellation intent stays recorded')
                gateway.abort(session, ack['run_id'])
                with self.coordinator.transaction() as con:
                    self._set_delivery(con, claim, attempt, 'aborted', run_id=ack['run_id'])
                self._emit(claim, 'progress', {'summary': 'Cancellation confirmed by the runtime.'}, 'gateway')
                return self._close(claim, 'cancelled', 'Cancelled during execution', gateway, before)
            if self.heartbeat is not None:
                self.heartbeat(claim)
            page = gateway.history(session, cursor)
            pages += 1
            if page['kind'] == 'reset':
                cursor = None
                continue
            with self.coordinator.transaction() as con:
                new_agent_rows += self._absorb(con, claim, page['messages'])
            if page['messages']:
                self._emit(claim, 'progress', {'summary': f'{len(page["messages"])} transcript update(s) recorded.'},
                           'gateway')
            if page['cursor']:
                cursor = page['cursor']
                continue
            # A run is over only after it has produced an agent reply and the runtime reports idle twice in a row
            # (the reply row can land just before the active flag clears).
            idle_reads = idle_reads + 1 if (not page['active_run'] and new_agent_rows) else 0
            if idle_reads >= SETTLE_POLLS:
                break
            if self.clock() >= deadline:
                timed_out = True
                break
            self.sleep(self.poll_interval)
        if timed_out:
            try:
                gateway.abort(session, ack['run_id'])
            except Exception:
                pass
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, attempt, 'aborted', run_id=ack['run_id'])
            self._emit(claim, 'progress', {'summary': 'The run took too long and was stopped.'}, 'gateway')
            return self._close(claim, 'failed', 'The assistant took too long and was stopped. Please try a smaller request.', gateway, before)
        with self.store.connect() as con:
            last = self._last_agent_message(con, claim.account_id, claim.conversation_id)
        public = last if last else 'Completed without an agent transcript row; reconcile history before relying on this result.'
        self._emit(claim, 'result', {'summary': public[:500]})
        return self._close(claim, 'completed', public, gateway, before)

    def abandon(self, claim: RequestClaim):
        """Last resort for a request whose runtime cannot be reached for a long time: fail it and charge the reserved upper bound."""
        with self.store.connect() as con:
            row = con.execute('SELECT attempt FROM chat_deliveries WHERE account_id=? AND request_id=? ORDER BY attempt DESC LIMIT 1',
                              (claim.account_id, claim.request_id)).fetchone()
        if row is not None:
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, row['attempt'], 'aborted')
        self._emit(claim, 'progress', {'summary': 'The runtime could not be reached; the request was stopped.'}, 'reconciler')

        class _Blind:
            def usage_snapshot(self): raise RuntimeError('runtime unreachable')
        return self._close(claim, 'failed', 'The assistant could not be reached for this request, so it was stopped. Please try again.', _Blind(), None)

    def reconcile(self, claim: RequestClaim):
        if claim.conversation_id is None:
            raise ValueError('chat driver requires a conversation binding')
        with self.store.connect() as con:
            row = con.execute('''SELECT attempt,state,native_run_id,usage_before_microusd FROM chat_deliveries WHERE account_id=? AND request_id=?
                ORDER BY attempt DESC LIMIT 1''', (claim.account_id, claim.request_id)).fetchone()
            session_row = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?',
                                      (claim.account_id, claim.conversation_id)).fetchone()
        if row is None or not session_row or not session_row[0]:
            # No message was ever handed to a runtime session: nothing ran, nothing was spent.
            if row is not None:
                with self.coordinator.transaction() as con:
                    self._set_delivery(con, claim, row['attempt'], 'aborted')
            return self._close(claim, 'failed', 'Your request could not be started. Nothing was charged. Please send it again.')
        attempt, state, run_id = row['attempt'], row['state'], row['native_run_id']
        if state not in ('acknowledged', 'uncertain'):
            return None
        gateway = self.gateway_factory(claim)
        try:
            page = gateway.history(session_row[0], None)
        except CapabilityUnavailable:
            return None
        if page['kind'] != 'tail' or page['cursor'] or page['active_run']:
            return None
        with self.coordinator.transaction() as con:
            self._absorb(con, claim, page['messages'])
            if state != 'acknowledged':
                self._set_delivery(con, claim, attempt, 'acknowledged', run_id=run_id)
            last = self._last_agent_message(con, claim.account_id, claim.conversation_id)
        public = last if last else 'Reconciled without an agent transcript row.'
        self._emit(claim, 'result', {'summary': public[:500]}, 'reconciler')
        return self._close(claim, 'completed', public, gateway, row['usage_before_microusd'])


def synthetic_gateway_factory(gateway: SyntheticGateway):
    def factory(claim):
        return gateway
    return factory
