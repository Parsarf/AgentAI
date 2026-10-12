"""Account-scoped reusable skills (Phase 10, NATIVE-07).

Skills are versioned within one tenant. Revisions are *proposed* and applied
only by an explicit customer approval; proposals originating from outside
content are refused so hostile pages/repos cannot create or change skills.
"""
from __future__ import annotations
import hashlib
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

MAX_SKILLS = 50
ORIGINS = {'customer', 'agent'}


class SkillService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    def create(self, principal: Principal, name: str, body: str) -> str:
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError('invalid skill name')
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if con.execute('SELECT count(*) FROM skills WHERE account_id=?',
                           (principal.account_id,)).fetchone()[0] >= MAX_SKILLS:
                raise Conflict('skill limit reached')
            if con.execute('SELECT 1 FROM skills WHERE account_id=? AND name=?',
                           (principal.account_id, name)).fetchone():
                raise Conflict('skill exists')
            skill_id = uuid.uuid4().hex
            now = int(self.clock())
            con.execute('INSERT INTO skills VALUES (?,?,?,?)', (principal.account_id, skill_id, name, now))
            self._version(con, principal, skill_id, 1, body, 'active', principal.actor_id)
            self.coordinator._audit(con, principal.account_id, principal.actor_id, skill_id,
                                    'skill.create', 'completed')
            return skill_id

    def _version(self, con, principal, skill_id, version, body, status, proposer):
        if not isinstance(body, str) or not 1 <= len(body) <= 20000:
            raise ValueError('skill body must be 1-20000 characters')
        con.execute('INSERT INTO skill_versions VALUES (?,?,?,?,?,?,?,?)',
                    (principal.account_id, skill_id, version, body,
                     hashlib.sha256(body.encode()).hexdigest(), status, proposer, int(self.clock())))

    def _exists(self, con, principal, skill_id):
        self.store._authorize(con, principal)
        identifier(skill_id)
        if not con.execute('SELECT 1 FROM skills WHERE account_id=? AND id=?',
                           (principal.account_id, skill_id)).fetchone():
            raise NotFound('unavailable')

    def list(self, principal: Principal, query: str = '') -> list[dict]:
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('''SELECT s.id,s.name,v.version FROM skills s JOIN skill_versions v
                ON v.account_id=s.account_id AND v.skill_id=s.id AND v.status='active'
                WHERE s.account_id=? AND s.name LIKE ? ESCAPE '\\' ORDER BY s.name''',
                               (principal.account_id,
                                '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')).fetchall()
            return [dict(r) for r in rows]

    def run(self, principal: Principal, skill_id: str) -> dict:
        """Return the active version's body for use; audited."""
        with self.coordinator.transaction() as con:
            self._exists(con, principal, skill_id)
            row = con.execute('''SELECT version,body,sha256 FROM skill_versions WHERE account_id=?
                AND skill_id=? AND status='active' ''', (principal.account_id, skill_id)).fetchone()
            self.coordinator._audit(con, principal.account_id, principal.actor_id, skill_id,
                                    'skill.run', 'completed')
            return dict(row)

    def propose_revision(self, principal: Principal, skill_id: str, body: str, *, origin='agent') -> int:
        if origin not in ORIGINS:
            raise ValueError('revisions from outside content are refused')
        with self.coordinator.transaction() as con:
            self._exists(con, principal, skill_id)
            version = con.execute('''SELECT max(version)+1 FROM skill_versions WHERE account_id=?
                AND skill_id=?''', (principal.account_id, skill_id)).fetchone()[0]
            self._version(con, principal, skill_id, version, body, 'proposed', origin)
            self.coordinator._audit(con, principal.account_id, principal.actor_id, skill_id,
                                    'skill.propose', 'completed')
            return version

    def proposals(self, principal: Principal, skill_id: str) -> list[dict]:
        with self.store.connect() as con:
            self._exists(con, principal, skill_id)
            active = con.execute('''SELECT body FROM skill_versions WHERE account_id=? AND skill_id=?
                AND status='active' ''', (principal.account_id, skill_id)).fetchone()['body']
            rows = con.execute('''SELECT version,body,proposed_by FROM skill_versions WHERE account_id=?
                AND skill_id=? AND status='proposed' ORDER BY version''',
                               (principal.account_id, skill_id)).fetchall()
            return [{**dict(r), 'current_body': active} for r in rows]

    def decide(self, principal: Principal, skill_id: str, version: int, approve: bool) -> None:
        with self.coordinator.transaction() as con:
            self._exists(con, principal, skill_id)
            if not con.execute('''SELECT 1 FROM skill_versions WHERE account_id=? AND skill_id=?
                AND version=? AND status='proposed' ''', (principal.account_id, skill_id, version)).fetchone():
                raise NotFound('unavailable')
            if approve:
                con.execute('''UPDATE skill_versions SET status='superseded' WHERE account_id=?
                    AND skill_id=? AND status='active' ''', (principal.account_id, skill_id))
            con.execute('UPDATE skill_versions SET status=? WHERE account_id=? AND skill_id=? AND version=?',
                        ('active' if approve else 'rejected', principal.account_id, skill_id, version))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, skill_id,
                                    'skill.approve' if approve else 'skill.reject', 'completed')
