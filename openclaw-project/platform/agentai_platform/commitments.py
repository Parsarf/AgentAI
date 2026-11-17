"""Decisions and commitments (roadmap #43): what was promised or decided, who owns it, when it is due, where it came from, and whether it is still open.

* The customer adds one in the app, or their assistant records one with a tool.
* One found in OUTSIDE content (an email, a document, a meeting's notes) is only ever PROPOSED: it shows in the list as "suggested" and counts once the customer
  confirms it. The assistant cannot confirm it for them (shared-context rule 5: proposals from outside content are never applied without the customer).
* Every change is kept in the row's history (who, what, when), and the item points back at its source so the list can open it.
* Phase 7 follow-ups build on this table.

Scoped by the verified principal's account. Stdlib only.
"""
from __future__ import annotations
import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

STATES = ('proposed', 'open', 'done', 'dropped')
SOURCE_KINDS = ('conversation', 'email', 'document', 'meeting', 'customer')
OUTSIDE = ('email', 'document', 'meeting')
MAX_OPEN = 2000
MAX_HISTORY = 50


def due(value, zone_name):
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' in the customer's timezone -> (epoch, has_time). None -> (None, False)."""
    if value in (None, ''):
        return None, False
    try:
        zone = ZoneInfo(zone_name or 'UTC')
    except Exception:
        raise ValueError('invalid timezone')
    for fmt, has_time in (('%Y-%m-%d %H:%M', True), ('%Y-%m-%dT%H:%M', True), ('%Y-%m-%d', False)):
        try:
            moment = datetime.strptime(str(value), fmt).replace(tzinfo=zone)
            if not has_time:
                moment = moment.replace(hour=23, minute=59)
            return int(moment.timestamp()), has_time
        except ValueError:
            continue
    raise ValueError('invalid due date')


def _source(kind, ref) -> str:
    if kind not in SOURCE_KINDS:
        raise ValueError('invalid source')
    ref = ref or {}
    if not isinstance(ref, dict) or len(json.dumps(ref)) > 1000 or any(not isinstance(k, str) or not isinstance(v, (str, int)) for k, v in ref.items()):
        raise ValueError('invalid source')
    allowed = {'conversation': ('conversation', 'request'), 'email': ('account', 'thread', 'message'), 'document': ('source_id', 'passage_id'),
               'meeting': ('account', 'calendar', 'event'), 'customer': ()}[kind]
    return json.dumps({k: str(v)[:300] for k, v in ref.items() if k in allowed})


class CommitmentService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    @staticmethod
    def public(row) -> dict:
        return {'id': row['id'], 'kind': row['kind'], 'what': row['what'], 'owner': row['owner'], 'due_epoch': row['due_epoch'], 'due_zone': row['due_zone'],
                'due_has_time': bool(row['due_has_time']), 'source_kind': row['source_kind'], 'source': json.loads(row['source_json']), 'origin': row['origin'],
                'state': row['state'], 'suggested': row['state'] == 'proposed', 'created_epoch': row['created_epoch'], 'updated_epoch': row['updated_epoch'],
                'history': json.loads(row['history_json'])}

    def list(self, principal: Principal, *, state=None, person=None) -> dict:
        if state is not None and state not in STATES + ('active',):
            raise ValueError('invalid state')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            require(principal, 'task.read', con=con)
            where, args = ['account_id=?'], [principal.account_id]
            if state == 'active':
                where.append("state IN ('proposed','open')")
            elif state:
                where.append('state=?'); args.append(state)
            if person:
                where.append('instr(lower(owner),?)>0'); args.append(str(person).lower()[:200])
            rows = con.execute(f"SELECT * FROM commitments WHERE {' AND '.join(where)} ORDER BY state!='proposed', due_epoch IS NULL, due_epoch, created_epoch DESC LIMIT 500", args).fetchall()
        items = [self.public(r) for r in rows]
        return {'items': items, 'counts': {s: sum(1 for i in items if i['state'] == s) for s in STATES}}

    def record(self, principal: Principal, *, what, owner='', due_on=None, zone='UTC', source_kind='customer', source=None, kind='commitment', by='customer', request_id=None) -> dict:
        """`by`: 'customer' (they typed it in the app or told the assistant directly) or 'assistant'. Anything from outside content is a suggestion until confirmed."""
        if not isinstance(what, str) or not what.strip() or len(what) > 500 or not isinstance(owner, str) or len(owner) > 200 or kind not in ('commitment', 'decision'):
            raise ValueError('invalid commitment')
        due_epoch, has_time = due(due_on, zone)
        origin = 'outside' if source_kind in OUTSIDE else 'customer'
        state = 'proposed' if origin == 'outside' else 'open'
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'task.run', con=con)
            if con.execute("SELECT count(*) FROM commitments WHERE account_id=? AND state IN ('proposed','open')", (principal.account_id,)).fetchone()[0] >= MAX_OPEN:
                raise Conflict('too many open commitments')
            twin = con.execute("SELECT * FROM commitments WHERE account_id=? AND lower(what)=lower(?) AND state IN ('proposed','open')", (principal.account_id, what.strip())).fetchone()
            if twin is not None:
                return self.public(twin)
            item = uuid.uuid4().hex
            history = [{'at': now, 'by': by, 'change': 'suggested' if state == 'proposed' else 'recorded'}]
            con.execute('''INSERT INTO commitments(account_id,id,kind,what,owner,due_epoch,due_zone,due_has_time,source_kind,source_json,origin,state,request_id,created_epoch,
                updated_epoch,history_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (principal.account_id, item, kind, what.strip(), owner.strip(), due_epoch, zone if due_epoch else None, int(has_time), source_kind, _source(source_kind, source),
                         origin, state, request_id, now, now, json.dumps(history)))
            return self.public(con.execute('SELECT * FROM commitments WHERE account_id=? AND id=?', (principal.account_id, item)).fetchone())

    def change(self, principal: Principal, item_id, *, state=None, what=None, owner=None, due_on=..., zone=None, by='customer') -> dict:
        """Confirm a suggestion (state 'open'), close one ('done', 'dropped'), or edit it. The assistant may close or edit what is open; only the customer confirms."""
        if state is not None and state not in ('open', 'done', 'dropped'):
            raise ValueError('invalid state')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'task.run', con=con)
            row = con.execute('SELECT * FROM commitments WHERE account_id=? AND id=?', (principal.account_id, identifier(item_id))).fetchone()
            if row is None:
                raise NotFound('unavailable')
            if row['state'] == 'proposed' and state is not None and state != 'dropped' and by != 'customer':
                raise PermissionError('only the customer confirms a suggestion')
            changes = {}
            if state is not None and state != row['state']:
                changes['state'] = state
            if what is not None:
                if not isinstance(what, str) or not what.strip() or len(what) > 500:
                    raise ValueError('invalid commitment')
                changes['what'] = what.strip()
            if owner is not None:
                if not isinstance(owner, str) or len(owner) > 200:
                    raise ValueError('invalid owner')
                changes['owner'] = owner.strip()
            if due_on is not ...:
                epoch, has_time = due(due_on, zone or row['due_zone'] or 'UTC')
                changes.update({'due_epoch': epoch, 'due_has_time': int(has_time), 'due_zone': (zone or row['due_zone'] or 'UTC') if epoch else None})
            if not changes:
                return self.public(row)
            history = json.loads(row['history_json'])[-(MAX_HISTORY - 1):]
            history.append({'at': now, 'by': by, 'change': 'confirmed' if changes.get('state') == 'open' and row['state'] == 'proposed' else changes.get('state', 'edited'),
                            'fields': sorted(k for k in changes if k != 'state')})
            sets = ','.join(f'{k}=?' for k in changes)
            con.execute(f'UPDATE commitments SET {sets},updated_epoch=?,history_json=? WHERE account_id=? AND id=?', (*changes.values(), now, json.dumps(history), principal.account_id, row['id']))
            return self.public(con.execute('SELECT * FROM commitments WHERE account_id=? AND id=?', (principal.account_id, row['id'])).fetchone())

    def with_people(self, principal: Principal, people) -> list:
        """Open commitments that name any of these people as owner (for the meeting brief, #58)."""
        names = [str(p).lower()[:200] for p in people if p][:30]
        if not names:
            return []
        out = []
        for item in self.list(principal, state='active')['items']:
            owner = item['owner'].lower()
            if owner and any(n in owner or owner in n for n in names):
                out.append(item)
        return out[:20]
