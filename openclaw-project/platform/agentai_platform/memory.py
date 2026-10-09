"""Customer/project-scoped memory (Phase 10, NATIVE-04 / RETENTION-MEMORY).

Entries carry source/date/confidence/last-confirmed fields. Retrieval is
selective (term-index overlap, bounded count). Correction supersedes the old
entry; deletion blanks content and removes index terms immediately (backups
keep history only for their documented retention). Entries from outside
content are data: never preferences, never instructions, and returned with an
explicit ``instruction: false`` marker. Large tool output belongs in an
artifact; only a reference may be stored here.
"""
from __future__ import annotations
import re
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .security import NotFound, Principal

MAX_CONTENT = 2000
MAX_ACTIVE_PER_PROJECT = 500
MAX_RESULTS = 8
KINDS = {'preference', 'fact', 'correction', 'reference'}
SOURCES = {'customer', 'agent', 'outside'}
CONFIDENCE = {'low', 'medium', 'high'}
STOP = {'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'is', 'it', 'for', 'on', 'my', 'i'}


def terms(text: str) -> set[str]:
    return {t for t in re.findall(r'[a-z0-9]{3,}', text.lower()) if t not in STOP}


class MemoryService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def _project(self, con, principal, project_id):
        self.store._authorize(con, principal)
        identifier(project_id)
        if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                           (principal.account_id, project_id)).fetchone():
            raise NotFound('unavailable')

    def _insert(self, con, principal, project_id, kind, content, source, source_ref,
                confidence, supersedes=None):
        if kind not in KINDS or source not in SOURCES or confidence not in CONFIDENCE:
            raise ValueError('invalid memory field')
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT:
            raise ValueError('memory content must be 1-2000 characters; store large output as an artifact')
        if source == 'outside' and kind in {'preference', 'correction'}:
            raise ValueError('outside content cannot become a preference or correction')
        active = con.execute('''SELECT count(*) FROM memory_entries WHERE account_id=? AND project_id=?
            AND status='active' ''', (principal.account_id, project_id)).fetchone()[0]
        if active >= MAX_ACTIVE_PER_PROJECT and supersedes is None:
            raise ValueError('memory limit reached')
        now = int(self.clock())
        entry_id = uuid.uuid4().hex
        con.execute('''INSERT INTO memory_entries(account_id,project_id,id,kind,content,source,source_ref,
            confidence,last_confirmed_epoch,status,supersedes_id,created_epoch)
            VALUES (?,?,?,?,?,?,?,?,?,'active',?,?)''',
                    (principal.account_id, project_id, entry_id, kind, content, source,
                     str(source_ref)[:200], confidence, now, supersedes, now))
        for term in terms(content):
            con.execute('INSERT INTO memory_terms VALUES (?,?,?)', (principal.account_id, entry_id, term))
        self.coordinator._audit(con, principal.account_id, principal.actor_id, entry_id,
                                'memory.write', 'completed')
        return entry_id

    def remember(self, principal: Principal, project_id: str, content: str, *, kind='fact',
                 source='customer', source_ref='', confidence='medium') -> str:
        with self.coordinator.transaction() as con:
            self._project(con, principal, project_id)
            return self._insert(con, principal, project_id, kind, content, source, source_ref, confidence)

    def recall(self, principal: Principal, project_id: str, query: str, *, limit=MAX_RESULTS) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
            raise ValueError('invalid limit')
        wanted = terms(query)
        with self.store.connect() as con:
            self._project(con, principal, project_id)
            if not wanted:
                return []
            marks = ','.join('?' * len(wanted))
            rows = con.execute(f'''SELECT e.id,e.kind,e.content,e.source,e.confidence,
                e.last_confirmed_epoch, count(*) AS hits FROM memory_terms t
                JOIN memory_entries e ON e.account_id=t.account_id AND e.id=t.entry_id
                WHERE t.account_id=? AND e.project_id=? AND e.status='active' AND t.term IN ({marks})
                GROUP BY e.id ORDER BY hits DESC, e.last_confirmed_epoch DESC LIMIT ?''',
                               (principal.account_id, project_id, *sorted(wanted), limit)).fetchall()
            return [{'id': r['id'], 'kind': r['kind'], 'content': r['content'], 'source': r['source'],
                     'confidence': r['confidence'], 'last_confirmed_epoch': r['last_confirmed_epoch'],
                     'instruction': False} for r in rows]

    def confirm(self, principal: Principal, project_id: str, entry_id: str) -> None:
        with self.coordinator.transaction() as con:
            self._project(con, principal, project_id)
            cur = con.execute('''UPDATE memory_entries SET last_confirmed_epoch=? WHERE account_id=?
                AND project_id=? AND id=? AND status='active' ''',
                              (int(self.clock()), principal.account_id, project_id, entry_id))
            if cur.rowcount != 1:
                raise NotFound('unavailable')

    def correct(self, principal: Principal, project_id: str, entry_id: str, content: str) -> str:
        with self.coordinator.transaction() as con:
            self._project(con, principal, project_id)
            row = con.execute('''SELECT kind FROM memory_entries WHERE account_id=? AND project_id=?
                AND id=? AND status='active' ''', (principal.account_id, project_id, entry_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            new_id = self._insert(con, principal, project_id, row['kind'], content, 'customer',
                                  'correction of ' + entry_id, 'high', supersedes=entry_id)
            self._retire(con, principal, entry_id, 'superseded')
            return new_id

    def forget(self, principal: Principal, project_id: str, entry_id: str) -> None:
        with self.coordinator.transaction() as con:
            self._project(con, principal, project_id)
            if not con.execute('''SELECT 1 FROM memory_entries WHERE account_id=? AND project_id=?
                AND id=? AND status!='deleted' ''', (principal.account_id, project_id, entry_id)).fetchone():
                raise NotFound('unavailable')
            self._retire(con, principal, entry_id, 'deleted')

    def _retire(self, con, principal, entry_id, status):
        """Blank content and drop index terms so retired text is never retrievable."""
        con.execute('DELETE FROM memory_terms WHERE account_id=? AND entry_id=?',
                    (principal.account_id, entry_id))
        con.execute('''UPDATE memory_entries SET status=?, content='', deleted_epoch=?
            WHERE account_id=? AND id=?''', (status, int(self.clock()), principal.account_id, entry_id))
        self.coordinator._audit(con, principal.account_id, principal.actor_id, entry_id,
                                'memory.' + status, 'completed')
