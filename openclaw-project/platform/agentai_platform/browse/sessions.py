"""More than one browser job for one request (the assistant may call the browser tool several times in one run).

Session 1 is the request's own job: its job id IS the request id and it is recorded in browse_runs/browse_steps exactly as it always was.
A later session gets a job id of its own, derived from the request id, because the browse service, its run folders and the runner's container command
all insist on a 32-character hex id. Everything customer-facing (Live view URLs, steps) keeps using the request id; only the calls to the browse service
use the job id of the session that is running.
"""
from __future__ import annotations
import hashlib


def job_id(request_id: str, session: int = 1) -> str:
    """The id the browse service knows this session by. Session 1 is the request id itself; the others are 32 hex characters derived from it (stable, so a retried
    start is the idempotent no-op the service already makes it)."""
    if session <= 1:
        return request_id
    return hashlib.sha256(f'{request_id}:{int(session)}'.encode()).hexdigest()[:32]


def offset(con, account_id: str, request_id: str) -> int:
    """Steps of this request already recorded: the next session's steps continue after them."""
    row = con.execute('SELECT MAX(n) FROM browse_steps WHERE account_id=? AND request_id=?', (account_id, request_id)).fetchone()
    return int(row[0] or 0)


def register(con, account_id: str, request_id: str, session: int, now: int) -> tuple[str, int]:
    """Record session n >= 2 (idempotent) -> (job id, step offset). Session 1 needs no row."""
    if session <= 1:
        return request_id, 0
    row = con.execute('SELECT job_id,n_offset FROM browse_sessions WHERE account_id=? AND request_id=? AND session=?', (account_id, request_id, session)).fetchone()
    if row:
        return row[0], int(row[1])
    job, base = job_id(request_id, session), offset(con, account_id, request_id)
    con.execute('INSERT INTO browse_sessions(account_id,request_id,session,job_id,n_offset,created_epoch) VALUES (?,?,?,?,?,?)', (account_id, request_id, session, job, base, now))
    return job, base


def latest(con, account_id: str, request_id: str) -> tuple[str, int]:
    """(job id, step offset) of the newest session of this request: the one the Live view should show. A request with one session -> (request id, 0)."""
    row = con.execute('SELECT job_id,n_offset FROM browse_sessions WHERE account_id=? AND request_id=? ORDER BY session DESC LIMIT 1', (account_id, request_id)).fetchone()
    return (row[0], int(row[1])) if row else (request_id, 0)
