"""Persistence and the only operations a block may trigger. Every method re-authorizes and re-validates."""
from __future__ import annotations
import json
import time
import uuid

from agentai_platform.lifecycle.coordinator import Coordinator, identifier
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal

from . import document, schema


def _public(row, con=None) -> dict:
    out = _public_base(row)
    if con is not None and row['kind'] == 'task_plan' and row['status'] == 'launched':
        out['run'], out['run_status'] = _run(con, row['account_id'], row['id'])
    return out


def _run(con, account, block):
    rows = con.execute('SELECT * FROM plan_phase_runs WHERE account_id=? AND block_id=? ORDER BY position', (account, block)).fetchall()
    run = {r['phase_id']: {'state': r['state'], 'attempts': r['attempts'], 'request_id': r['request_id'], 'summary': r['summary'],
                           'approved': r['approved_epoch'] is not None, 'started_epoch': r['started_epoch'], 'finished_epoch': r['finished_epoch']} for r in rows}
    states = [r['state'] for r in rows]
    if 'running' in states:
        status = 'running'
    elif 'awaiting_approval' in states:
        status = 'awaiting_approval'
    elif 'failed' in states:
        status = 'failed'
    elif 'pending' in states:
        status = 'running'
    elif 'cancelled' in states:
        status = 'stopped'
    else:
        status = 'completed'
    return run, status


def _public_base(row) -> dict:
    return {'id': row['id'], 'conversation_id': row['conversation_id'], 'anchor_message_id': row['anchor_message_id'], 'kind': row['kind'],
            'schema_version': row['schema_version'], 'spec': json.loads(row['spec_json']), 'state': json.loads(row['state_json']),
            'version': row['version'], 'status': row['status'], 'launched_request_id': row['launched_request_id'],
            'created_epoch': row['created_epoch'], 'updated_epoch': row['updated_epoch']}


def _card(row, con=None) -> dict:
    meta = con.execute('SELECT * FROM gen_artifact_state WHERE account_id=? AND artifact_id=?', (row['account_id'], row['id'])).fetchone() if con is not None and row['kind'] == 'document' else None
    return {'id': row['id'], 'conversation_id': row['conversation_id'], 'anchor_message_id': row['anchor_message_id'], 'kind': row['kind'],
            'state_revision': meta['state_revision'] if meta else 1,
            'schema_version': '1.0', 'spec': json.loads(row['spec_json']), 'state': json.loads(meta['state_json']) if meta else {}, 'version': meta['version'] if meta else 1, 'status': 'final', 'launched_request_id': None,
            'created_epoch': row['created_epoch'], 'updated_epoch': row['created_epoch']}


class BlockStore:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    # -- creation: server code only, never reachable from a client request body -------------------------------------
    def create_form(self, account_id, conversation_id, spec, *, key, anchor_message_id=None, source_request_id=None, con=None) -> dict:
        spec = schema.validate_form(spec)
        state = {'answers': schema.validate_answers(spec, {})}
        return self._create(account_id, conversation_id, 'form', spec, state, key=key, anchor=anchor_message_id, source=source_request_id, con=con)

    def create_plan(self, account_id, conversation_id, plan, *, key, anchor_message_id=None, source_request_id=None, requirements=None, con=None) -> dict:
        plan = schema.validate_plan(plan)
        state = {'plan': plan, 'requirements': requirements or {}, 'revision': 1}
        return self._create(account_id, conversation_id, 'task_plan', plan, state, key=key, anchor=anchor_message_id, source=source_request_id, con=con,
                            revision=('ai', plan))

    def _create(self, account, conversation, kind, spec, state, *, key, anchor, source, con, revision=None):
        identifier(key)
        if con is None:
            with self.coordinator.transaction() as inner:
                return self._create(account, conversation, kind, spec, state, key=key, anchor=anchor, source=source, con=inner, revision=revision)
        existing = con.execute('SELECT * FROM ui_blocks WHERE account_id=? AND idempotency_key=?', (account, key)).fetchone()
        if existing:
            return _public(existing)
        if not con.execute('SELECT 1 FROM conversations WHERE account_id=? AND id=?', (account, conversation)).fetchone():
            raise NotFound('unavailable')
        block, now = uuid.uuid4().hex, int(self.clock())
        con.execute('''INSERT INTO ui_blocks(account_id,id,conversation_id,anchor_message_id,kind,schema_version,spec_json,state_json,version,status,
            source_request_id,idempotency_key,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?,1,'draft',?,?,?,?)''',
                    (account, block, conversation, anchor, kind, schema.SCHEMA_VERSION, json.dumps(spec), json.dumps(state), source, key, now, now))
        if revision:
            con.execute('INSERT INTO plan_revisions VALUES (?,?,1,?,?,?)', (account, block, revision[0], json.dumps(revision[1]), now))
        return _public(con.execute('SELECT * FROM ui_blocks WHERE account_id=? AND id=?', (account, block)).fetchone(), con)

    # -- reads ---------------------------------------------------------------------------------------------------
    def list(self, principal: Principal, conversation_id: str) -> list[dict]:
        identifier(conversation_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM conversations WHERE account_id=? AND id=?', (principal.account_id, conversation_id)).fetchone():
                raise NotFound('unavailable')
            rows = con.execute('SELECT * FROM ui_blocks WHERE account_id=? AND conversation_id=? ORDER BY created_epoch,rowid LIMIT 100',
                               (principal.account_id, conversation_id)).fetchall()
            out = [_public(r, con) for r in rows]
            cards = con.execute('SELECT * FROM data_blocks WHERE account_id=? AND conversation_id=? ORDER BY created_epoch,position LIMIT 100',
                                (principal.account_id, conversation_id)).fetchall()
            return out + [_card(c, con) for c in cards]

    def get(self, principal: Principal, block_id: str, con=None) -> dict:
        identifier(block_id)
        if con is None:
            with self.store.connect() as inner:
                self.store._authorize(inner, principal)
                return self.get(principal, block_id, inner)
        row = con.execute('SELECT * FROM ui_blocks WHERE account_id=? AND id=?', (principal.account_id, block_id)).fetchone()
        if not row:
            raise NotFound('unavailable')
        return _public(row, con)

    # -- registered operation 1: save the user's edits (autosave) ---------------------------------------------------
    def save_state(self, principal: Principal, block_id: str, version: int, state) -> dict:
        if type(version) is not int or version < 1:
            raise ValueError('invalid version')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            block = self.get(principal, block_id, con)
            if block['status'] != 'draft':
                raise Conflict('this block can no longer be edited')
            if block['version'] != version:
                raise Conflict('version conflict')           # someone (another tab) saved first: reload instead of overwriting
            if not isinstance(state, dict):
                raise schema.SpecError('state must be an object')
            if block['kind'] == 'form':
                new = {'answers': schema.validate_answers(block['spec'], state.get('answers', {}))}
            else:
                plan = schema.validate_plan(state.get('plan'))
                new = {'plan': plan, 'requirements': block['state'].get('requirements', {}), 'revision': block['state'].get('revision', 1)}
                if plan != block['state']['plan']:
                    new['revision'] = block['state']['revision'] + 1
                    con.execute('INSERT OR REPLACE INTO plan_revisions VALUES (?,?,?,?,?,?)',
                                (principal.account_id, block_id, new['revision'], 'user', json.dumps(plan), int(self.clock())))
            con.execute('UPDATE ui_blocks SET state_json=?,version=version+1,updated_epoch=? WHERE account_id=? AND id=?',
                        (json.dumps(new), int(self.clock()), principal.account_id, block_id))
            return self.get(principal, block_id, con)

    def set_status(self, con, account_id, block_id, status, *, request_id=None):
        con.execute('UPDATE ui_blocks SET status=?,launched_request_id=coalesce(?,launched_request_id),version=version+1,updated_epoch=? '
                    'WHERE account_id=? AND id=?', (status, request_id, int(self.clock()), account_id, block_id))

    # -- read-only data cards extracted from an assistant answer (server code only) ----------------------------------
    def add_display(self, account_id, conversation_id, request_id, style, plan=None) -> bool:
        """Record how the request's plain-text reply should be laid out (routing/display.py), anchored to that reply. Only when the request stored no card."""
        if style not in ('steps', 'answer', 'list'):
            return False
        with self.coordinator.transaction() as con:
            if con.execute('SELECT 1 FROM data_blocks WHERE account_id=? AND source_request_id=?', (account_id, request_id)).fetchone():
                return False
            row = con.execute("SELECT id FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance='agent' ORDER BY id DESC LIMIT 1",
                              (account_id, conversation_id, request_id)).fetchone()
            if row is None:
                return False
            con.execute('INSERT INTO data_blocks(account_id,id,conversation_id,anchor_message_id,kind,spec_json,source_request_id,position,created_epoch) VALUES (?,?,?,?,?,?,?,?,?)',
                        (account_id, uuid.uuid4().hex, conversation_id, row['id'], 'display', json.dumps({'schemaVersion': '1.0', 'type': 'display', 'style': style, **({'presentationPlan': plan} if plan else {})}), request_id, 0, int(self.clock())))
        return True

    def attach_cards(self, account_id, conversation_id, request_id) -> int:
        """Attach registry documents or apply a versioned continuation update; historical messages stay intact."""
        with self.store.connect() as con:
            rows = [dict(r) for r in con.execute("SELECT id,content FROM chat_messages WHERE account_id=? AND conversation_id=? AND request_id=? AND provenance='agent' "
                                                 "AND content LIKE '%```lumina-doc%' ORDER BY id", (account_id, conversation_id, request_id)).fetchall()]
        with self.store.connect() as con:
            ctx = con.execute('SELECT context_json FROM customer_requests WHERE account_id=? AND id=?', (account_id, request_id)).fetchone()
        request_context = json.loads(ctx['context_json'] or '{}') if ctx else {}
        try:
            tier = request_context.get('ui', document.DEFAULT_TIER)
        except ValueError:
            tier = document.DEFAULT_TIER
        if tier not in document.TIERS:
            tier = document.DEFAULT_TIER
        prepared = []
        for row in rows:
            clean, specs = document.extract_documents(row['content'], tier)
            prepared.append((row, clean, specs))
        made = 0
        with self.coordinator.transaction() as con:
            for row, clean, specs in prepared:
                now = con.execute('SELECT content FROM chat_messages WHERE account_id=? AND id=?', (account_id, row['id'])).fetchone()
                if now is None or now['content'] != row['content']:
                    continue                                   # already handled (or edited) while pictures were being fetched
                for spec in specs:
                    target = spec.get('artifactId')
                    if target:
                        from .artifacts import ArtifactStore, strict_document
                        interaction = request_context.get('ui_artifact') or {}
                        prior = con.execute("SELECT * FROM data_blocks WHERE account_id=? AND id=? AND conversation_id=? AND kind='document'", (account_id, target, conversation_id)).fetchone()
                        meta = con.execute('SELECT * FROM gen_artifact_state WHERE account_id=? AND artifact_id=?', (account_id, target)).fetchone()
                        if prior and meta and interaction.get('artifact_id') == target and spec.get('baseVersion') == meta['version']:
                            value = strict_document({k: v for k, v in spec.items() if k != 'type'})
                            ArtifactStore(self.store, self.clock).replace(con, account_id, target, prior, meta, value)
                            made += 1
                        continue
                    cur = con.execute('SELECT coalesce(max(position),-1)+1 FROM data_blocks WHERE account_id=? AND source_request_id=?', (account_id, request_id)).fetchone()[0]
                    con.execute('INSERT OR IGNORE INTO data_blocks(account_id,id,conversation_id,anchor_message_id,kind,spec_json,source_request_id,position,created_epoch) '
                                'VALUES (?,?,?,?,?,?,?,?,?)', (account_id, uuid.uuid4().hex, conversation_id, row['id'], spec['type'], json.dumps(spec), request_id, cur, int(self.clock())))
                    made += 1
                con.execute('UPDATE chat_messages SET content=? WHERE account_id=? AND id=?', (clean or 'Here is what I found.', account_id, row['id']))
        return made
