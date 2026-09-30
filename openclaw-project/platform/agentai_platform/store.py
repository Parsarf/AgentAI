from __future__ import annotations
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
from .security import Principal, NotFound, require_customer

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

class Store:
    def __init__(self, path: Path): self.path = Path(path)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True, timeout=2, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=2000")
        try: yield con
        finally: con.close()

    def initialize(self):
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink(): raise ValueError("unsafe state path")
        if self.path.parent.stat().st_mode & 0o077: raise ValueError("state directory must be private")
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        os.close(fd)
        if self.path.stat().st_mode & 0o077: raise ValueError("database must be private")
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            con.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))")
            applied = {row["version"]:row["checksum"] for row in con.execute("SELECT version,checksum FROM schema_migrations")}
            known={f.name for f in MIGRATIONS.glob("*.sql")}
            if set(applied)-known: raise ValueError("database newer than application")
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                source=migration.read_text();digest=hashlib.sha256(source.encode()).hexdigest()
                if migration.name in applied:
                    if applied[migration.name]!=digest: raise ValueError("migration checksum changed")
                    continue
                con.execute("BEGIN IMMEDIATE")
                try:
                    buf=""
                    for line in source.splitlines(keepends=True):
                        buf+=line
                        if sqlite3.complete_statement(buf): con.execute(buf);buf=""
                    if buf.strip(): raise ValueError("incomplete migration")
                    con.execute("INSERT INTO schema_migrations(version,checksum) VALUES (?,?)",(migration.name,digest))
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK");raise

    def ready(self) -> bool:
        try:
            with self.connect() as con:
                applied={row["version"]:row["checksum"] for row in con.execute("SELECT version,checksum FROM schema_migrations")}
                expected={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in MIGRATIONS.glob("*.sql")}
                return bool(expected) and applied==expected and con.execute("PRAGMA foreign_keys").fetchone()[0]==1 and con.execute("PRAGMA quick_check").fetchone()[0]=="ok" and not con.execute("PRAGMA foreign_key_check").fetchall()
        except (sqlite3.Error,OSError): return False

    def _authorize(self, con, principal: Principal):
        require_customer(principal)
        row=con.execute("SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account_id WHERE m.account_id=? AND m.actor_id=? AND m.role='customer' AND m.status='active' AND a.status='active'",(principal.account_id,principal.actor_id)).fetchone()
        if not row: raise NotFound("unavailable")

    def list_projects(self, principal: Principal) -> list[dict]:
        with self.connect() as con:
            self._authorize(con,principal)
            return [dict(x) for x in con.execute("SELECT id,name,created_at FROM projects WHERE account_id=? ORDER BY created_at,id LIMIT 100",(principal.account_id,))]

    def get_project(self, principal: Principal, project_id: str) -> dict:
        with self.connect() as con:
            self._authorize(con,principal)
            row=con.execute("SELECT id,name,created_at FROM projects WHERE account_id=? AND id=?",(principal.account_id,project_id)).fetchone()
            if not row: raise NotFound("unavailable")
            return dict(row)
