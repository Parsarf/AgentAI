"""The knowledge index (roadmap #36, #37, #40, #41): parsed documents and their passages, searchable by words and by meaning.

Production is a dedicated PostgreSQL database with the vector extension on the Lumina host (the owner's choice, 2026-11-16; its own container, not Hindsight's, see
deploy/knowledge/install.sh). `LocalIndex` has the same interface on SQLite and is used by the tests and the local development server.

The index is DERIVED: the source of truth is `knowledge_sources` in the platform database and the files themselves. Everything here can be rebuilt by indexing the
sources again, so a backup of it is not needed, and a removed source must never come back from one.

Who may see a passage is decided HERE, inside every query, before anything is ranked: a passage is visible to the account that added it, and, when its source was
shared with the organization, to the members its audience names ('all', 'role:<role>', 'group:<id>'). The knowledge service checks the final results once more
against the current state of the sources (knowledge.py), so a source removed or unshared a moment ago is not returned either.

Stdlib plus pg8000 (pure Python). Nothing about content is logged.
"""
from __future__ import annotations
import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field

from .adapters import CapabilityUnavailable
from .embeddings import DIMENSIONS, cosine

SCHEMA_VERSION = 1
MAX_STRUCTURE_BYTES = 24 * 1024 * 1024
TERM = re.compile(r'\w{2,}', re.UNICODE)
COLUMNS = ('id', 'account_id', 'organization_id', 'source_id', 'project_id', 'scope', 'audience', 'ordinal', 'page', 'section', 'kind', 'text', 'position', 'confidence',
           'content_hash', 'source_epoch', 'created_epoch')


@dataclass(frozen=True)
class Visible:
    """Who is asking: their account, their organization and the audiences they belong to (always 'all'; 'role:<their role>'; 'group:<id>' for each of their groups)."""
    account_id: str
    organization_id: str
    audiences: tuple = field(default=('all',))


def terms(query: str, limit=24) -> list:
    seen, out = set(), []
    for t in TERM.findall((query or '').lower()):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:limit]


def _vector_text(vector) -> str:
    if len(vector) != DIMENSIONS:
        raise ValueError('wrong vector size')
    return '[' + ','.join(f'{float(v):.6f}' for v in vector) + ']'


# ---------------------------------------------------------------------------------------------------------------------------------------------------- PostgreSQL
PG_SCHEMA = (
    'CREATE EXTENSION IF NOT EXISTS vector',
    'CREATE TABLE IF NOT EXISTS kn_meta (key text PRIMARY KEY, value text NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS kn_documents (account_id text NOT NULL, sha256 text NOT NULL, parser text NOT NULL, structure jsonb NOT NULL, pages int,
        created_epoch bigint NOT NULL, PRIMARY KEY(account_id, sha256, parser))''',
    f'''CREATE TABLE IF NOT EXISTS kn_passages (id text PRIMARY KEY, account_id text NOT NULL, organization_id text NOT NULL, source_id text NOT NULL, project_id text,
        scope text NOT NULL, audience text NOT NULL DEFAULT '', ordinal int NOT NULL, page int, section text NOT NULL DEFAULT '', kind text NOT NULL, text text NOT NULL,
        position jsonb, confidence real, content_hash text NOT NULL, source_epoch bigint, created_epoch bigint NOT NULL, tsv tsvector NOT NULL, embedding vector({DIMENSIONS}))''',
    'CREATE INDEX IF NOT EXISTS kn_passages_source ON kn_passages(account_id, source_id, ordinal)',
    "CREATE INDEX IF NOT EXISTS kn_passages_shared ON kn_passages(organization_id, audience) WHERE scope = 'organization'",
    'CREATE INDEX IF NOT EXISTS kn_passages_tsv ON kn_passages USING gin(tsv)',
)
# Exact distances, filtered by account first: correct (no approximate index can drop a visible passage) and fast at the size one customer's documents reach
# (1,000 documents of about 50 passages each is 50,000 rows of 384 numbers). An approximate index is the change to make if one account grows far beyond that.
PG_VISIBLE = "(account_id = :account OR (organization_id = :org AND scope = 'organization' AND audience = ANY(:aud)))"


class PgIndex:
    def __init__(self, *, host, port, database, user, password, timeout=30, connect=None):
        self.params = {'host': host, 'port': int(port), 'database': database, 'user': user, 'password': password, 'timeout': timeout}
        self._connect = connect
        self._ready = False
        self._lock = threading.Lock()

    @classmethod
    def from_url(cls, url: str, **kw):
        from urllib.parse import unquote, urlsplit
        parts = urlsplit(url.strip())
        if parts.scheme not in ('postgresql', 'postgres') or parts.hostname not in ('127.0.0.1', 'localhost', '::1') or not parts.path.strip('/'):
            raise ValueError('the knowledge index must be a PostgreSQL database on this host')
        return cls(host=parts.hostname, port=parts.port or 5432, database=parts.path.strip('/'), user=unquote(parts.username or ''), password=unquote(parts.password or ''), **kw)

    def _con(self):
        try:
            if self._connect is not None:
                return self._connect(**self.params)
            import pg8000.native
            return pg8000.native.Connection(self.params['user'], host=self.params['host'], port=self.params['port'], database=self.params['database'],
                                            password=self.params['password'], timeout=self.params['timeout'])
        except Exception as exc:                       # the driver's own error types; the message can carry the address, so it is not passed on
            raise CapabilityUnavailable('knowledge index unavailable') from exc

    def _run(self, work):
        con = self._con()
        try:
            if not self._ready:
                with self._lock:
                    if not self._ready:
                        for statement in PG_SCHEMA:
                            con.run(statement)
                        con.run("INSERT INTO kn_meta(key,value) VALUES ('schema', :v) ON CONFLICT (key) DO UPDATE SET value = excluded.value", v=str(SCHEMA_VERSION))
                        self._ready = True
            return work(con)
        except CapabilityUnavailable:
            raise
        except Exception as exc:
            try:
                con.run('ROLLBACK')
            except Exception:
                pass
            raise CapabilityUnavailable('knowledge index failed: ' + type(exc).__name__) from exc
        finally:
            try:
                con.close()
            except Exception:
                pass

    # -- documents ------------------------------------------------------------------------------------------------------------------------------
    def document(self, account_id, sha256, parser):
        def work(con):
            rows = con.run('SELECT structure::text FROM kn_documents WHERE account_id = :a AND sha256 = :s AND parser = :p', a=account_id, s=sha256, p=parser)
            return json.loads(rows[0][0]) if rows else None
        return self._run(work)

    def keep_document(self, account_id, sha256, parser, structure, pages, now):
        text = json.dumps(structure, ensure_ascii=False)
        if len(text.encode()) > MAX_STRUCTURE_BYTES:
            raise ValueError('parsed document too large')
        self._run(lambda con: con.run('''INSERT INTO kn_documents(account_id,sha256,parser,structure,pages,created_epoch) VALUES (:a,:s,:p,CAST(:j AS jsonb),:n,:t)
            ON CONFLICT (account_id,sha256,parser) DO UPDATE SET structure = excluded.structure, pages = excluded.pages''', a=account_id, s=sha256, p=parser, j=text, n=pages, t=int(now)))

    def forget_documents(self, account_id, keep_hashes):
        """Parsed documents of this account whose content no source uses any more."""
        def work(con):
            rows = con.run('DELETE FROM kn_documents WHERE account_id = :a AND NOT (sha256 = ANY(:k)) RETURNING sha256', a=account_id, k=list(keep_hashes) or [''])
            return len(rows)
        return self._run(work)

    # -- passages -------------------------------------------------------------------------------------------------------------------------------
    def replace_source(self, account_id, source_id, passages, vectors):
        """All passages of one source, in one transaction: the old ones go, the new ones arrive. A search never sees half of it."""
        if len(passages) != len(vectors):
            raise ValueError('one vector per passage')

        def work(con):
            con.run('START TRANSACTION')
            con.run('DELETE FROM kn_passages WHERE account_id = :a AND source_id = :s', a=account_id, s=source_id)
            for p, v in zip(passages, vectors):
                con.run('''INSERT INTO kn_passages(id,account_id,organization_id,source_id,project_id,scope,audience,ordinal,page,section,kind,text,position,confidence,content_hash,
                        source_epoch,created_epoch,tsv,embedding) VALUES (:id,:account,:org,:source,:project,:scope,:audience,:ordinal,:page,:section,:kind,:text,CAST(:position AS jsonb),
                        :confidence,:hash,:source_epoch,:created,setweight(to_tsvector('simple', :section),'A') || setweight(to_tsvector('simple', :text),'B'),CAST(:vec AS vector))''',
                        id=p['id'], account=account_id, org=p['organization_id'], source=source_id, project=p.get('project_id'), scope=p['scope'], audience=p.get('audience') or '',
                        ordinal=p['ordinal'], page=p.get('page'), section=p.get('section') or '', kind=p['kind'], text=p['text'], position=json.dumps(p.get('position') or {}),
                        confidence=p.get('confidence'), hash=p['content_hash'], source_epoch=p.get('source_epoch'), created=p['created_epoch'], vec=_vector_text(v))
            con.run('COMMIT')
            return len(passages)
        return self._run(work)

    def share(self, account_id, source_id, *, scope, audience, project_id):
        """A source's sharing or project changed: its passages follow at once (no re-parse)."""
        return self._run(lambda con: len(con.run('''UPDATE kn_passages SET scope = :scope, audience = :aud, project_id = :project WHERE account_id = :a AND source_id = :s RETURNING id''',
                                                 scope=scope, aud=audience or '', project=project_id, a=account_id, s=source_id)))

    def remove_source(self, account_id, source_id) -> int:
        return self._run(lambda con: len(con.run('DELETE FROM kn_passages WHERE account_id = :a AND source_id = :s RETURNING id', a=account_id, s=source_id)))

    def remove_account(self, account_id) -> int:
        def work(con):
            con.run('START TRANSACTION')
            n = len(con.run('DELETE FROM kn_passages WHERE account_id = :a RETURNING id', a=account_id))
            con.run('DELETE FROM kn_documents WHERE account_id = :a', a=account_id)
            con.run('COMMIT')
            return n
        return self._run(work)

    def count(self, account_id, source_id=None) -> int:
        if source_id is None:
            return self._run(lambda con: con.run('SELECT count(*) FROM kn_passages WHERE account_id = :a', a=account_id)[0][0])
        return self._run(lambda con: con.run('SELECT count(*) FROM kn_passages WHERE account_id = :a AND source_id = :s', a=account_id, s=source_id)[0][0])

    def account_sizes(self, account_id) -> dict:
        return self._run(lambda con: {'passages': con.run('SELECT count(*) FROM kn_passages WHERE account_id = :a', a=account_id)[0][0],
                                      'documents': con.run('SELECT count(*) FROM kn_documents WHERE account_id = :a', a=account_id)[0][0]})

    def keyword(self, visible: Visible, query, *, sources=None, limit=40):
        words = terms(query)
        if not words:
            return []
        q = ' | '.join(w.replace("'", '') for w in words)
        extra = ' AND source_id = ANY(:sources)' if sources is not None else ''

        def work(con):
            rows = con.run(f'''SELECT id, source_id, ts_rank_cd(tsv, query) FROM kn_passages, to_tsquery('simple', :q) AS query
                WHERE tsv @@ query AND {PG_VISIBLE}{extra} ORDER BY 3 DESC, id LIMIT :k''', q=q, account=visible.account_id, org=visible.organization_id,
                           aud=list(visible.audiences), k=int(limit), **({'sources': list(sources) or ['']} if sources is not None else {}))
            return [{'id': r[0], 'source_id': r[1], 'score': float(r[2])} for r in rows]
        return self._run(work)

    def nearest(self, visible: Visible, vector, *, sources=None, limit=40):
        extra = ' AND source_id = ANY(:sources)' if sources is not None else ''

        def work(con):
            rows = con.run(f'''SELECT id, source_id, 1 - (embedding <=> CAST(:v AS vector)) FROM kn_passages WHERE embedding IS NOT NULL AND {PG_VISIBLE}{extra}
                ORDER BY embedding <=> CAST(:v AS vector), id LIMIT :k''', v=_vector_text(vector), account=visible.account_id, org=visible.organization_id,
                           aud=list(visible.audiences), k=int(limit), **({'sources': list(sources) or ['']} if sources is not None else {}))
            return [{'id': r[0], 'source_id': r[1], 'score': float(r[2])} for r in rows]
        return self._run(work)

    def passages(self, visible: Visible, ids):
        if not ids:
            return []

        def work(con):
            rows = con.run(f'SELECT {",".join(c if c != "position" else "position::text" for c in COLUMNS)} FROM kn_passages WHERE id = ANY(:ids) AND {PG_VISIBLE}',
                           ids=list(ids), account=visible.account_id, org=visible.organization_id, aud=list(visible.audiences))
            return [_row(dict(zip(COLUMNS, r))) for r in rows]
        return self._run(work)

    def vectors(self, visible: Visible, ids) -> dict:
        if not ids:
            return {}

        def work(con):
            rows = con.run(f'SELECT id, embedding::text FROM kn_passages WHERE id = ANY(:ids) AND {PG_VISIBLE}', ids=list(ids), account=visible.account_id,
                           org=visible.organization_id, aud=list(visible.audiences))
            return {r[0]: json.loads(r[1]) for r in rows if r[1]}
        return self._run(work)

    def source_passages(self, visible: Visible, source_id, *, limit=5000):
        def work(con):
            rows = con.run(f'SELECT {",".join(c if c != "position" else "position::text" for c in COLUMNS)} FROM kn_passages WHERE source_id = :s AND {PG_VISIBLE} ORDER BY ordinal LIMIT :k',
                           s=source_id, account=visible.account_id, org=visible.organization_id, aud=list(visible.audiences), k=int(limit))
            return [_row(dict(zip(COLUMNS, r))) for r in rows]
        return self._run(work)


def _row(row):
    if isinstance(row.get('position'), str):
        try:
            row['position'] = json.loads(row['position'])
        except ValueError:
            row['position'] = {}
    return row


# ---------------------------------------------------------------------------------------------------------------------------------------------------- SQLite
class LocalIndex:
    """The same index on SQLite (full-text search with FTS5, vectors compared in Python). For tests and the development server only."""

    def __init__(self, path=':memory:'):
        self.path = path
        self._shared = sqlite3.connect(path, check_same_thread=False) if path == ':memory:' else None
        self._lock = threading.RLock()
        with self._lock:
            con = self._c()
            con.executescript('''
                CREATE TABLE IF NOT EXISTS kn_documents (account_id TEXT, sha256 TEXT, parser TEXT, structure TEXT, pages INTEGER, created_epoch INTEGER, PRIMARY KEY(account_id,sha256,parser));
                CREATE TABLE IF NOT EXISTS kn_passages (id TEXT PRIMARY KEY, account_id TEXT, organization_id TEXT, source_id TEXT, project_id TEXT, scope TEXT, audience TEXT,
                    ordinal INTEGER, page INTEGER, section TEXT, kind TEXT, text TEXT, position TEXT, confidence REAL, content_hash TEXT, source_epoch INTEGER, created_epoch INTEGER,
                    embedding TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS kn_fts USING fts5(id UNINDEXED, section, text, tokenize='unicode61');''')
            con.commit()
        self.fail = None                 # tests: an exception to raise on the next call, to prove a broken index degrades instead of failing a request

    def _c(self):
        if self._shared is not None:
            return self._shared
        con = sqlite3.connect(self.path, timeout=10)
        return con

    def _check(self):
        if self.fail is not None:
            raise CapabilityUnavailable('knowledge index unavailable')

    def _visible(self, visible, p=''):
        marks = ','.join('?' for _ in visible.audiences) or "''"
        return (f"({p}account_id = ? OR ({p}organization_id = ? AND {p}scope = 'organization' AND {p}audience IN ({marks})))",
                [visible.account_id, visible.organization_id, *visible.audiences])

    def document(self, account_id, sha256, parser):
        self._check()
        with self._lock:
            row = self._c().execute('SELECT structure FROM kn_documents WHERE account_id=? AND sha256=? AND parser=?', (account_id, sha256, parser)).fetchone()
        return json.loads(row[0]) if row else None

    def keep_document(self, account_id, sha256, parser, structure, pages, now):
        self._check()
        with self._lock:
            con = self._c()
            con.execute('INSERT OR REPLACE INTO kn_documents VALUES (?,?,?,?,?,?)', (account_id, sha256, parser, json.dumps(structure, ensure_ascii=False), pages, int(now)))
            con.commit()

    def forget_documents(self, account_id, keep_hashes):
        self._check()
        with self._lock:
            con = self._c()
            keep = list(keep_hashes) or ['']
            n = con.execute(f'DELETE FROM kn_documents WHERE account_id=? AND sha256 NOT IN ({",".join("?" for _ in keep)})', (account_id, *keep)).rowcount
            con.commit()
            return n

    def replace_source(self, account_id, source_id, passages, vectors):
        self._check()
        if len(passages) != len(vectors):
            raise ValueError('one vector per passage')
        with self._lock:
            con = self._c()
            old = [r[0] for r in con.execute('SELECT id FROM kn_passages WHERE account_id=? AND source_id=?', (account_id, source_id))]
            con.executemany('DELETE FROM kn_fts WHERE id=?', [(i,) for i in old])
            con.execute('DELETE FROM kn_passages WHERE account_id=? AND source_id=?', (account_id, source_id))
            for p, v in zip(passages, vectors):
                _vector_text(v)
                con.execute('INSERT INTO kn_passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (p['id'], account_id, p['organization_id'], source_id, p.get('project_id'), p['scope'], p.get('audience') or '', p['ordinal'], p.get('page'),
                             p.get('section') or '', p['kind'], p['text'], json.dumps(p.get('position') or {}), p.get('confidence'), p['content_hash'], p.get('source_epoch'),
                             p['created_epoch'], json.dumps(v)))
                con.execute('INSERT INTO kn_fts(id,section,text) VALUES (?,?,?)', (p['id'], p.get('section') or '', p['text']))
            con.commit()
            return len(passages)

    def share(self, account_id, source_id, *, scope, audience, project_id):
        self._check()
        with self._lock:
            con = self._c()
            n = con.execute('UPDATE kn_passages SET scope=?,audience=?,project_id=? WHERE account_id=? AND source_id=?', (scope, audience or '', project_id, account_id, source_id)).rowcount
            con.commit()
            return n

    def remove_source(self, account_id, source_id):
        self._check()
        with self._lock:
            con = self._c()
            ids = [r[0] for r in con.execute('SELECT id FROM kn_passages WHERE account_id=? AND source_id=?', (account_id, source_id))]
            con.executemany('DELETE FROM kn_fts WHERE id=?', [(i,) for i in ids])
            con.execute('DELETE FROM kn_passages WHERE account_id=? AND source_id=?', (account_id, source_id))
            con.commit()
            return len(ids)

    def remove_account(self, account_id):
        self._check()
        with self._lock:
            con = self._c()
            ids = [r[0] for r in con.execute('SELECT id FROM kn_passages WHERE account_id=?', (account_id,))]
            con.executemany('DELETE FROM kn_fts WHERE id=?', [(i,) for i in ids])
            con.execute('DELETE FROM kn_passages WHERE account_id=?', (account_id,))
            con.execute('DELETE FROM kn_documents WHERE account_id=?', (account_id,))
            con.commit()
            return len(ids)

    def count(self, account_id, source_id=None):
        self._check()
        with self._lock:
            if source_id is None:
                return self._c().execute('SELECT count(*) FROM kn_passages WHERE account_id=?', (account_id,)).fetchone()[0]
            return self._c().execute('SELECT count(*) FROM kn_passages WHERE account_id=? AND source_id=?', (account_id, source_id)).fetchone()[0]

    def account_sizes(self, account_id):
        self._check()
        with self._lock:
            con = self._c()
            return {'passages': con.execute('SELECT count(*) FROM kn_passages WHERE account_id=?', (account_id,)).fetchone()[0],
                    'documents': con.execute('SELECT count(*) FROM kn_documents WHERE account_id=?', (account_id,)).fetchone()[0]}

    def keyword(self, visible, query, *, sources=None, limit=40):
        self._check()
        words = terms(query)
        if not words:
            return []
        where, args = self._visible(visible, 'p.')
        extra = ''
        if sources is not None:
            sources = list(sources) or ['']
            extra = f' AND p.source_id IN ({",".join("?" for _ in sources)})'
            args += sources
        match = ' OR '.join('"' + w.replace('"', '') + '"' for w in words)
        with self._lock:
            rows = self._c().execute(f'''SELECT p.id, p.source_id, -bm25(kn_fts, 2.0, 1.0) FROM kn_fts JOIN kn_passages p ON p.id = kn_fts.id
                WHERE kn_fts MATCH ? AND {where}{extra}
                ORDER BY 3 DESC, p.id LIMIT ?''', [match, *args, int(limit)]).fetchall()
        return [{'id': r[0], 'source_id': r[1], 'score': float(r[2])} for r in rows]

    def nearest(self, visible, vector, *, sources=None, limit=40):
        self._check()
        where, args = self._visible(visible)
        extra = ''
        if sources is not None:
            sources = list(sources) or ['']
            extra = f' AND source_id IN ({",".join("?" for _ in sources)})'
            args += sources
        with self._lock:
            rows = self._c().execute(f'SELECT id, source_id, embedding FROM kn_passages WHERE embedding IS NOT NULL AND {where}{extra}', args).fetchall()
        scored = sorted(({'id': r[0], 'source_id': r[1], 'score': cosine(vector, json.loads(r[2]))} for r in rows), key=lambda x: (-x['score'], x['id']))
        return scored[:limit]

    def passages(self, visible, ids):
        self._check()
        if not ids:
            return []
        where, args = self._visible(visible)
        ids = list(ids)
        with self._lock:
            rows = self._c().execute(f'SELECT {",".join(COLUMNS)} FROM kn_passages WHERE id IN ({",".join("?" for _ in ids)}) AND {where}', [*ids, *args]).fetchall()
        return [_row(dict(zip(COLUMNS, r))) for r in rows]

    def vectors(self, visible, ids):
        self._check()
        if not ids:
            return {}
        where, args = self._visible(visible)
        ids = list(ids)
        with self._lock:
            rows = self._c().execute(f'SELECT id, embedding FROM kn_passages WHERE id IN ({",".join("?" for _ in ids)}) AND {where}', [*ids, *args]).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows if r[1]}

    def source_passages(self, visible, source_id, *, limit=5000):
        self._check()
        where, args = self._visible(visible)
        with self._lock:
            rows = self._c().execute(f'SELECT {",".join(COLUMNS)} FROM kn_passages WHERE source_id=? AND {where} ORDER BY ordinal LIMIT ?', [source_id, *args, int(limit)]).fetchall()
        return [_row(dict(zip(COLUMNS, r))) for r in rows]
