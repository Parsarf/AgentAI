"""Durable declarative artifacts. User events bind to stored actions, never client authority."""
from __future__ import annotations
import hashlib
import json
import math
import re
import time
from datetime import date
from . import document
from .schema import SpecError
from agentai_platform.lifecycle.coordinator import Coordinator, identifier
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound


def nodes(doc):
    for node in doc['blocks']:
        yield node
        yield from nodes({'blocks': document._children(node)})


def available_node(doc, node_id, blocked=False):
    for node in doc['blocks']:
        unavailable = blocked or node.get('disabled') or node.get('loading') or node.get('visible') is False
        if node['id'] == node_id:
            return None if unavailable else node
        found = available_node({'blocks': document._children(node)}, node_id, unavailable)
        if found is not None:
            return found
    return None


def bindings(node):
    p = node['props']
    if node['type'] == 'approval_request':
        yield 'approve', {'kind': 'agent.approve', 'planBlockId': p['planBlockId'], 'phaseId': p['phaseId']}
        yield 'deny', {'kind': 'agent.deny', 'planBlockId': p['planBlockId'], 'phaseId': p['phaseId']}
    if node['type'] == 'error_retry':
        yield 'retry', {'kind': 'agent.retry', **{k: p[k] for k in ('planBlockId', 'phaseId', 'requestId') if p.get(k)}}
    if 'submit' in p:
        yield 'submit', p['submit']['action']
    if 'action' in p:
        yield 'confirm', p['action']
    for b in p.get('items', []):
        if 'action' in b:
            yield b['id'], b['action']
    for i, card in enumerate(p.get('cards', [])):
        for j, b in enumerate(card.get('actions', [])):
            yield f'card-{i}-action-{j}', b['action']
    for i, b in enumerate(p.get('buttons', [])):
        yield b['id'], b['action']
    for i, b in enumerate(p.get('actions', [])):
        yield f'action-{i}', b['action']
    for i, s in enumerate(p.get('suggestions', [])):
        yield f'suggestion-{i}', {'kind': 'agent.request', 'message': s}


class FieldErrors(SpecError):
    def __init__(self, errors):
        super().__init__('Some fields need attention')
        self.errors = errors


def field_error(f, value):
    if value == '' or value is None or value == []:
        return 'Enter a value.' if f.get('required') else None
    kind = f['type']
    def bounded(v):
        return type(v) in (int, float) and math.isfinite(v) and f.get('min', -1e15) <= v <= f.get('max', 1e15)
    def calendar(v):
        if not isinstance(v, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', v): return False
        try: date.fromisoformat(v); return True
        except ValueError: return False
    if kind in ('multiselect', 'range', 'date-range', 'tags'):
        if not isinstance(value, list) or len(value) > 50 or any(type(v) not in (str, int, float) or (isinstance(v, str) and len(v) > 80) or (type(v) in (int, float) and not math.isfinite(v)) for v in value):
            return 'Use at most 50 valid items, with at most 80 characters each.'
        if kind in ('range', 'date-range'):
            valid = len(value) == 2 and all(bounded(v) if kind == 'range' else calendar(v) for v in value)
            if not valid: return 'Enter both valid ends of the range.'
            if value[0] > value[1]: return 'Start must be before or equal to end.'
    elif kind in ('checkbox', 'toggle'):
        if type(value) is not bool: return 'Choose yes or no.'
    elif kind in ('number', 'slider', 'rating'):
        if not bounded(value): return 'Enter a number within the allowed range.'
        step = f.get('step')
        if step and step > 0:
            count = (value - f.get('min', 0)) / step
            if abs(count - round(count)) > 1e-7: return f'Use increments of {step}.'
    elif not isinstance(value, str) or len(value) > 500 or document._CONTROL.search(value):
        return 'Use at most 500 characters without control characters.'
    if kind == 'date' and not calendar(value): return 'Enter a valid calendar date.'
    if kind == 'time' and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value): return 'Enter a valid time.'
    if kind == 'color' and not re.fullmatch(r'#[0-9a-fA-F]{6}', value): return 'Choose a valid color.'
    options = f.get('options')
    if options and kind in ('select', 'radio', 'segmented', 'multiselect') and any(v not in {o['value'] for o in options} for v in (value if isinstance(value, list) else [value])):
        return 'Choose an available option.'
    return None


def answers(node, values):
    fields = node['props'].get('fields', [])
    if node['type'] == 'wizard':
        fields = [dict(f, type='text') for step in node['props']['steps'] for f in step['fields']]
    elif node['type'] == 'human_prompt':
        fields = [{'id': 'response', 'label': node['props']['message'], 'type': 'text', 'required': True}]
    if not isinstance(values, dict) or set(values) - {f['id'] for f in fields}:
        raise SpecError('unknown submitted fields')
    effective = {f['id']: values.get(f['id'], f.get('default', '')) for f in fields}
    out, lines, errors = {}, [], {}
    for f in fields:
        value = effective[f['id']]
        cond = f.get('showIf')
        if cond and effective.get(cond['field']) != cond['equals']: continue
        error = field_error(f, value)
        if error:
            errors[f['id']] = error; continue
        if value == '' or value is None or value == []: continue
        out[f['id']] = value
        lines.append(f'- {f["label"]}: {value}')
    if errors: raise FieldErrors(errors)
    return out, lines


class ArtifactStore:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def _row(self, con, principal, artifact):
        self.store._authorize(con, principal)
        row = con.execute("SELECT * FROM data_blocks WHERE account_id=? AND id=? AND kind='document'", (principal.account_id, artifact)).fetchone()
        if row is None:
            raise NotFound('unavailable')
        con.execute('INSERT OR IGNORE INTO gen_artifact_state(account_id,artifact_id) VALUES (?,?)', (principal.account_id, artifact))
        meta = con.execute('SELECT * FROM gen_artifact_state WHERE account_id=? AND artifact_id=?', (principal.account_id, artifact)).fetchone()
        return row, meta

    def state(self, principal, artifact, version, revision, state):
        if type(version) is not int or type(revision) is not int or not isinstance(state, dict) or len(json.dumps(state)) > 32000:
            raise SpecError('invalid artifact state')
        with self.coordinator.transaction() as con:
            row, meta = self._row(con, principal, artifact)
            if (version, revision) != (meta['version'], meta['state_revision']):
                raise Conflict('artifact changed; reload before saving')
            allowed = {n['id'] for n in nodes(json.loads(row['spec_json']))}
            if set(state) - allowed or any(not isinstance(v, dict) for v in state.values()):
                raise SpecError('state must address nodes in this artifact')
            con.execute('UPDATE gen_artifact_state SET state_json=?,state_revision=state_revision+1 WHERE account_id=? AND artifact_id=?', (json.dumps(state, allow_nan=False), principal.account_id, artifact))
            return {'state_revision': revision + 1}

    def event(self, principal, artifact, payload, chat):
        expected = {'id', 'node_id', 'action_id', 'version', 'values'}
        if not isinstance(payload, dict) or set(payload) != expected or len(json.dumps(payload)) > 16000:
            raise SpecError('invalid event envelope')
        for key in ('id', 'node_id', 'action_id'):
            identifier(payload[key])
        if type(payload['version']) is not int:
            raise SpecError('invalid version')
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False)
        with self.coordinator.transaction() as con:
            row, meta = self._row(con, principal, artifact)
            prior = con.execute('SELECT * FROM gen_artifact_events WHERE account_id=? AND id=?', (principal.account_id, payload['id'])).fetchone()
            if prior:
                if prior['artifact_id'] != artifact or prior['actor_id'] != principal.actor_id or prior['payload_json'] != encoded:
                    raise Conflict('event id was already used')
                if prior['status'] == 'success':
                    return json.loads(prior['result_json'])
                if prior['status'] == 'pending' and int(self.clock()) - prior['created_epoch'] < 60:
                    raise Conflict('event is being processed')
            if payload['version'] != meta['version']:
                raise Conflict('artifact version is stale')
            node = available_node(json.loads(row['spec_json']), payload['node_id'])
            if node is None or node.get('disabled') or node.get('loading'):
                raise SpecError('node is unavailable')
            action = dict(bindings(node)).get(payload['action_id'])
            if action is None or action['kind'] not in ('agent.request', 'agent.approve', 'agent.deny', 'agent.retry'):
                raise SpecError('unknown agent action binding')
            if node['props'].get('expiresEpoch') is not None and node['props']['expiresEpoch'] <= self.clock():
                raise Conflict('approval has expired')
            plan_id = action.get('planBlockId')
            if plan_id:
                plan = con.execute('SELECT conversation_id FROM ui_blocks WHERE account_id=? AND id=?', (principal.account_id, plan_id)).fetchone()
                phase = con.execute('SELECT state FROM plan_phase_runs WHERE account_id=? AND block_id=? AND phase_id=?', (principal.account_id, plan_id, action.get('phaseId'))).fetchone()
                want = 'failed' if action['kind'] == 'agent.retry' else 'awaiting_approval'
                if not plan or plan['conversation_id'] != row['conversation_id'] or not phase or phase['state'] != want:
                    raise Conflict('this phase is unavailable for that action')
            elif action.get('requestId'):
                target = con.execute('SELECT conversation_id FROM customer_requests WHERE account_id=? AND id=?', (principal.account_id, action['requestId'])).fetchone()
                if not target or target['conversation_id'] != row['conversation_id']:
                    raise NotFound('unavailable')
            values, lines = answers(node, payload['values'])
            state_revision = meta['state_revision']
            if values:
                state = json.loads(meta['state_json'])
                local = dict(state.get(node['id'], {}))
                local.update({'value': values['response']} if node['type'] == 'human_prompt' else {'values': values})
                state[node['id']] = local
                con.execute('UPDATE gen_artifact_state SET state_json=?,state_revision=state_revision+1 WHERE account_id=? AND artifact_id=?', (json.dumps(state), principal.account_id, artifact))
                state_revision += 1
            conversation = row['conversation_id']
            con.execute('INSERT OR REPLACE INTO gen_artifact_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (principal.account_id, payload['id'], artifact, principal.actor_id, conversation, node['id'], payload['action_id'], payload['version'], encoded, 'pending', None, int(self.clock())))
        key = 'uie' + hashlib.sha256(f'{artifact}:{payload["id"]}'.encode()).hexdigest()[:48]
        message = '\n'.join([action.get('message', ''), *lines])[:16000]
        # A deterministic queue key prevents a second execution if the process dies after sending.
        try:
            if action['kind'] == 'agent.request':
                result = chat.send(principal, conversation_id=conversation, message=message, key=key, ui='interactive', ui_event={'artifact_id': artifact, 'version': meta['version'], 'event_id': payload['id'], 'node_id': node['id'], 'action_id': payload['action_id'], 'values': values})
            elif action.get('planBlockId'):
                verb = {'agent.approve': 'approve', 'agent.deny': 'skip', 'agent.retry': 'retry'}[action['kind']]
                result = {'block': chat.runner.act(principal, action['planBlockId'], action['phaseId'], verb)}
            else:
                result = chat.retry(principal, action['requestId'])
        except Exception:
            with self.coordinator.transaction() as con:
                con.execute("UPDATE gen_artifact_events SET status='failed' WHERE account_id=? AND id=?", (principal.account_id, payload['id']))
            raise
        result = {**result, 'artifact_state_revision': state_revision}
        with self.coordinator.transaction() as con:
            con.execute("UPDATE gen_artifact_events SET status='success',result_json=? WHERE account_id=? AND id=?", (json.dumps(result), principal.account_id, payload['id']))
        return result

    def update(self, principal, artifact, version, raw):
        """Replace a document atomically, retaining compatible state by stable node id."""
        value = strict_document(raw)
        with self.coordinator.transaction() as con:
            row, meta = self._row(con, principal, artifact)
            if meta['version'] != version:
                raise Conflict('artifact version is stale')
            self.replace(con, principal.account_id, artifact, row, meta, value)
        return {'artifact_id': artifact, 'version': version + 1}

    def replace(self, con, account, artifact, row, meta, value):
        old = {n['id']: n for n in nodes(json.loads(row['spec_json']))}
        keep = {n['id'] for n in nodes(value) if n['id'] in old and old[n['id']]['type'] == n['type'] and old[n['id']]['props'].get('fields') == n['props'].get('fields')}
        state = {k: v for k, v in json.loads(meta['state_json']).items() if k in keep}
        con.execute('UPDATE data_blocks SET spec_json=? WHERE account_id=? AND id=?', (json.dumps(dict(value, type='document')), account, artifact))
        con.execute('UPDATE gen_artifact_state SET version=version+1,state_revision=state_revision+1,state_json=? WHERE account_id=? AND artifact_id=?', (json.dumps(state), account, artifact))


def strict_document(raw):
    if not isinstance(raw, dict) or len(json.dumps(raw, allow_nan=False)) > document.registry()['limits']['bytes']:
        raise SpecError('invalid or excessive document')
    if set(raw) - {'version', 'responseId', 'blocks', 'datasets', 'presentationPlan', 'artifactId', 'baseVersion'}:
        raise SpecError('unknown document properties')
    value = document.validate_document(raw)
    seen = set()
    for n in nodes(raw):
        document.validate_block(n, raw.get('datasets', {}))
        if n['id'] in seen:
            raise SpecError('duplicate node id')
        seen.add(n['id'])
    count, depth = document._shape(raw['blocks'])
    if count > document.registry()['limits']['nested'] or depth > document.registry()['limits']['depth']:
        raise SpecError('document nesting limit exceeded')
    return value
