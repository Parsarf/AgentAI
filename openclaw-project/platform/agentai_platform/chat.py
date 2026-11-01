"""Customer chat: conversations, admission-gated sends and the native run that serves them.

The customer surface owns projects/conversations/transcript metadata, admission (queue, budget, the one running slot) and the verdict shown to the customer. The
run itself is OpenClaw's: ChatService admits a message and, while a run is going, can steer it; ChatDriver (chat_driver.py) hands the message to the runtime, asks the
runtime when the run ended and settles it. Nothing here reads the assistant's prose for commands. Transcript authority: durable app rows map access; the native
session is authoritative for execution and its replies are attributed to a request by native run id, never by position.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from .adapters import CapabilityUnavailable
from .budget import OWN_KEY_AMOUNT, BudgetDenied, BudgetLedger
from .events import EventService
from . import safety
from .genui import document as gen_document, prompts as gen_prompts, schema as gen_schema
from .genui.runtime import GenUiRuntime
from .genui.store import BlockStore
from .genui.runner import PlanRunner
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .request_queue import RequestQueue
from .security import NotFound, Principal

MAX_CONVERSATIONS_PER_PROJECT = 100   # chat-style use: many conversations; clearing (archiving) one frees a slot
MAX_PROJECTS = 10  # product/plan.json max_projects; the numeric source of truth
MAX_TRANSCRIPT_CHARS = 16000

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


OWN_KEY_PRICE_VERSION = 'own-key-v1'       # an own-key task reserves OWN_KEY_AMOUNT, one micro-dollar (no limit is checked on the customer's model)


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
                 clock=time.time, max_conversations_per_project=MAX_CONVERSATIONS_PER_PROJECT, execution=False, browse=False, events=None, gateway_factory=None, unmetered=None):
        self.unmetered = unmetered or (lambda account_id: False)   # callable(account_id) -> True when the account runs on its own model key: Lumina's spending limits do not apply
        self.events = events   # EventService: the timeline starts the moment a message is received, not when a worker picks it up
        self.browse = bool(browse)   # owner switch browse_tasks: Browse mode and the browser tool are offered
        self.gateway_factory = gateway_factory   # callable(account_id) -> gateway: lets a message join a running task (steering) and a goal be resumed or cleared; None = always queue
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
            if count >= self.max_conversations_per_project and safety.is_on(con, principal.account_id, 'project_chat_limits'):
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

    def conversations(self, principal: Principal, project_id: str | None = None, *, query: str = '', archived: bool = False, limit: int = 500, offset: int = 0):
        if not isinstance(query, str) or len(query) > 200 or type(archived) is not bool or type(limit) is not int or not 1 <= limit <= 501 or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError('invalid pagination')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            sql = """SELECT c.id,c.project_id,c.created_at,c.archived_epoch,
                coalesce(c.title,(SELECT substr(m.content,1,90) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id
                    AND m.provenance IN ('customer','telegram') ORDER BY m.id LIMIT 1)) AS title,
                (SELECT max(m.created_at) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id) AS last_activity,
                (SELECT substr(m.content,1,240) FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS preview,
                (SELECT count(*) FROM customer_requests r WHERE r.account_id=c.account_id AND r.conversation_id=c.id
                    AND r.state IN ('waiting','starting','running','uncertain')) AS active
                FROM conversations c WHERE c.account_id=?"""
            args: list = [principal.account_id]
            sql += ' AND c.archived_epoch IS ' + ('NOT NULL' if archived else 'NULL')
            if project_id is not None:
                identifier(project_id)
                sql += ' AND c.project_id=?'
                args.append(project_id)
            if query.strip():
                sql += " AND (instr(lower(coalesce(c.title,'')),lower(?))>0 OR EXISTS (SELECT 1 FROM chat_messages m WHERE m.account_id=c.account_id AND m.conversation_id=c.id AND instr(lower(m.content),lower(?))>0))"
                args.extend([query.strip(), query.strip()])
            args.extend([limit, offset])
            return [dict(row) for row in con.execute(sql + ' ORDER BY coalesce(last_activity,c.created_at) DESC,c.id DESC LIMIT ? OFFSET ?', args).fetchall()]

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

    def restore_conversation(self, principal: Principal, conversation_id: str):
        identifier(conversation_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT project_id,archived_epoch FROM conversations WHERE account_id=? AND id=?', (principal.account_id, conversation_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['archived_epoch'] is not None:
                count = con.execute('SELECT count(*) FROM conversations WHERE account_id=? AND project_id=? AND archived_epoch IS NULL', (principal.account_id, row['project_id'])).fetchone()[0]
                if count >= self.max_conversations_per_project and safety.is_on(con, principal.account_id, 'project_chat_limits'):
                    raise Conflict('conversation limit reached')
                con.execute('UPDATE conversations SET archived_epoch=NULL WHERE account_id=? AND id=?', (principal.account_id, conversation_id))
                self.coordinator._audit(con, principal.account_id, principal.actor_id, conversation_id, 'chat.conversation_restore', 'completed')
            return {'id': conversation_id, 'archived': False}

    def conversation(self, principal: Principal, conversation_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT id,project_id,created_at,title,archived_epoch FROM conversations WHERE account_id=? AND id=?',
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
            if count >= MAX_PROJECTS and safety.is_on(con, principal.account_id, 'project_chat_limits'):
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
        with self.store.connect() as con:
            budget_on = safety.is_on(con, principal.account_id, 'budget_caps')
        if not budget_on:                       # the account's own `budget_caps` safety switch: no reservation, same path as an unpriced route
            return None, None, project_id
        own = self.unmetered(principal.account_id)
        try:
            amount, price_version = (OWN_KEY_AMOUNT, OWN_KEY_PRICE_VERSION) if own else self.pricer.reservation(message_for_cost)
        except CapabilityUnavailable:
            return None, None, project_id
        try:
            self.ledger.admit(principal, task=result['id'], project=project_id, conversation=conversation_id,
                              key=key, amount_microusd=amount, upper_bound_verified=True, unmetered=own)
        except Exception:
            self.queue.cancel(principal, result['id'])
            raise
        return amount, price_version, project_id

    def send(self, principal: Principal, *, conversation_id: str, message: str, key: str,
             provenance: str = 'customer', mode: str = 'auto', goal: bool = False, ui: str = 'basic', ui_event: dict | None = None):
        """One actionable request per send; admission via Phase 5 before any native effect. A repeat with the same key never starts a second task.

        While a task of this conversation is still running, a plain message joins that run as a steer (the runtime's own steering) instead of waiting behind it.
        `goal` (Keep working until complete) starts a session goal with this message as its objective; plan mode never takes one."""
        identifier(key)
        if not isinstance(message, str) or not message.strip() or len(message) > 16000 or '\x00' in message:
            raise ValueError('invalid message')
        if mode not in ('auto', 'text', 'plan', 'browse'):
            raise ValueError('invalid mode')
        if ui not in gen_document.TIERS:
            raise ValueError('invalid answer style')
        if type(goal) is not bool or (goal and (mode == 'plan' or provenance != 'customer')):
            raise ValueError('invalid goal')
        if self.conversation(principal, conversation_id)['archived_epoch'] is not None:
            raise Conflict('restore the archived conversation first')
        if not goal and ui_event is None and mode in ('auto', 'text') and self.gateway_factory is not None:
            running = self.queue.open_for_steer(principal, conversation_id)
            if running is not None and running['intent'] in ('chat', 'browse', 'goal_continue', 'goal_resume'):
                try:
                    return self.steer(principal, running, message=message, key=key, provenance=provenance)
                except Conflict:
                    pass                         # the task finished a moment ago: this becomes a task of its own
        kind = ('plan' if mode == 'plan' else 'browse' if mode == 'browse' and self.browse else 'text') if provenance == 'customer' else 'text'
        context = {'mode': 'text'} if mode == 'text' else None      # Text mode means plain text: the browser is not offered for it
        if ui != 'basic' and mode != 'text' and kind == 'text':
            context = {**(context or {}), 'ui': ui}                 # answer style: which composed blocks the assistant may write (genui/document.py)
        if ui_event is not None:
            context = {**(context or {}), 'ui_artifact': ui_event}
        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id,
                                   intent=kind if kind in ('plan', 'browse') else 'chat', context=context, goal_mode=goal)
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
        own = self.unmetered(principal.account_id)
        try:
            amount, price_version = (OWN_KEY_AMOUNT, OWN_KEY_PRICE_VERSION) if own else self.pricer.reservation(message)
        except CapabilityUnavailable:
            # No verified route: the request waits unfunded, execution stays off.
            return {**result, 'conversation_id': conversation_id, 'execution_enabled': False,
                    'admission': 'route_unconfigured', 'price_version': None, 'response_type': kind if kind in ('plan', 'browse') else 'text'}
        try:
            self.ledger.admit(principal, task=result['id'], project=project_id, conversation=conversation_id,
                              key=key, amount_microusd=amount, upper_bound_verified=True, unmetered=own)
        except Exception:
            # Whatever stopped admission (budget, mismatch, storage), the request must not stay queued without a reservation:
            # it would be claimed and wedge the serial slot.
            self.queue.cancel(principal, result['id'])
            raise
        self._announce_queued(principal.account_id, result['id'])
        return {**result, 'conversation_id': conversation_id, 'execution_enabled': True,
                'admission': 'reserved', 'price_version': price_version, 'response_type': kind if kind in ('plan', 'browse') else 'text'}

    def steer(self, principal: Principal, running: dict, *, message: str, key: str, provenance: str = 'customer'):
        """Join a message to the run that is going on, with the runtime's own steering. The message belongs to that request (same reservation, same outcome); the worker, which
        owns the request, waits for the run it starts. Refused (Conflict) once the request has begun to close, so no run is ever started that nobody owns."""
        factory = self.gateway_factory
        if factory is None:
            raise Conflict('steering is not available')
        run_key = f'{running["id"]}-s-{hashlib.sha256(key.encode()).hexdigest()[:16]}'
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute("""SELECT r.conversation_id,c.native_session_ref FROM customer_requests r JOIN conversations c ON c.account_id=r.account_id AND c.id=r.conversation_id
                WHERE r.account_id=? AND r.id=? AND r.state IN ('starting','running') AND r.closing=0 AND r.cancel_requested=0""", (principal.account_id, running['id'])).fetchone()
            if not row or not row['native_session_ref']:
                raise Conflict('the task is not accepting messages')
            if con.execute('SELECT 1 FROM chat_deliveries WHERE account_id=? AND request_id=? AND idempotency_key=?', (principal.account_id, running['id'], run_key)).fetchone():
                return self._steer_view(principal, running['id'], run_key)           # the same message sent again (double click, retry): nothing new
            attempt = con.execute('SELECT coalesce(max(attempt),0)+1 FROM chat_deliveries WHERE account_id=? AND request_id=?', (principal.account_id, running['id'])).fetchone()[0]
            now = int(self.clock())
            con.execute("""INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,created_epoch,updated_epoch,kind,payload)
                VALUES (?,?,?,?,?,'pending',?,?,?,'steer',?)""", (principal.account_id, running['id'], attempt, run_key, hashlib.sha256(message.encode()).hexdigest(), run_key, now, now, message))
            con.execute('INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,?,?)',
                        (principal.account_id, row['conversation_id'], running['id'], provenance, message))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, running['id'], 'chat.steer', 'completed')
            session = row['native_session_ref']
        try:
            ack = factory(principal.account_id).send(session, run_key, message, queue_mode='steer')
        except Exception:
            with self.coordinator.transaction() as con:      # the write may have landed: the worker settles it by the run id (a resend of the same key is safe)
                con.execute("UPDATE chat_deliveries SET state='uncertain',updated_epoch=? WHERE account_id=? AND request_id=? AND idempotency_key=?", (int(self.clock()), principal.account_id, running['id'], run_key))
            raise
        with self.coordinator.transaction() as con:
            con.execute("UPDATE chat_deliveries SET state='acknowledged',native_run_id=?,updated_epoch=? WHERE account_id=? AND request_id=? AND idempotency_key=?",
                        (ack['run_id'], int(self.clock()), principal.account_id, running['id'], run_key))
        if self.events is not None:
            try:
                self.events.append(principal.account_id, running['id'], 'progress', {'summary': 'Your message was added to the task that is running.', 'step': 'steered'}, 'queue')
            except Exception:
                pass
        return self._steer_view(principal, running['id'], run_key)

    def _steer_view(self, principal, request_id, run_key):
        return {**self.queue.get(principal, request_id), 'steered': True, 'run_id': run_key, 'execution_enabled': True, 'admission': 'steered', 'response_type': 'text'}

    def goal_action(self, principal: Principal, conversation_id: str, action: str, *, key: str):
        """The customer's controls on a session goal: 'resume' (a paused, blocked or budget-limited goal; admitted and funded like any task) or 'clear' (forget the objective)."""
        identifier(key)
        if action not in ('resume', 'clear'):
            raise ValueError('invalid goal action')
        found = self.conversation(principal, conversation_id)
        if found['archived_epoch'] is not None:
            raise Conflict('restore the archived conversation first')
        if action == 'clear':
            session = self._session_of(principal, conversation_id)
            if session is None or self.gateway_factory is None:
                raise Conflict('there is no goal')
            gateway = self.gateway_factory(principal.account_id)
            goal = gateway.session_goal(session)
            if goal is None:
                raise Conflict('there is no goal')
            if self.queue.open_for_steer(principal, conversation_id) is not None:
                raise Conflict('stop the running task first')
            gateway.goal_clear(session, goal['id'], 'clear-' + hashlib.sha256(key.encode()).hexdigest()[:24])
            return {'goal': None}
        return self._spawn(principal, conversation_id, message='Continue pursuing the current goal.', key='goal-resume-' + key, intent='goal_resume',
                           context={'resume': True}, shown='Resuming the goal.', provenance='system', goal_mode=True)

    def _session_of(self, principal, conversation_id):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?', (principal.account_id, conversation_id)).fetchone()
        return row['native_session_ref'] if row else None

    # -- generative UI operations (the only things a block button can do) -------------------------------------------
    def _spawn(self, principal, conversation_id, *, message, key, intent, context, shown, provenance='customer', goal_mode=False, continues=None):
        """Queue a request created by a block action or by the goal chain, show `shown` as the turn, and admit it like any send."""
        result = self.queue.submit(principal, message=message, key=key, conversation_id=conversation_id, intent=intent, context=context, goal_mode=goal_mode, continues=continues)
        with self.coordinator.transaction() as con:
            if not con.execute('SELECT 1 FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance=?',
                               (principal.account_id, conversation_id, result['id'], provenance)).fetchone():
                con.execute('INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (?,?,?,?,?)',
                            (principal.account_id, conversation_id, result['id'], provenance, shown[:16000]))
        amount, price_version, _project = self._admit(principal, result, conversation_id, key, message)
        if amount is not None:
            self._announce_queued(principal.account_id, result['id'])
        return {**result, 'conversation_id': conversation_id, 'execution_enabled': amount is not None,
                'admission': 'reserved' if amount is not None else 'route_unconfigured'}

    def _announce_queued(self, account_id, request_id):
        """First line of the live timeline, written at once so the Live view has something true to show while the assistant is still being woken. Best-effort, once per task."""
        if self.events is None:
            return
        try:
            with self.store.connect() as con:
                if con.execute("SELECT 1 FROM events WHERE account_id=? AND task_id=? AND kind='task_queued'", (account_id, request_id)).fetchone():
                    return
            self.events.append(account_id, request_id, 'task_queued', {'summary': 'Received. Getting your assistant ready.'}, 'queue')
        except Exception:
            pass

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
                (principal.account_id, conversation_id, after, limit + 1)).fetchall()
            tasks = con.execute('''SELECT r.id,r.state,r.paused,r.cancel_requested,r.result,r.created_epoch,r.outcome,r.outcome_note,r.verification,r.parked_reason,r.goal_mode,r.continues,
                    r.continue_goal,t.state AS task_state,t.budget_microusd,v.state AS reservation_state
                FROM customer_requests r LEFT JOIN tasks t ON t.account_id=r.account_id AND t.id=r.id
                LEFT JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND r.conversation_id=? ORDER BY r.sequence DESC LIMIT 20''',
                (principal.account_id, conversation_id)).fetchall()
            return {'conversation_id': conversation_id,
                    'messages': [dict(row) for row in rows[:limit]], 'has_more': len(rows) > limit,
                    'next_after': rows[min(limit, len(rows)) - 1]['id'] if rows else after, 'tasks': [dict(row) for row in tasks],
                    'execution_enabled': self.execution}

    def task(self, principal: Principal, request_id: str):
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT r.id,r.state,r.paused,r.cancel_requested,r.result,r.created_epoch,r.conversation_id,r.outcome,r.outcome_note,r.verification,r.parked_reason,r.goal_mode,r.continues,
                    r.continue_goal,t.state AS task_state,t.budget_microusd,v.state AS reservation_state
                FROM customer_requests r LEFT JOIN tasks t ON t.account_id=r.account_id AND t.id=r.id
                LEFT JOIN task_reservations v ON v.account_id=r.account_id AND v.task_id=r.id
                WHERE r.account_id=? AND r.id=?''', (principal.account_id, request_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            receipts = con.execute('SELECT amount_microusd,price_version FROM provider_receipts WHERE account_id=? AND task_id=?', (principal.account_id, request_id)).fetchall()
            usage = {'tokens': None, 'cost_microusd': sum(r['amount_microusd'] for r in receipts) if receipts else None,
                     'estimated': any(r['price_version'] == 'reservation-upper-bound-v1' for r in receipts), 'currency': 'USD'}
            return {**dict(row), 'usage': usage, 'execution_enabled': self.execution}

    def cancel(self, principal: Principal, request_id: str):
        before = self.task(principal, request_id)
        result = self.queue.cancel(principal, request_id)
        if before['state'] == 'waiting' and (before['goal_mode'] or before['continues']):
            self._pause_goal(principal, before['conversation_id'], 'Stopped by the customer.')       # no driver will see this one: the goal must not wait to be resumed by a later turn
        return result

    def _pause_goal(self, principal, conversation_id, note):
        """Best effort and idempotent: a goal that cannot be reached right now is paused by the driver the next time it runs; Stop itself never fails on it."""
        try:
            session = self._session_of(principal, conversation_id)
            if session is None or self.gateway_factory is None:
                return
            gateway = self.gateway_factory(principal.account_id)
            goal = gateway.session_goal(session)
            if goal is not None and goal['status'] == 'active':
                gateway.goal_update(session, goal['id'], 'pause', 'stop-' + uuid.uuid4().hex[:24], note=note)
        except Exception:
            pass

    def pause(self, principal: Principal, request_id: str):
        return self.queue.pause(principal, request_id)

    def resume(self, principal: Principal, request_id: str):
        return self.queue.resume(principal, request_id)

    def retry(self, principal: Principal, request_id: str):
        """Run a failed or cancelled task again: the same request in the same conversation, queued and admitted afresh (a new budget reservation, the usual caps).
        Idempotent: pressing Retry twice gives the one retry. The new task's `retry_of` names the original."""
        source = self.queue.retry_source(principal, request_id)
        latest = source['latest']
        if latest and latest['state'] in ('waiting', 'starting', 'running', 'uncertain', 'completed'):
            return latest | {'execution_enabled': self.execution, 'admission': 'existing'}        # a repeat press: the retry that already exists
        if self.conversation(principal, source['conversation_id'])['archived_epoch'] is not None:
            raise Conflict('restore the archived conversation first')
        result = self._spawn(principal, source['conversation_id'], message=source['message'], key=f'retry-{request_id}-{source["attempts"] + 1}',
                             intent=source['intent'], context=source['context'], shown=source['message'], goal_mode=source['goal_mode'])
        self.queue.mark_retry(principal, result['id'], request_id)
        return self.queue.get(principal, result['id']) | {'execution_enabled': result['execution_enabled'], 'admission': result['admission']}


