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
from .genui import intent as gen_intent, prompts as gen_prompts, schema as gen_schema
from .genui.runtime import GenUiRuntime
from .genui.store import BlockStore
from .genui.runner import PlanRunner
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .request_queue import RequestQueue, RequestClaim, RequestReceipt
from .security import NotFound, Principal

MAX_CONVERSATIONS_PER_PROJECT = 100   # chat-style use: many conversations; clearing (archiving) one frees a slot
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
                 clock=time.time, max_conversations_per_project=MAX_CONVERSATIONS_PER_PROJECT, execution=False, browse=False):
        self.browse = bool(browse)   # owner switch browse_tasks: the browser agent may be chosen for interactive goals
        self.execution = bool(execution)   # owner switch state, shown to the customer UI
        self.store = store
        self.queue = queue
        self.ledger = ledger
        self.pricer = pricer
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)
        self.blocks = BlockStore(store, clock=clock)
        self.runner = PlanRunner(self, clock=clock)
        self.max_conversations_per_project = max_conversations_per_project

    def create_conversation(self, principal: Principal, project_id: str):
        identifier(project_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?', (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            count = con.execute('SELECT count(*) FROM conversations WHERE account_id=? AND project_id=? AND archived_epoch IS NULL',
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
            sql = '''SELECT c.id,c.project_id,c.created_at,
                coalesce(c.title,(SELECT substr(m.content,1,90) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id
                    AND m.provenance IN ('customer','telegram') ORDER BY m.id LIMIT 1)) AS title,
                (SELECT max(m.created_at) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id) AS last_activity,
                (SELECT count(*) FROM customer_requests r WHERE r.account_id=c.account_id AND r.conversation_id=c.id
                    AND r.state IN ('waiting','starting','running','uncertain')) AS active
                FROM conversations c WHERE c.account_id=? AND c.archived_epoch IS NULL'''
            args: list = [principal.account_id]
            if project_id is not None:
                identifier(project_id)
                sql += ' AND c.project_id=?'
                args.append(project_id)
            return [dict(row) for row in con.execute(sql + ' ORDER BY c.created_at,c.id LIMIT 500', args).fetchall()]

    def archive_conversation(self, principal: Principal, conversation_id: str):
        """Hide a conversation (history, tasks and ledger rows stay). Idempotent."""
        identifier(conversation_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM conversations WHERE account_id=? AND id=?', (principal.account_id, conversation_id)).fetchone():
                raise NotFound('unavailable')
            con.execute('UPDATE conversations SET archived_epoch=coalesce(archived_epoch,?) WHERE account_id=? AND id=?',
                        (int(self.clock()), principal.account_id, conversation_id))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, conversation_id, 'chat.conversation_archive', 'completed')
            return {'id': conversation_id, 'archived': True}

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

    def _admit(self, principal, result, conversation_id, key, message_for_cost):
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT project_id FROM customer_requests WHERE account_id=? AND id=?',
                              (principal.account_id, result['id'])).fetchone()
            if not row:
                raise NotFound('unavailable')
            project_id = row['project_id']
        try:
            amount, price_version = self.pricer.reservation(message_for_cost)
        except CapabilityUnavailable:
            return None, None, project_id
        try:
            self.ledger.admit(principal, task=result['id'], project=project_id, conversation=conversation_id,
                              key=key, amount_microusd=amount, upper_bound_verified=True)
        except Exception:
            self.queue.cancel(principal, result['id'])
            raise
        return amount, price_version, project_id

    def _local_form(self, principal, conversation_id, message, key, template):
        """A requirements form needs no model call: record the customer's message and attach the template. Idempotent by key."""
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            existing = con.execute('SELECT id FROM ui_blocks WHERE account_id=? AND idempotency_key=?', (principal.account_id, 'form-' + key)).fetchone()
            if not existing:
                cur = con.execute('''INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,NULL,'customer',?)''',
                                  (principal.account_id, conversation_id, message))
                block = self.blocks.create_form(principal.account_id, conversation_id, template, key='form-' + key, anchor_message_id=cur.lastrowid, con=con)
                self.coordinator._audit(con, principal.account_id, principal.actor_id, block['id'], 'chat.form_created', 'completed')
            else:
                block = self.blocks.get(principal, existing['id'], con)
        return {'id': None, 'state': 'completed', 'response_type': 'interactive', 'block': block, 'conversation_id': conversation_id,
                'execution_enabled': self.execution, 'admission': 'none', 'price_version': None}

    def send(self, principal: Principal, *, conversation_id: str, message: str, key: str,
             provenance: str = 'customer', mode: str = 'auto'):
        """One actionable request per send; admission via Phase 5 before any
        native effect. A repeat with the same key never starts a second task."""
        identifier(key)
        if not isinstance(message, str) or not message.strip() or len(message) > 16000 or '\x00' in message:
            raise ValueError('invalid message')
        if mode not in ('auto', 'text', 'plan', 'browse'):
            raise ValueError('invalid mode')
        self.conversation(principal, conversation_id)
        kind = gen_intent.detect(message, mode=mode, browse=self.browse) if provenance == 'customer' else 'text'
        if kind == 'requirements':
            template = gen_intent.requirements_template(message)
            if template:
                return self._local_form(principal, conversation_id, message, key, template)
            kind = 'plan'
        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id,
                                   intent=kind if kind in ('plan', 'browse') else 'chat')
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
                    'admission': 'route_unconfigured', 'price_version': None, 'response_type': kind if kind in ('plan', 'browse') else 'text'}
        try:
            self.ledger.admit(principal, task=result['id'], project=project_id, conversation=conversation_id,
                              key=key, amount_microusd=amount, upper_bound_verified=True)
        except Exception:
            # Whatever stopped admission (budget, mismatch, storage), the request must not stay queued without a reservation:
            # it would be claimed and wedge the serial slot.
            self.queue.cancel(principal, result['id'])
            raise
        return {**result, 'conversation_id': conversation_id, 'execution_enabled': True,
                'admission': 'reserved', 'price_version': price_version, 'response_type': kind if kind in ('plan', 'browse') else 'text'}

    # -- generative UI operations (the only things a block button can do) -------------------------------------------
    def _spawn(self, principal, conversation_id, *, message, key, intent, context, shown):
        """Queue a request created by a block action, show `shown` as the customer's turn, and admit it like any send."""
        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id, intent=intent, context=context)
        with self.coordinator.transaction() as con:
            if not con.execute('SELECT 1 FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance=\'customer\'',
                               (principal.account_id, conversation_id, result['id'])).fetchone():
                con.execute('INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,\'customer\',?)',
                            (principal.account_id, conversation_id, result['id'], shown[:16000]))
        amount, price_version, _project = self._admit(principal, result, conversation_id, key, message)
        return {**result, 'conversation_id': conversation_id, 'execution_enabled': amount is not None,
                'admission': 'reserved' if amount is not None else 'route_unconfigured'}

    def submit_block(self, principal: Principal, block_id: str, version: int):
        """Submit a requirements form: validates answers, then asks the runtime for a plan using them. Idempotent per version."""
        block = self.blocks.get(principal, block_id)
        if block['kind'] != 'form':
            raise Conflict('only a form can be submitted')
        if block['status'] == 'submitted':
            with self.store.connect() as con:
                prior = con.execute('SELECT id FROM customer_requests WHERE account_id=? AND idempotency_key=?',
                                    (principal.account_id, f'plan-{block_id}-{version}')).fetchone()
            if prior:   # a repeat of the same submission (double click, retry): the same request, nothing new
                return {'request': self.queue.get(principal, prior['id']), 'block': block}
        if block['version'] != version or block['status'] != 'draft':
            raise Conflict('version conflict')
        answers = gen_schema.validate_answers(block['spec'], block['state'].get('answers', {}), final=True)
        with self.store.connect() as con:
            anchor = con.execute('SELECT content FROM chat_messages WHERE account_id=? AND id=?', (principal.account_id, block['anchor_message_id'])).fetchone()
        original = anchor['content'] if anchor else block['spec']['title']
        summary = '; '.join(f'{f["label"]}: {answers[f["id"]]}' for f in gen_schema.visible_fields(block['spec'], answers) if f['id'] in answers and answers[f['id']] != '')
        result = self._spawn(principal, block['conversation_id'], message=original, key=f'plan-{block_id}-{version}', intent='plan',
                             context={'block': block_id, 'answers': answers}, shown='Requirements submitted. ' + summary)
        with self.blocks.coordinator.transaction() as con:
            if block['status'] == 'draft':
                self.blocks.set_status(con, principal.account_id, block_id, 'submitted', request_id=result['id'])
        return {'request': result, 'block': self.blocks.get(principal, block_id)}

    def launch_plan(self, principal: Principal, block_id: str, version: int):
        """Approve and run a plan. The exact approved revision is stored; the runtime executes that revision and nothing else."""
        block = self.blocks.get(principal, block_id)
        if block['kind'] != 'task_plan':
            raise Conflict('only a plan can be launched')
        if block['version'] != version:
            raise Conflict('version conflict')
        if block['status'] == 'launched':
            return {'request': self.queue.get(principal, block['launched_request_id']) if block['launched_request_id'] else None, 'block': block}
        if block['status'] != 'draft':
            raise Conflict('this plan can no longer be launched')
        plan = gen_schema.validate_plan(block['state']['plan'], launch=True)
        revision = block['state']['revision'] + 1
        with self.blocks.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            fresh = con.execute('SELECT status,version FROM ui_blocks WHERE account_id=? AND id=?', (principal.account_id, block_id)).fetchone()
            if fresh['status'] != 'draft':
                raise Conflict('this plan can no longer be launched')
            con.execute('INSERT OR IGNORE INTO plan_revisions VALUES (?,?,?,?,?,?)',
                        (principal.account_id, block_id, revision, 'approved', __import__('json').dumps(plan), int(self.clock())))
            state = dict(block['state']); state['revision'] = revision
            con.execute('UPDATE ui_blocks SET state_json=?,actor_id=? WHERE account_id=? AND id=?', (__import__('json').dumps(state), principal.actor_id, principal.account_id, block_id))
            self.runner.start(con, principal.account_id, block_id, plan)
            self.blocks.set_status(con, principal.account_id, block_id, 'launched')
            self.coordinator._audit(con, principal.account_id, principal.actor_id, block_id, 'chat.plan_launch', 'completed')
        with self.coordinator.transaction() as con:
            con.execute('INSERT OR IGNORE INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,NULL,\'customer\',?)',
                        (principal.account_id, block['conversation_id'],
                         'Launched the plan "' + plan['title'] + '" with ' + str(sum(1 for p in plan['phases'] if p['enabled'])) + ' phases. Approval-gated phases will ask first.'))
        first = self.runner.advance(principal.account_id, block_id)
        return {'request': self.queue.get(principal, first) if first else None, 'block': self.blocks.get(principal, block_id)}

    def rename_conversation(self, principal: Principal, conversation_id: str, title: str):
        identifier(conversation_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 90 or '\x00' in title:
            raise ValueError('invalid title')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('UPDATE conversations SET title=? WHERE account_id=? AND id=?', (title.strip(), principal.account_id, conversation_id)).rowcount:
                raise NotFound('unavailable')
        return {'id': conversation_id, 'title': title.strip()}

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
                 events: EventService | None = None, sleep=None, poll_interval=1.5, run_timeout=900, usage_wait=45, heartbeat=None, genui=None, browse_factory=None):
        self.browse_factory = browse_factory   # callable(account_id) -> BrowseRpc; None = browse requests are refused
        self.genui = genui   # GenUiRuntime: plan/execute prompts and plan-reply handling; None keeps plain chat behaviour
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
                    AND request_id=? AND provenance='customer' AND native_message_id IS NULL
                    AND NOT EXISTS (SELECT 1 FROM chat_messages o WHERE o.account_id=? AND o.conversation_id=? AND o.native_message_id=?)''',
                    (native_id, claim.account_id, claim.conversation_id, claim.request_id, claim.account_id, claim.conversation_id, native_id))
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
        with self.store.connect() as con:
            funded = con.execute('SELECT 1 FROM task_reservations WHERE account_id=? AND task_id=?', (claim.account_id, claim.request_id)).fetchone()
        if funded:   # a request that never got a reservation has nothing to reconcile or settle
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
        if not (self.genui and self.genui.request_info(claim)[0] == 'browse'):      # browser tasks do not use the assistant's cell
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
            is_browse = bool(self.genui and self.genui.request_info(claim)[0] == 'browse')
            if is_browse and not pre_cancelled:
                con.execute("UPDATE tasks SET state='running' WHERE account_id=? AND id=?", (claim.account_id, claim.request_id))
            elif pre_cancelled:
                attempt, _operation_id = self._start_delivery(con, claim)
                self._set_delivery(con, claim, attempt, 'aborted')
            if pre_cancelled:
                attempt, _operation_id = self._start_delivery(con, claim)
                self._set_delivery(con, claim, attempt, 'aborted')
            elif not is_browse:
                con.execute("UPDATE tasks SET state='running' WHERE account_id=? AND id=?", (claim.account_id, claim.request_id))
                attempt, operation_id = self._start_delivery(con, claim)
        if pre_cancelled:
            # Aborted before any native effect; recorded, settled, no retry.
            return self._close(claim, 'cancelled', 'Cancelled before execution')
        if is_browse:
            return self._execute_browse(claim, gateway)
        self._emit(claim, 'task_started', {'summary': 'Dispatched to the isolated runtime.'})
        intent, context = self.genui.request_info(claim) if self.genui else ('chat', {})
        outgoing = self.genui.outgoing(claim, intent, context) if self.genui else claim.message
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
            ack = gateway.send(session, operation_id, outgoing)
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, attempt, 'acknowledged', run_id=ack['run_id'], ack_seq=ack['message_seq'])
            self._emit(claim, 'progress', {'summary': 'Runtime accepted the request.'}, 'gateway')
        except Exception:
            # The native outcome is unknown; reconcile by receipts, never resend.
            with self.coordinator.transaction() as con:
                self._set_delivery(con, claim, attempt, 'uncertain')
            raise
        poll = {'cursor': None, 'new_agent_rows': 0, 'idle_reads': 0}
        outcome = self._poll(claim, gateway, session, ack, attempt, before, poll)
        if isinstance(outcome, RequestReceipt):
            return outcome
        if intent == 'plan' and self.genui is not None and outcome == 'done':
            with self.store.connect() as con:
                reply = self._last_agent_message(con, claim.account_id, claim.conversation_id) or ''
            plan, reason = self.genui.validate_reply(reply)
            if plan is None:
                # One bounded repair attempt in the same session; a second failure falls back to the plain reply.
                self._emit(claim, 'progress', {'summary': 'The plan needs a correction; asking once more.'}, 'gateway')
                repair_op = uuid.uuid4().hex
                ack = gateway.send(session, repair_op, gen_prompts.repair_prompt(reason))
                poll['new_agent_rows'] = poll['idle_reads'] = 0
                outcome = self._poll(claim, gateway, session, ack, attempt, before, poll)
                if isinstance(outcome, RequestReceipt):
                    return outcome
                with self.store.connect() as con:
                    reply = self._last_agent_message(con, claim.account_id, claim.conversation_id) or ''
                plan, reason = self.genui.validate_reply(reply)
            if plan is not None:
                self.genui.attach_plan(claim, context, plan)
                self._emit(claim, 'progress', {'summary': 'Plan drafted and ready to edit.'}, 'gateway')
            else:
                self._emit(claim, 'progress', {'summary': 'The reply could not be shown as a plan; showing it as text.'}, 'gateway')
        with self.store.connect() as con:
            last = self._last_agent_message(con, claim.account_id, claim.conversation_id)
        public = last if last else 'Completed without an agent transcript row; reconcile history before relying on this result.'
        self._emit(claim, 'result', {'summary': public[:500]})
        return self._close(claim, 'completed', public, gateway, before)

    def _execute_browse(self, claim, gateway):
        """Run a browser job on the host browse service and mirror its steps into the task timeline and browse_steps.

        The assistant's cell is not involved. Money: the run's model calls spend on the account's own key, reconciled exactly
        like a chat turn (spend delta). A hand-off at a payment step completes the request; the takeover window continues
        in the service and is read through the browse endpoints.
        """
        if self.browse_factory is None:
            return self._close(claim, 'failed', 'Browsing is not available right now. Nothing was charged.')
        rpc = self.browse_factory(claim.account_id)
        before = self._usage_before(gateway)
        with self.store.connect() as con:
            reserved = con.execute('SELECT amount_microusd FROM task_reservations WHERE account_id=? AND task_id=?', (claim.account_id, claim.request_id)).fetchone()
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            con.execute('INSERT OR IGNORE INTO browse_runs(account_id,request_id,goal,status,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?)',
                        (claim.account_id, claim.request_id, claim.message, 'queued', now, now))
        self._emit(claim, 'task_started', {'summary': 'Opening a browser for this task.'})
        rpc('start', request_id=claim.request_id, goal=claim.message, max_cost_microusd=int(reserved[0]) if reserved else 1_000_000)
        since, deadline, final = 0, self.clock() + self.run_timeout, None
        finals = ('done', 'handoff', 'stopped', 'blocked', 'budget', 'error', 'cancelled', 'stuck', 'max_steps', 'deadline')
        while True:
            with self.coordinator.transaction() as con:
                cancelled = bool(con.execute('SELECT cancel_requested FROM customer_requests WHERE account_id=? AND id=?', (claim.account_id, claim.request_id)).fetchone()[0])
            if cancelled:
                try:
                    rpc('cancel', request_id=claim.request_id)
                except Exception:
                    pass
            if self.heartbeat is not None:
                self.heartbeat(claim)
            try:
                polled = rpc('poll', request_id=claim.request_id, since=since)
            except CapabilityUnavailable:
                polled = None
            if polled is not None:
                self._mirror_browse(claim, polled)
                for e in polled['events']:
                    since = max(since, e['n'])
                    summary = self._browse_summary(e)
                    if summary:
                        self._emit(claim, 'progress', {'summary': summary}, 'browser')
                if polled['state'] in finals:
                    final = polled
                    break
            if self.clock() >= deadline:
                try:
                    rpc('cancel', request_id=claim.request_id)
                except Exception:
                    pass
                return self._close(claim, 'failed', 'The browser task took too long and was stopped.', gateway, before)
            self.sleep(self.poll_interval)
        status = final['state']
        if status == 'cancelled':
            return self._close(claim, 'cancelled', 'Cancelled during browsing', gateway, before)
        text = self._browse_message(final)
        with self.coordinator.transaction() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,'agent',?)",
                        (claim.account_id, claim.conversation_id, claim.request_id, text[:MAX_TRANSCRIPT_CHARS]))
        self._emit(claim, 'result', {'summary': text[:500]})
        return self._close(claim, 'completed' if status in ('done', 'handoff') else 'failed', text, gateway, before)

    @staticmethod
    def _browse_summary(e):
        if e['kind'] == 'opened':
            return f'Opened {e.get("url", "")}'
        if e['kind'] == 'step':
            who = {'jev': 'JEV', 'haiku': 'Haiku', 'sonnet': 'Sonnet'}.get(e.get('by'), e.get('by', ''))
            verb = {'click': 'Clicked', 'type': 'Typed into', 'select': 'Chose in', 'press': 'Pressed', 'scroll': 'Scrolled', 'back': 'Went back'}.get(e.get('action'), e.get('action', ''))
            tail = '' if e.get('result') == 'ok' else f' (failed: {e.get("result")})'
            label = f' “{e.get("label")}”' if e.get('label') else ''
            return f'{verb}{label} · {who}{tail}'
        return None

    @staticmethod
    def _browse_message(final):
        status, reason, answer = final['state'], final.get('reason') or '', final.get('answer') or ''
        if status == 'done':
            return answer or 'Done.'
        if status == 'handoff':
            where = f' I stopped at {final.get("url")}.' if final.get('url') else ''
            return ('I got as far as I safely can: ' + (reason or 'the next step needs you') + '.' + where +
                    ' Open the Browser page to see the screen and take over; nothing was purchased or submitted.')
        notes = {'blocked': 'I did not open that site because it is not allowed.', 'budget': 'I stopped because the spending limit for this task was reached.',
                 'stuck': 'I got stuck repeating the same step and stopped.', 'deadline': 'I ran out of time.', 'max_steps': 'I reached the step limit.',
                 'error': 'The browser run failed.', 'stopped': 'I could not complete this.'}
        return (notes.get(status, 'The browser run ended.') + (f' ({reason})' if reason else '')).strip()

    def _mirror_browse(self, claim, polled):
        now = int(self.clock())
        jev = polled.get('jev') or {}
        with self.coordinator.transaction() as con:
            con.execute('''UPDATE browse_runs SET status=?,url=?,answer=?,reason=?,pending_json=?,jev_asked=?,jev_agree=?,estimated_cost_microusd=?,updated_epoch=?,
                takeover_until=CASE WHEN ? THEN ? ELSE takeover_until END WHERE account_id=? AND request_id=?''',
                        (polled['state'], polled.get('url'), polled.get('answer'), polled.get('reason'),
                         json.dumps(polled['pending_action']) if polled.get('pending_action') else None, jev.get('jev_asked', 0), jev.get('jev_agree', 0),
                         int(polled.get('cost_microusd') or 0), now, 1 if polled.get('takeover') else 0, now + 600, claim.account_id, claim.request_id))
            for e in polled['events']:
                con.execute('INSERT OR IGNORE INTO browse_steps(account_id,request_id,n,kind,data_json,created_epoch) VALUES (?,?,?,?,?,?)',
                            (claim.account_id, claim.request_id, e['n'], e['kind'], json.dumps({k: v for k, v in e.items() if k not in ('n', 'kind')}), now))

    def _poll(self, claim, gateway, session, ack, attempt, before, poll):
        """Wait for the run to finish. Returns 'done', or a RequestReceipt when the request was closed (cancel or timeout)."""
        deadline = self.clock() + self.run_timeout
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
            page = gateway.history(session, poll['cursor'])
            if page['kind'] == 'reset':
                poll['cursor'] = None
                continue
            with self.coordinator.transaction() as con:
                poll['new_agent_rows'] += self._absorb(con, claim, page['messages'])
            if page['messages']:
                self._emit(claim, 'progress', {'summary': f'{len(page["messages"])} transcript update(s) recorded.'}, 'gateway')
            if page['cursor']:
                poll['cursor'] = page['cursor']
                continue
            # A run is over only after it has produced an agent reply and the runtime reports idle twice in a row
            # (the reply row can land just before the active flag clears).
            poll['idle_reads'] = poll['idle_reads'] + 1 if (not page['active_run'] and poll['new_agent_rows']) else 0
            if poll['idle_reads'] >= SETTLE_POLLS:
                return 'done'
            if self.clock() >= deadline:
                try:
                    gateway.abort(session, ack['run_id'])
                except Exception:
                    pass
                with self.coordinator.transaction() as con:
                    self._set_delivery(con, claim, attempt, 'aborted', run_id=ack['run_id'])
                self._emit(claim, 'progress', {'summary': 'The run took too long and was stopped.'}, 'gateway')
                return self._close(claim, 'failed', 'The assistant took too long and was stopped. Please try a smaller request.', gateway, before)
            self.sleep(self.poll_interval)

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
        if self.genui is not None and self.genui.request_info(claim)[0] == 'browse':
            # A browse run interrupted by a crash: the browser job is bounded and stops by itself; settle at the reserved upper bound.
            if self.browse_factory is not None:
                try:
                    self.browse_factory(claim.account_id)('cancel', request_id=claim.request_id)
                except Exception:
                    pass
            return self._close(claim, 'failed', 'The browser task was interrupted and stopped. Please try again.', self.gateway_factory(claim), None)
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
