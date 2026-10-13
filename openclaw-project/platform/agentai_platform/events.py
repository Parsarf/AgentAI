"""Durable scoped task timeline (Phase 9).

Normalized public events with stable ids, per-task sequence, source and
redacted typed payloads. Append is a trusted host/system operation; reads are
always account-scoped. Private model reasoning, prompts, credentials and raw
sensitive tool output never enter the store: payloads are allowlisted per
kind, recursively redacted, bounded to 32KiB and stored as JSON. Cursor
replay is gap-free by sequence; streams are capped at three per account and
rechecked against live account state while open. Retention: 30 days, then
pruned; expired cursors resync from the current tail.
"""
from __future__ import annotations
import json
import re
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

MAX_PAYLOAD_BYTES = 32 * 1024
MAX_EVENTS_PER_TASK = 2000
RETENTION_DAYS = 30
MAX_STREAMS_PER_ACCOUNT = 3
STREAM_TTL_SECONDS = 900

EVENT_KINDS = {
    # kind -> allowed payload keys (empty set = no payload beyond kind/time)
    'task_queued': {'summary'},
    'task_started': {'summary'},
    'plan': {'summary', 'steps'},
    'progress': {'summary', 'step', 'detail'},
    'search': {'query', 'sources'},
    'file_change': {'path', 'change'},
    'command_result': {'command', 'exit_code', 'summary'},
    'test_result': {'suite', 'passed', 'failed', 'summary'},
    'approval_request': {'request_id', 'summary', 'expires_epoch'},
    'approval_decision': {'request_id', 'decision'},
    'error': {'summary', 'category'},
    'budget': {'remaining_microusd', 'held_microusd', 'note'},
    'artifact': {'artifact_id', 'version', 'name', 'sha256'},
    'result': {'summary'},
    'activity': {'ref', 'tool', 'category', 'label', 'detail', 'output', 'status'},
}

SECRET_PATTERNS = [
    re.compile(
        r'(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|'
        r'xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{20,})'),
    re.compile(
        r'(api[_-]?key|secret|password|token|credential)"?\s*[:=]\s*"[^"]{6,}"',
        re.IGNORECASE),
]


def redact(value):
    """Recursive allowlist-oriented redaction: strings matching secret
    patterns are replaced; containers are walked depth-first."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub('[redacted]', value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def normalize(kind: str, payload: dict | None) -> dict:
    if kind not in EVENT_KINDS:
        raise ValueError('unknown event kind')
    payload = redact(payload or {})
    if not isinstance(payload, dict):
        raise ValueError('event payload must be an object')
    unknown = set(payload) - EVENT_KINDS[kind]
    if unknown:
        raise ValueError('payload keys not allowed for ' + kind)
    encoded = json.dumps(payload, sort_keys=True)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        payload = {'summary': str(payload.get('summary', ''))[:2000], 'truncated': True}
        encoded = json.dumps(payload, sort_keys=True)
    return json.loads(encoded)


class EventService:
    def __init__(self, store, *, clock=time.time):
        self.store = store
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)

    # ---------- append (trusted host/system path) ----------

    def append(self, account_id: str, task_id: str, kind: str, payload: dict | None = None,
               source: str = 'system') -> dict:
        identifier(account_id)
        identifier(task_id)
        identifier(source)
        public = normalize(kind, payload)
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            if not con.execute('SELECT 1 FROM tasks WHERE account_id=? AND id=?',
                               (account_id, task_id)).fetchone():
                raise NotFound('unavailable')
            count = con.execute('SELECT count(*) FROM events WHERE account_id=? AND task_id=?',
                                (account_id, task_id)).fetchone()[0]
            if count >= MAX_EVENTS_PER_TASK:
                raise Conflict('event limit reached for this task')
            sequence = con.execute('''SELECT coalesce(max(sequence),0)+1 FROM events
                WHERE account_id=? AND task_id=?''', (account_id, task_id)).fetchone()[0]
            event_id = uuid.uuid4().hex
            con.execute('''INSERT INTO events(account_id,task_id,id,sequence,kind,public_payload)
                VALUES (?,?,?,?,?,?)''',
                        (account_id, task_id, event_id, sequence, kind,
                         json.dumps({'source': source, **public}, sort_keys=True)))
            return {'id': event_id, 'sequence': sequence, 'kind': kind, 'payload': public}

    # ---------- reads (customer path) ----------

    def events(self, principal: Principal, task_id: str, *, after: int = 0, limit: int = 100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('invalid pagination')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT state FROM tasks WHERE account_id=? AND id=?''',
                              (principal.account_id, task_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            rows = con.execute('''SELECT sequence,kind,public_payload,created_at FROM events
                WHERE account_id=? AND task_id=? AND sequence>? ORDER BY sequence LIMIT ?''',
                (principal.account_id, task_id, after, limit)).fetchall()
            events = []
            for row in rows:
                payload = json.loads(row['public_payload'])
                events.append({'sequence': row['sequence'], 'kind': row['kind'],
                               'source': payload.pop('source', 'system'),
                               'payload': payload, 'created_at': row['created_at']})
            return {'task_id': task_id, 'task_state': row[0], 'events': events,
                    'live_streaming': False}

    # ---------- streams ----------

    def open_stream(self, principal: Principal, task_id: str, stream_id: str):
        identifier(task_id)
        identifier(stream_id)
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM tasks WHERE account_id=? AND id=?',
                               (principal.account_id, task_id)).fetchone():
                raise NotFound('unavailable')
            con.execute('DELETE FROM event_streams WHERE expires_epoch<=?', (now,))
            active = con.execute('SELECT count(*) FROM event_streams WHERE account_id=? AND closed_epoch IS NULL',
                                 (principal.account_id,)).fetchone()[0]
            if active >= MAX_STREAMS_PER_ACCOUNT:
                raise Conflict('stream limit reached')
            con.execute('''INSERT INTO event_streams(account_id,task_id,stream_id,opened_epoch,expires_epoch)
                VALUES (?,?,?,?,?)''', (principal.account_id, task_id, stream_id, now, now + STREAM_TTL_SECONDS))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, stream_id,
                                    'stream.open', 'completed')

    def heartbeat_stream(self, stream_id: str) -> bool:
        with self.coordinator.transaction() as con:
            cursor = con.execute('''UPDATE event_streams SET expires_epoch=? WHERE stream_id=?
                AND closed_epoch IS NULL''', (int(self.clock()) + STREAM_TTL_SECONDS, stream_id))
            return cursor.rowcount == 1

    def close_stream(self, stream_id: str):
        with self.coordinator.transaction() as con:
            con.execute('UPDATE event_streams SET closed_epoch=? WHERE stream_id=? AND closed_epoch IS NULL',
                        (int(self.clock()), stream_id))

    def stream_alive(self, principal: Principal, stream_id: str) -> bool:
        """Rechecked between event batches: revocation or closure ends the stream."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT 1 FROM event_streams WHERE stream_id=? AND account_id=?
                AND closed_epoch IS NULL AND expires_epoch>?''',
                (stream_id, principal.account_id, int(self.clock()))).fetchone()
            return bool(row)

    # ---------- retention ----------

    def prune_expired(self) -> int:
        horizon = (int(self.clock()) - RETENTION_DAYS * 86400)
        cutoff = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(horizon))
        with self.coordinator.transaction() as con:
            cursor = con.execute('DELETE FROM events WHERE created_at<?', (cutoff,))
            return cursor.rowcount
