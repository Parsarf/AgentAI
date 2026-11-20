"""The action pipeline (roadmap #26 previews and approval, #27 undo, #28 compensation): the one way Lumina changes anything in an outside system.

An ACTION is one proposed change. Its row holds the exact payload that will be sent and a hash of it. Everything after that hangs on the hash:

* PREVIEW. Rendered from the stored payload by the connector's own renderer for that write kind, never from a description the assistant writes. It always says where it
  goes, what changes (before and after), how many records or people are affected, and what cannot be taken back.
* APPROVAL. The customer approves THAT hash, and the approval expires. If the stored payload no longer hashes to it, the approval is void. An organization may ask for an
  admin as well. The customer may let one kind of change on one connection go ahead without asking (never the default, and never for a kind that cannot be undone unless they
  said so for that kind).
* EXECUTION. At most once. The move from "approved" to "executing" is a single guarded update, so a double click, a second worker or a retry finds nothing left to start.
  The write carries the idempotency key `<request id>-<step>` (the step is counted by Lumina, never taken from the assistant). A write whose answer never came is
  `uncertain`: it is read back, never sent again blindly.
* VERIFICATION. After a success the result is read back and compared with what was sent. A mismatch is recorded and shown.
* UNDO. Every write kind registered its inverse or said why it cannot be undone. What the inverse needs is captured BEFORE the forward write. An undo is itself an action,
  with a preview and a receipt, and carries the record's version so it never overwrites a later change by somebody else.
* COMPENSATION. A kind that cannot be undone may register follow-ups defined in code (send a correction, unpublish ...). Their payloads are written durably before the
  forward write. The assistant may propose one; it never invents one.

Nothing here talks to a provider except through connector_kit.ConnectorClient, so permissions, grants, policy, rate limits and error mapping all apply.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid

from . import organizations, permissions
from .connector_kit import ConnectorFault, Unanswered, payload_hash
from .handoff import Handoffs
from .lifecycle.coordinator import Coordinator
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

APPROVAL_SECONDS = 900             # an approval is good for this long: execution must begin within it
STALE_SECONDS = 120                # an action "executing" for longer than this lost its worker: its outcome is unknown and is read back
MAX_ATTEMPTS = 3                   # sends of one action when the provider says "later"
OPEN = ('proposed', 'approved', 'executing', 'uncertain')
MAX_PAYLOAD_BYTES = 60000
FAILED_WORDS = {
    'conflict': 'The record changed in the connected service after this was prepared, so nothing was changed. Review the current version and prepare the change again.',
    'refused': 'The connected service, your choices or your organization do not allow this. Nothing was changed.',
    'needs_customer': 'The connection needs you (reconnect it in Settings). Nothing was changed.',
    'not_found': 'The item no longer exists in the connected service. Nothing was changed.',
    'invalid': 'The connected service did not accept this request. Nothing was changed.',
    'retry_later': 'The connected service stayed busy. Nothing was changed. It can be prepared again later.',
    'payload_changed': 'The change no longer matches what was approved, so it was not made.',
    'approval_expired': 'The approval ran out before the change could be made. Nothing was changed.',
    'connection_removed': 'The connection was removed. Nothing was changed.',
    'workflow_stopped': 'An earlier step did not succeed, so this step was not run.',
}


DIRECT_SCREENS = ('inbox', 'calendar', 'settings')


def _direct(row):
    try:
        return row['direct_screen']
    except (IndexError, KeyError):
        return None                                # a database before migration 0052


class ActionService:
    def __init__(self, store, connectors, client, *, clock=time.time, writes_on=lambda account, service=None: True):
        self.store, self.connectors, self.client, self.clock = store, connectors, client, clock
        self.writes_on = writes_on                # the owner switch for changes in connected services, asked per account
        self.coordinator = Coordinator(store, clock=clock)
        self.handoffs = Handoffs(store, clock=clock)

    # -- views -------------------------------------------------------------------------------------------------------------------------------
    def public(self, row) -> dict:
        preview = json.loads(row['preview_json'])
        return {'id': row['id'], 'request_id': row['request_id'], 'connection_id': row['connection_id'], 'provider': row['provider'], 'kind': row['kind'], 'state': row['state'],
                'payload_hash': row['payload_hash'], 'payload': json.loads(row['payload_json']), 'preview': preview,
                'can_undo': bool(row['can_undo']), 'undo_until_epoch': row['undo_until_epoch'], 'undo_of': row['undo_of'], 'compensates': row['compensates'],
                'compensations': sorted(json.loads(row['compensation_json'] or '{}')), 'needs_admin': bool(row['needs_admin']),
                'approved_by_you': bool(row['approved_by']), 'admin_approved': bool(row['admin_approved_by']), 'auto_approved': bool(row['auto_approved']),
                'approval_expires_epoch': row['approval_expires_epoch'], 'verified': None if row['verified'] is None else bool(row['verified']), 'verify_note': row['verify_note'],
                'conflict': json.loads(row['conflict_json']) if row['conflict_json'] else None, 'ended_reason': row['ended_reason'],
                'ended_words': FAILED_WORDS.get(row['ended_reason'], '') if row['ended_reason'] else '', 'workflow_id': row['workflow_id'],
                'receipt': row['receipt'], 'created_epoch': row['created_epoch'], 'executed_epoch': row['executed_epoch'],
                'direct': _direct(row)}

    def _row(self, con, account_id, action_id):
        row = con.execute('SELECT * FROM actions WHERE account_id=? AND id=?', (account_id, str(action_id))).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    def get(self, principal: Principal, action_id: str) -> dict:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return self.public(self._row(con, principal.account_id, action_id))

    def listing(self, principal: Principal, *, limit=30, request_id=None) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('SELECT * FROM actions WHERE account_id=?' + (' AND request_id=?' if request_id else '') + ' ORDER BY created_epoch DESC,id LIMIT ?',
                               (principal.account_id, *((request_id,) if request_id else ()), max(1, min(int(limit), 100)))).fetchall()
            return [self.public(r) for r in rows]

    # -- proposing ---------------------------------------------------------------------------------------------------------------------------
    def propose(self, principal: Principal, connection_id: str, kind: str, payload: dict, *, request_id=None, workflow=None, undo_of=None, compensates=None, base_version=None,
                key=None, ask=True) -> dict:
        """Record one change for approval. Nothing is sent. -> the action as the customer will see it. Raises ConnectorFault (one of six kinds) when it cannot even be proposed.

        `workflow` is (workflow id, position): the workflow's own approval covers the step, so no separate handoff is made. `ask=False` likewise makes no handoff (a reversal
        the runner starts itself)."""
        if not self.writes_on(principal.account_id, self.connectors.service_of(principal.account_id, connection_id)):
            raise ConnectorFault('refused')
        if not isinstance(payload, dict) or len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
            raise ConnectorFault('invalid')
        ready = self.client.prepare(principal, connection_id, kind, payload)             # role, connection state, policy, grant, shape, the record as it is now
        declaration, adapter, write_kind, before = ready['declaration'], ready['adapter'], ready['kind'], ready['before']
        digest = payload_hash(payload)
        preview = adapter.preview(kind, payload, before)
        preview = {'title': write_kind.label, 'destination': str(preview.get('destination', ''))[:300], 'summary': str(preview.get('summary', write_kind.label))[:300],
                   'changes': [{'field': str(c.get('field', ''))[:80], 'before': c.get('before'), 'after': c.get('after')} for c in (preview.get('changes') or [])][:40],
                   'affected': int(preview.get('affected') or 1), 'irreversible': write_kind.irreversible_reason or None, 'can_undo': bool(write_kind.undo),
                   'undo_seconds': write_kind.undo_seconds if write_kind.undo else None,
                   'compensations': [{'kind': c, 'label': declaration.write_kind(c).label} for c in write_kind.compensations]}
        if write_kind.needs_version and base_version is None:
            base_version = (before or {}).get('version')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            require(principal, 'action.propose', con=con)
            rule = max((organizations.write_rule(con, principal.account_id, name) for name in (write_kind.policy_kind, kind)), key=organizations.WRITE_RULES.index)
            if rule == 'blocked':
                raise ConnectorFault('refused')
            if request_id is not None and workflow is None and undo_of is None and compensates is None:
                same = con.execute(f"""SELECT * FROM actions WHERE account_id=? AND request_id=? AND connection_id=? AND kind=? AND payload_hash=?
                    AND state IN ({','.join('?' * len(OPEN))}) ORDER BY created_epoch LIMIT 1""", (principal.account_id, request_id, connection_id, kind, digest, *OPEN)).fetchone()
                if same:
                    return self.public(same)                    # the assistant asked for the very same change twice in one task: it is one action
            step = con.execute('SELECT count(*) FROM actions WHERE account_id=? AND request_id IS ?', (principal.account_id, request_id)).fetchone()[0] + 1
            key = key or (f'{request_id}-{step}' if request_id else 'act-' + uuid.uuid4().hex)
            if con.execute('SELECT 1 FROM actions WHERE account_id=? AND idempotency_key=?', (principal.account_id, key)).fetchone():
                raise Conflict('this change was already prepared')
            auto = con.execute('SELECT include_irreversible FROM action_auto_approvals WHERE account_id=? AND connection_id=? AND kind=?', (principal.account_id, connection_id, kind)).fetchone()
            automatic = bool(auto and rule != 'admin_approval' and workflow is None and (write_kind.undo or auto['include_irreversible']))
            action_id = uuid.uuid4().hex
            con.execute('''INSERT INTO actions(account_id,id,request_id,step,idempotency_key,actor_id,connection_id,provider,kind,payload_json,payload_hash,preview_json,target_json,
                base_version,before_json,can_undo,undo_kind,undo_of,compensates,state,needs_admin,approved_by,approved_epoch,approval_expires_epoch,auto_approved,workflow_id,
                workflow_position,created_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (principal.account_id, action_id, request_id, step, key, principal.actor_id, connection_id, ready['provider'], kind, json.dumps(payload, sort_keys=True), digest,
                         json.dumps(preview), json.dumps(list(ready['target'])) if ready['target'] else None, None if base_version is None else str(base_version),
                         json.dumps(before) if before else None, 1 if write_kind.undo else 0, write_kind.undo, undo_of, compensates,
                         'approved' if automatic else 'proposed', 1 if rule == 'admin_approval' else 0, principal.actor_id if automatic else None, now if automatic else None,
                         now + APPROVAL_SECONDS if automatic else None, 1 if automatic else 0, workflow[0] if workflow else None, workflow[1] if workflow else None, now, now))
            if not automatic and workflow is None and ask:
                self.handoffs.create(con, account_id=principal.account_id, actor_id=principal.actor_id, kind='action_approval', request_id=request_id, action_id=action_id,
                                     question=preview['summary'], evidence={'destination': preview['destination'], 'affected': preview['affected'], 'irreversible': preview['irreversible']},
                                     resume={'action': action_id})
            self.coordinator._audit(con, principal.account_id, principal.actor_id, action_id, 'action.propose', 'completed')
            return self.public(self._row(con, principal.account_id, action_id))

    # -- the customer's own hand (roadmap Phase 6) ----------------------------------------------------------------------------------------------
    def direct(self, principal: Principal, connection_id: str, kind: str, payload: dict, *, screen: str, base_version=None, delay_seconds: int = 0) -> dict:
        """A change the customer made themselves in the Inbox or the Calendar (pressed Send, cancelled an event): the same write kind through the same pipeline, and their
        press IS the approval, recorded with the screen it came from. Sent now, or after `delay_seconds` ("Undo send"; `cancel` stops it in that time). An organization
        that asks for an admin as well still gets its admin: the change then waits like any other."""
        return self._direct(principal, self.propose(principal, connection_id, kind, payload, base_version=base_version, key='direct-' + uuid.uuid4().hex, ask=False),
                            screen, delay_seconds)

    def undo_direct(self, principal: Principal, action_id: str, *, screen: str) -> dict:
        """The customer pressed Undo on a finished change: its inverse, approved by that press."""
        return self._direct(principal, self.undo(principal, action_id, ask=False), screen, 0)

    def _direct(self, principal, action, screen, delay_seconds):
        if screen not in DIRECT_SCREENS or type(delay_seconds) is not int or not 0 <= delay_seconds <= 60:
            raise ValueError('invalid request')
        approved = self.approve(principal, action['id'], action['payload_hash'])
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            con.execute('UPDATE actions SET direct_screen=?,retry_after_epoch=?,updated_epoch=? WHERE account_id=? AND id=?',
                        (screen, now + delay_seconds if delay_seconds else None, now, principal.account_id, action['id']))
        if approved['state'] == 'approved' and not delay_seconds:
            self.execute(principal.account_id, action['id'])
        return self.get(principal, action['id'])

    def cancel(self, principal: Principal, action_id: str) -> dict:
        """Stop an approved change that has not been sent yet (the customer's "Undo send" inside its wait). Nothing reaches the provider."""
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            row = self._row(con, principal.account_id, action_id)
            if row['state'] != 'approved' or not row['retry_after_epoch'] or row['retry_after_epoch'] <= self.clock():
                raise Conflict('this change can no longer be stopped')
            self._end(con, row, 'declined', 'cancelled_by_customer')
            self.coordinator._audit(con, principal.account_id, principal.actor_id, action_id, 'action.cancel', 'completed')
        return self.get(principal, action_id)

    # -- approving ---------------------------------------------------------------------------------------------------------------------------
    def approve(self, principal: Principal, action_id: str, approved_hash: str, *, member_account: str | None = None) -> dict:
        """Approve exactly the payload with this hash. `member_account`: an admin approving a member's change, where their organization asks for an admin as well."""
        account = principal.account_id
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            role = permissions.member_role(con, principal.account_id, principal.actor_id)
            if member_account and member_account != principal.account_id:
                if role not in permissions.MANAGERS or permissions.organization_of(con, member_account) != permissions.organization_of(con, principal.account_id):
                    raise NotFound('unavailable')
                account = member_account
            row = self._row(con, account, action_id)
            if row['state'] != 'proposed':
                raise Conflict('this change is not waiting for approval')
            if row['workflow_id']:
                raise Conflict('this step is approved with its workflow')
            if not isinstance(approved_hash, str) or approved_hash != row['payload_hash'] or payload_hash(json.loads(row['payload_json'])) != row['payload_hash']:
                raise Conflict('the change is not the one that was shown: review it again')        # an approval is for one exact payload
            waiting = con.execute("SELECT expires_epoch FROM handoffs WHERE account_id=? AND action_id=? AND state='waiting'", (account, row['id'])).fetchone()
            if waiting and waiting['expires_epoch'] <= self.clock():
                raise Conflict('this change waited too long and has expired')
            now = int(self.clock())
            mine = account == principal.account_id
            approved_by = row['approved_by'] or (principal.actor_id if mine else None)
            admin_by = row['admin_approved_by'] or (principal.actor_id if role in permissions.MANAGERS else None)
            complete = bool(approved_by) and (not row['needs_admin'] or bool(admin_by))      # the person whose change it is always approves it; an admin's word is an addition, never a replacement
            con.execute('UPDATE actions SET approved_by=?,admin_approved_by=?,state=?,approved_epoch=?,approval_expires_epoch=?,updated_epoch=? WHERE account_id=? AND id=?',
                        (approved_by, admin_by, 'approved' if complete else 'proposed', now if complete else None, now + APPROVAL_SECONDS if complete else None, now, account, row['id']))
            if complete:
                self.handoffs.settle(con, account, action_id=row['id'], answer={'decision': 'approved'})
            self.coordinator._audit(con, account, principal.actor_id, row['id'], 'action.approve', 'completed')
            return self.public(self._row(con, account, row['id']))

    def decline(self, principal: Principal, action_id: str) -> dict:
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            row = self._row(con, principal.account_id, action_id)
            if row['state'] not in ('proposed', 'approved'):
                raise Conflict('this change can no longer be declined')
            now = int(self.clock())
            con.execute("UPDATE actions SET state='declined',updated_epoch=? WHERE account_id=? AND id=? AND state IN ('proposed','approved')", (now, principal.account_id, row['id']))
            self.handoffs.settle(con, principal.account_id, action_id=row['id'], answer={'decision': 'declined'})
            self.coordinator._audit(con, principal.account_id, principal.actor_id, row['id'], 'action.decline', 'completed')
            return self.public(self._row(con, principal.account_id, row['id']))

    def awaiting_admin(self, principal: Principal) -> list[dict]:
        """For an admin: changes of members of their organization that wait for an admin's approval."""
        with self.store.connect() as con:
            require(principal, 'policy.change', con=con)
            org = permissions.organization_of(con, principal.account_id)
            rows = con.execute("""SELECT x.* FROM actions x JOIN accounts a ON a.id=x.account_id WHERE a.organization_id=? AND x.state='proposed' AND x.needs_admin=1
                AND x.admin_approved_by IS NULL ORDER BY x.created_epoch LIMIT 50""", (org,)).fetchall()
            return [{**self.public(r), 'account_id': r['account_id']} for r in rows]

    # -- automatic approval --------------------------------------------------------------------------------------------------------------------
    def set_auto(self, principal: Principal, connection_id: str, kind: str, enabled: bool, *, include_irreversible: bool = False) -> list[dict]:
        if type(enabled) is not bool or type(include_irreversible) is not bool:
            raise ValueError('invalid setting')
        declaration = self.client.declaration_for(principal, connection_id)
        write_kind = declaration.write_kind(kind)
        if write_kind is None:
            raise ValueError('unknown kind of change')
        if enabled and not write_kind.undo and not include_irreversible:
            raise ValueError('this kind of change cannot be undone: say so explicitly to let it go ahead without asking')
        with self.coordinator.transaction() as con:
            require(principal, 'action.approve', con=con)
            if enabled and max((organizations.write_rule(con, principal.account_id, n) for n in (write_kind.policy_kind, kind)), key=organizations.WRITE_RULES.index) != 'allowed':
                raise Conflict('your organization decides this kind of change')
            if enabled:
                con.execute('INSERT OR REPLACE INTO action_auto_approvals(account_id,connection_id,kind,include_irreversible,set_by,set_epoch) VALUES (?,?,?,?,?,?)',
                            (principal.account_id, connection_id, kind, 1 if include_irreversible else 0, principal.actor_id, int(self.clock())))
            else:
                con.execute('DELETE FROM action_auto_approvals WHERE account_id=? AND connection_id=? AND kind=?', (principal.account_id, connection_id, kind))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, connection_id, 'action.auto.' + ('on' if enabled else 'off'), 'completed')
        return self.auto(principal, connection_id)

    def auto(self, principal: Principal, connection_id: str) -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            return [{'kind': r['kind'], 'include_irreversible': bool(r['include_irreversible'])}
                    for r in con.execute('SELECT kind,include_irreversible FROM action_auto_approvals WHERE account_id=? AND connection_id=? ORDER BY kind', (principal.account_id, connection_id))]

    # -- executing: at most once ---------------------------------------------------------------------------------------------------------------
    def execute(self, account_id: str, action_id: str) -> str:
        """Send one approved action. -> its state afterwards. Safe to call any number of times, from any number of workers: only the call that moves it from "approved" to
        "executing" sends anything."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT * FROM actions WHERE account_id=? AND id=?', (account_id, action_id)).fetchone()
            if not row or row['state'] != 'approved':
                return row['state'] if row else 'missing'
            payload = json.loads(row['payload_json'])
            if payload_hash(payload) != row['payload_hash']:
                return self._end(con, row, 'failed', 'payload_changed')
            if not self.writes_on(account_id, self.connectors.service_of(account_id, row['connection_id'])):
                return self._end(con, row, 'failed', 'refused')          # the owner switched changes off after this was prepared: it does not go out
            if not row['workflow_id'] and (row['approval_expires_epoch'] or 0) < now:
                return self._end(con, row, 'expired', 'approval_expired')
            if row['retry_after_epoch'] and row['retry_after_epoch'] > now:
                return 'approved'
            if con.execute("UPDATE actions SET state='executing',attempts=attempts+1,updated_epoch=? WHERE account_id=? AND id=? AND state='approved'", (now, account_id, action_id)).rowcount != 1:
                return 'executing'
            attempt = row['attempts'] + 1
        principal = Principal(account_id, row['actor_id'], 'customer')
        operation, sent = None, False
        try:
            ready = self.client.prepare(principal, row['connection_id'], row['kind'], payload)      # everything is checked again NOW: role, connection, policy, grant, the record
            adapter, write_kind, current = ready['adapter'], ready['kind'], ready['before']
            if write_kind.needs_version and str((current or {}).get('version')) != str(row['base_version']):
                raise ConnectorFault('conflict')
            # Captured and stored BEFORE the forward write: what the inverse needs, and the payload of every registered compensation.
            undo = adapter.undo_payload(row['kind'], payload, current) if write_kind.undo else None
            compensations = {c: adapter.compensation_payload(row['kind'], c, payload, None) for c in write_kind.compensations}
            with self.coordinator.transaction() as con:
                con.execute('UPDATE actions SET undo_payload_json=?,compensation_json=?,before_json=coalesce(?,before_json) WHERE account_id=? AND id=?',
                            (None if undo is None else json.dumps(undo), json.dumps({k: v for k, v in compensations.items() if v is not None}), json.dumps(current) if current else None,
                             account_id, action_id))
            destination = json.loads(row['preview_json'])['destination']
            operation = self.connectors.begin_operation(principal, row['connection_id'], row['kind'], f'{row["idempotency_key"]}-a{attempt}', payload, target=destination,
                                                        authorization={'payload_hash': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),      # the operation record's own digest of the same payload
                                                                       'target': destination[:300], 'expires_epoch': max(row['approval_expires_epoch'] or 0, now + 60)})
            with self.coordinator.transaction() as con:
                con.execute('UPDATE actions SET operation_id=? WHERE account_id=? AND id=?', (operation, account_id, action_id))
            sent = True                                        # from here on something may have left: a failure without an answer is "unknown", never "nothing happened"
            result = self.client.write(principal, row['connection_id'], row['kind'], payload, idempotency_key=row['idempotency_key'], base_version=row['base_version'])
        except Unanswered:
            return self._uncertain(principal, account_id, action_id, operation)
        except ConnectorFault as fault:
            self._finish_operation(principal, operation, 'failed')
            return self._fault(account_id, action_id, fault, payload)
        except (Conflict, NotFound, permissions.NotPermitted):
            self._finish_operation(principal, operation, 'failed')
            return self._fault(account_id, action_id, ConnectorFault('refused'), payload)
        except Exception:
            if not sent:                                       # it broke before anything was sent: nothing happened, and it is said so
                self._finish_operation(principal, operation, 'failed')
                return self._fault(account_id, action_id, ConnectorFault('invalid'), payload)
            return self._uncertain(principal, account_id, action_id, operation)       # something broke after the send may have left: the outcome is unknown, so it is read back
        self._finish_operation(principal, operation, 'completed', result.get('receipt'))
        return self._succeeded(principal, account_id, action_id, result)

    def _finish_operation(self, principal, operation, outcome, receipt=None):
        if operation is None:
            return
        try:
            self.connectors.finish_operation(principal, operation, outcome, str(receipt)[:200] if receipt else None)
        except Exception:
            pass                                   # the operation was cancelled by a removal in the meantime: the action row carries the outcome

    def _end(self, con, row, state, reason):
        con.execute('UPDATE actions SET state=?,ended_reason=?,updated_epoch=? WHERE account_id=? AND id=?', (state, reason, int(self.clock()), row['account_id'], row['id']))
        return state

    def _uncertain(self, principal, account_id, action_id, operation):
        self._finish_operation(principal, operation, 'uncertain')
        with self.coordinator.transaction() as con:
            con.execute("UPDATE actions SET state='uncertain',updated_epoch=? WHERE account_id=? AND id=? AND state='executing'", (int(self.clock()), account_id, action_id))
        return 'uncertain'

    def _fault(self, account_id, action_id, fault, payload):
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            row = con.execute('SELECT * FROM actions WHERE account_id=? AND id=?', (account_id, action_id)).fetchone()
            if fault.kind == 'retry_later' and row['attempts'] < MAX_ATTEMPTS:
                wait = max(5, (fault.retry_at or now + 5) - now)
                # Nothing was changed and the provider said "later": it goes back to approved and is sent again then. The approval is kept for that long.
                con.execute("UPDATE actions SET state='approved',retry_after_epoch=?,approval_expires_epoch=max(coalesce(approval_expires_epoch,0),?),updated_epoch=? WHERE account_id=? AND id=?",
                            (now + wait, now + wait + APPROVAL_SECONDS, now, account_id, action_id))
                return 'approved'
            conflict = None
            if fault.kind == 'conflict':
                principal = Principal(account_id, row['actor_id'], 'customer')
                target = json.loads(row['target_json']) if row['target_json'] else None
                try:
                    current = self.client.current(principal, row['connection_id'], *target) if target else None
                except Exception:
                    current = None
                # The customer sees their version (what the change was prepared against), the version there is now, and the change that was proposed.
                conflict = {'yours': json.loads(row['before_json']) if row['before_json'] else None, 'current': current, 'proposed': payload}
            con.execute("UPDATE actions SET state='failed',ended_reason=?,conflict_json=?,updated_epoch=? WHERE account_id=? AND id=?",
                        (fault.kind, json.dumps(conflict) if conflict else None, now, account_id, action_id))
            return 'failed'

    def _succeeded(self, principal, account_id, action_id, result) -> str:
        now = int(self.clock())
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM actions WHERE account_id=? AND id=?', (account_id, action_id)).fetchone()
        payload = json.loads(row['payload_json'])
        declaration = self.connectors.declared(row['provider'])
        adapter = self.connectors.registry.adapter(row['provider'])
        write_kind = declaration.write_kind(row['kind'])
        undo = json.loads(row['undo_payload_json']) if row['undo_payload_json'] else None
        if write_kind.undo:
            undo = adapter.undo_after(row['kind'], undo, result)
        compensations = {c: adapter.compensation_payload(row['kind'], c, payload, result) for c in write_kind.compensations}
        # Verification: read the result back and compare it with what was sent. A mismatch is recorded, never hidden.
        verified, note = None, None
        try:
            touched = result.get('record') or {}
            found = self.client.current(principal, row['connection_id'], touched.get('kind'), touched.get('id')) if touched.get('id') else None
            verified, note = adapter.verify(row['kind'], payload, found)
        except Exception:
            verified, note = None, 'the result could not be read back'
        with self.coordinator.transaction() as con:
            con.execute('''UPDATE actions SET state='done',receipt=?,result_json=?,undo_payload_json=?,compensation_json=?,verified=?,verify_note=?,executed_epoch=?,undo_until_epoch=?,
                updated_epoch=? WHERE account_id=? AND id=? AND state IN ('executing','uncertain')''',
                        (str(result.get('receipt') or '')[:200], json.dumps({'record': result.get('record')}), None if undo is None else json.dumps(undo),
                         json.dumps({k: v for k, v in compensations.items() if v is not None}), None if verified is None else int(bool(verified)), str(note or '')[:200], now,
                         now + write_kind.undo_seconds if write_kind.undo else None, now, account_id, action_id))
            if row['undo_of']:
                con.execute("UPDATE actions SET state='undone',updated_epoch=? WHERE account_id=? AND id=? AND state='done'", (now, account_id, row['undo_of']))
            if row['compensates']:
                con.execute("UPDATE actions SET state='compensated',updated_epoch=? WHERE account_id=? AND id=? AND state='done'", (now, account_id, row['compensates']))
            self.coordinator._audit(con, account_id, row['actor_id'], action_id, 'action.execute', 'completed')
        return 'done'

    def reconcile(self, account_id: str, action_id: str) -> str:
        """An action whose outcome is unknown: read it back. Found: it happened once, and is finished as a success. Not found: it did not happen, and may be sent (once more).
        The provider cannot be asked right now: it stays unknown and is asked again later. It is never sent again without knowing."""
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM actions WHERE account_id=? AND id=?', (account_id, action_id)).fetchone()
        if not row or row['state'] != 'uncertain':
            return row['state'] if row else 'missing'
        principal = Principal(account_id, row['actor_id'], 'customer')
        try:
            found = self.client.find_effect(principal, row['connection_id'], row['kind'], json.loads(row['payload_json']), idempotency_key=row['idempotency_key'])
        except ConnectorFault as fault:
            if fault.kind in ('refused', 'not_found', 'needs_customer'):       # the connection is gone or closed: it can never be read back, and it is said so
                with self.coordinator.transaction() as con:
                    con.execute("UPDATE actions SET ended_reason=?,updated_epoch=? WHERE account_id=? AND id=?", (fault.kind, int(self.clock()), account_id, action_id))
            return 'uncertain'
        except Exception:
            return 'uncertain'
        if found:
            if row['operation_id']:
                try:
                    self.connectors.reconcile(principal, row['operation_id'], str(found.get('receipt') or 'found')[:200])
                except Exception:
                    pass
            return self._succeeded(principal, account_id, action_id, found)
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            if row['operation_id']:
                con.execute("UPDATE connector_operations SET state='failed' WHERE account_id=? AND id=? AND state='uncertain'", (account_id, row['operation_id']))
            if row['attempts'] >= MAX_ATTEMPTS:
                con.execute("UPDATE actions SET state='failed',ended_reason='retry_later',updated_epoch=? WHERE account_id=? AND id=?", (now, account_id, action_id))
                return 'failed'
            con.execute("UPDATE actions SET state='approved',approval_expires_epoch=?,updated_epoch=? WHERE account_id=? AND id=? AND state='uncertain'", (now + APPROVAL_SECONDS, now, account_id, action_id))
        return 'approved'

    def recover_stale(self) -> int:
        """Actions left "executing" by a worker that died mid-send: their outcome is unknown."""
        with self.coordinator.transaction() as con:
            return con.execute("UPDATE actions SET state='uncertain',updated_epoch=? WHERE state='executing' AND updated_epoch<?", (int(self.clock()), int(self.clock()) - STALE_SECONDS)).rowcount

    def due(self, state) -> list[tuple]:
        with self.store.connect() as con:
            extra = ' AND workflow_id IS NULL AND coalesce(retry_after_epoch,0)<=?' if state == 'approved' else ''
            return [(r[0], r[1]) for r in con.execute(f'SELECT account_id,id FROM actions WHERE state=?{extra} ORDER BY updated_epoch LIMIT 25',
                                                      (state, int(self.clock())) if extra else (state,))]

    def expire(self, account_id: str, action_id: str, reason='approval_expired'):
        with self.coordinator.transaction() as con:
            con.execute("UPDATE actions SET state='expired',ended_reason=?,updated_epoch=? WHERE account_id=? AND id=? AND state IN ('proposed','approved')",
                        (reason, int(self.clock()), account_id, action_id))

    # -- undo and compensation -----------------------------------------------------------------------------------------------------------------
    def undo(self, principal: Principal, action_id: str, *, ask=True, workflow=None) -> dict:
        """Prepare the inverse of a finished change. It is an action like any other: previewed, approved (unless `ask=False`: a workflow walking itself back), executed once,
        with a receipt. It carries the version the forward write left, so it does not overwrite a later change by somebody else."""
        with self.store.connect() as con:
            require(principal, 'action.approve', con=con)
            row = self._row(con, principal.account_id, action_id)
            taken = con.execute(f"SELECT 1 FROM actions WHERE account_id=? AND undo_of=? AND state IN ({','.join('?' * len(OPEN))},'done')", (principal.account_id, row['id'], *OPEN)).fetchone()
        if row['state'] != 'done' or not row['can_undo'] or not row['undo_payload_json'] or taken:
            raise Conflict('this change cannot be undone')
        if ask and row['undo_until_epoch'] and row['undo_until_epoch'] < self.clock():
            raise Conflict('the time in which this could be undone has passed')
        version = ((json.loads(row['result_json'] or '{}').get('record')) or {}).get('version')
        return self.propose(principal, row['connection_id'], row['undo_kind'], json.loads(row['undo_payload_json']), request_id=row['request_id'], undo_of=row['id'],
                            base_version=version, key=row['idempotency_key'] + '-undo', ask=ask, workflow=workflow)

    def compensate(self, principal: Principal, action_id: str, compensation: str, *, ask=True, workflow=None) -> dict:
        """Prepare a registered follow-up for a change that cannot be undone. Only a compensation the write kind registered, with the payload written in code."""
        with self.store.connect() as con:
            require(principal, 'action.approve', con=con)
            row = self._row(con, principal.account_id, action_id)
        prepared = json.loads(row['compensation_json'] or '{}')
        if row['state'] != 'done' or compensation not in prepared:
            raise Conflict('there is no such follow-up for this change')
        return self.propose(principal, row['connection_id'], compensation, prepared[compensation], request_id=row['request_id'], compensates=row['id'],
                            key=f'{row["idempotency_key"]}-comp-{compensation.replace(".", "_")}'[:60], ask=ask, workflow=workflow)

    def approve_internal(self, account_id: str, action_id: str):
        """A step the runner starts itself (a workflow's approved step, a reversal): approved under the workflow's own approval."""
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            con.execute("UPDATE actions SET state='approved',approved_epoch=?,approval_expires_epoch=?,updated_epoch=? WHERE account_id=? AND id=? AND state='proposed'",
                        (now, now + APPROVAL_SECONDS, now, account_id, action_id))
