"""The synthetic connector: a fake outside system, built on the connector contract, that every part of the action pipeline is proven against (roadmap Phase 3).

It is the reference for connector authors (see platform/CONNECTORS.md): a declaration, an adapter, previews, inverses and a compensation. Its "provider" is two tables in
Lumina's own database, so the same checks run in a unit test and on the live stack. It exists for an account only while the test-only switch `synthetic_connector` is on.

What the fake provider has, on purpose, because real ones do:
* folders (the resource a grant names) holding notes, and an outbox of messages;
* a version number on every note, checked as a precondition on update and delete;
* cursor paging, with a total;
* faults that can be queued: a rate limit with Retry-After, a server error, a refused token, and a write that SUCCEEDS WITHOUT ANSWERING (`silent`);
* an idempotency key on writes: a repeat with the same key changes nothing and answers with the first result.

Write kinds: note.create (undone by note.delete), note.update (undone by another note.update that puts the old text back), note.delete (undone by note.restore), note.restore
(undone by note.delete) and message.send, which cannot be undone and registers the compensation message.correction.
"""
from __future__ import annotations
import time
import uuid

from .connector_kit import Caps, Declaration, Page, ProviderError, Unanswered, WriteKind, record

PROVIDER = 'synthetic'
FOLDERS = ('inbox', 'projects', 'archive')

DECLARATION = Declaration(
    provider=PROVIDER, label='Synthetic service (test only)', auth='token', scopes=('notes', 'messages'),
    resource_kinds=('folder',), record_kinds=('note', 'message'), read_operations=('list', 'read', 'search'),
    write_kinds=(
        WriteKind('note.create', 'Create a note', policy_kind='write', undo='note.delete'),
        WriteKind('note.update', 'Change a note', policy_kind='write', undo='note.update', needs_version=True),
        WriteKind('note.delete', 'Delete a note', policy_kind='delete', undo='note.restore', needs_version=True),
        WriteKind('note.restore', 'Put a deleted note back', policy_kind='write', undo='note.delete'),
        WriteKind('message.send', 'Send a message', policy_kind='send', irreversible_reason='A message that has been sent cannot be taken back.',
                  compensations=('message.correction',)),
        WriteKind('message.correction', 'Send a correction', policy_kind='send', irreversible_reason='A correction that has been sent cannot be taken back.'),
    ),
    change_tokens=False, version_token='revision', preconditions=True, idempotency_keys=True, paging='cursor',
    error_map={'token_revoked': 'needs_customer', 'version_mismatch': 'conflict', 'quota': 'retry_later', 'forbidden': 'refused'},
    implementation='first_party', reason='A fake provider inside Lumina: there is no outside server to wrap.',
    hosts=(), freshness_seconds={'folder': 900}, caps=Caps(pages=10, items=50, bytes=200_000, seconds=10.0),
    disclosure='A test service inside Lumina. It holds only what a test puts in it.')


def _note(row):
    return record('note', row['id'], container=('folder', row['folder']), version=row['version'], title=row['title'], data={'title': row['title'], 'body': row['body']},
                  updated_epoch=row['updated_epoch'])


def _message(row):
    return record('message', row['id'], container=('folder', row['folder']), version=row['version'], title=row['title'], data={'to': row['title'], 'text': row['body']},
                  updated_epoch=row['updated_epoch'])


class SyntheticAdapter:
    """The adapter. `credential` is the token from custody: {'access_token', 'account'}; a token the provider no longer knows is refused."""
    PAGE = 20

    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    # -- the fake provider's own behaviour -----------------------------------------------------------------------------------------------------
    def _enter(self, credential, operation):
        if not isinstance(credential, dict) or not credential.get('account') or not str(credential.get('access_token', '')).startswith('synthetic-'):
            raise ProviderError(401, 'token_revoked')
        account = credential['account']
        with self.store.connect() as con:
            fault = con.execute("SELECT sequence,fault,remaining FROM synthetic_faults WHERE account_id=? AND operation IN (?,'*') ORDER BY sequence LIMIT 1", (account, operation)).fetchone()
            if fault:
                if fault['remaining'] <= 1:
                    con.execute('DELETE FROM synthetic_faults WHERE sequence=?', (fault['sequence'],))
                else:
                    con.execute('UPDATE synthetic_faults SET remaining=remaining-1 WHERE sequence=?', (fault['sequence'],))
        name = fault['fault'] if fault else None
        if name == 'rate_limit':
            raise ProviderError(429, 'quota', retry_after=2)
        if name == 'server_error':
            raise ProviderError(503)
        if name == 'revoked':
            raise ProviderError(401, 'token_revoked')
        if name == 'forbidden':
            raise ProviderError(403, 'forbidden')
        return account, name

    # -- reading -------------------------------------------------------------------------------------------------------------------------------
    def resources(self, credential):
        self._enter(credential, 'resources')
        return [{'kind': 'folder', 'id': name, 'name': name.capitalize()} for name in FOLDERS]

    def list(self, credential, container, position, limit, record_kind=None):
        account, _ = self._enter(credential, 'list')
        start = int(position or 0)
        size = max(1, min(int(limit or self.PAGE), self.PAGE))
        with self.store.connect() as con:
            args = [account, container[1]] + ([record_kind] if record_kind else [])
            where = 'account_id=? AND folder=? AND deleted=0' + (' AND kind=?' if record_kind else '')
            total = con.execute(f'SELECT count(*) FROM synthetic_records WHERE {where}', args).fetchone()[0]
            rows = con.execute(f'SELECT * FROM synthetic_records WHERE {where} ORDER BY id LIMIT ? OFFSET ?', (*args, size, start)).fetchall()
        return Page([(_note if r['kind'] == 'note' else _message)(r) for r in rows], next=start + len(rows) if start + len(rows) < total else None, total=total)

    def read(self, credential, record_kind, record_id):
        account, _ = self._enter(credential, 'read')
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND id=? AND kind=? AND deleted=0', (account, record_id, record_kind)).fetchone()
        if row is None:
            raise ProviderError(404)
        return (_note if record_kind == 'note' else _message)(row)

    def search(self, credential, query, containers, position, limit):
        account, _ = self._enter(credential, 'search')
        start, size = int(position or 0), max(1, min(int(limit or self.PAGE), self.PAGE))
        folders = sorted({c[1] for c in containers}) if containers is not None else list(FOLDERS)
        marks = ','.join('?' * len(folders)) or "''"
        like = '%' + query.replace('%', '').replace('_', '') + '%'
        with self.store.connect() as con:
            where = f'account_id=? AND deleted=0 AND folder IN ({marks}) AND (title LIKE ? OR body LIKE ?)'
            total = con.execute(f'SELECT count(*) FROM synthetic_records WHERE {where}', (account, *folders, like, like)).fetchone()[0]
            rows = con.execute(f'SELECT * FROM synthetic_records WHERE {where} ORDER BY id LIMIT ? OFFSET ?', (account, *folders, like, like, size, start)).fetchall()
        return Page([(_note if r['kind'] == 'note' else _message)(r) for r in rows], next=start + len(rows) if start + len(rows) < total else None, total=total)

    # -- what a write touches (asked BEFORE anything is sent) ------------------------------------------------------------------------------------
    def container_of(self, credential, kind, payload):
        if kind in ('note.create', 'message.send', 'message.correction'):
            return ('folder', str(payload.get('folder', '')))
        with self.store.connect() as con:
            row = con.execute('SELECT folder FROM synthetic_records WHERE account_id=? AND id=?', (credential.get('account'), str(payload.get('id', '')))).fetchone()
        return ('folder', row['folder']) if row else None

    @staticmethod
    def target_of(kind, payload):
        """(record kind, record id) of the existing record a write changes, or None when it creates something new."""
        return ('note', str(payload['id'])) if kind in ('note.update', 'note.delete') and payload.get('id') else None

    @staticmethod
    def check(kind, payload):
        """Is this a well-formed request for this write kind? Raises ValueError with a fixed word. Called when an action is proposed, long before anything is sent."""
        text = lambda key, most, least=1: isinstance(payload.get(key), str) and least <= len(payload[key]) <= most
        ok = {'note.create': lambda: payload.get('folder') in FOLDERS and text('title', 200) and text('body', 5000, 0) and set(payload) <= {'folder', 'title', 'body'},
              'note.update': lambda: text('id', 64) and (text('title', 200) or 'title' not in payload) and (text('body', 5000, 0) or 'body' not in payload)
                                     and set(payload) <= {'id', 'title', 'body'} and len(payload) > 1,
              'note.delete': lambda: text('id', 64) and set(payload) <= {'id'},
              'note.restore': lambda: text('id', 64) and set(payload) <= {'id'},
              'message.send': lambda: payload.get('folder') in FOLDERS and text('to', 200) and text('text', 5000) and set(payload) <= {'folder', 'to', 'text'},
              'message.correction': lambda: payload.get('folder') in FOLDERS and text('to', 200) and text('text', 5000) and set(payload) <= {'folder', 'to', 'text', 'corrects'}}.get(kind)
        if ok is None or not isinstance(payload, dict) or not ok():
            raise ValueError('invalid request for this kind of change')

    # -- previews: rendered from the stored payload, one per write kind ------------------------------------------------------------------------------
    @staticmethod
    def preview(kind, payload, before):
        """-> {'destination','changes':[{'field','before','after'}],'affected','summary'}: what the customer is shown. Built only from the payload that will be sent and the
        record as it is now; never from anything the assistant wrote about it."""
        old = (before or {}).get('data') or {}
        if kind == 'note.create':
            return {'destination': f'Synthetic service, folder "{payload["folder"]}"', 'summary': f'Create the note "{payload["title"]}"', 'affected': 1,
                    'changes': [{'field': 'title', 'before': None, 'after': payload['title']}, {'field': 'body', 'before': None, 'after': payload['body']}]}
        if kind == 'note.update':
            return {'destination': f'Synthetic service, note "{old.get("title", payload["id"])}"', 'summary': f'Change the note "{old.get("title", payload["id"])}"', 'affected': 1,
                    'changes': [{'field': f, 'before': old.get(f), 'after': payload[f]} for f in ('title', 'body') if f in payload and payload[f] != old.get(f)]}
        if kind == 'note.delete':
            return {'destination': f'Synthetic service, note "{old.get("title", payload["id"])}"', 'summary': f'Delete the note "{old.get("title", payload["id"])}"', 'affected': 1,
                    'changes': [{'field': 'note', 'before': old.get('title'), 'after': None}]}
        if kind == 'note.restore':
            return {'destination': 'Synthetic service', 'summary': 'Put the deleted note back', 'affected': 1, 'changes': [{'field': 'note', 'before': None, 'after': payload['id']}]}
        return {'destination': f'To {payload["to"]} (synthetic service, folder "{payload["folder"]}")',
                'summary': ('Send a correction to ' if kind == 'message.correction' else 'Send a message to ') + payload['to'], 'affected': 1,
                'changes': [{'field': 'text', 'before': None, 'after': payload['text']}]}

    # -- undo and compensation: defined here, in code. The data to undo is taken BEFORE the forward write -------------------------------------------------
    @staticmethod
    def undo_payload(kind, payload, before):
        """What the inverse needs, from the record as it is before the forward write. For a creation the id is not known yet: `undo_after` adds it."""
        old = (before or {}).get('data') or {}
        if kind == 'note.update':
            return {'id': payload['id'], **{f: old.get(f, '') for f in ('title', 'body') if f in payload}}
        if kind == 'note.delete':
            return {'id': payload['id']}
        if kind == 'note.restore':
            return {'id': payload['id']}
        return {} if kind == 'note.create' else None

    @staticmethod
    def undo_after(kind, undo, result):
        if kind == 'note.create' and isinstance(undo, dict):
            return {'id': result['record']['id']}
        return undo

    @staticmethod
    def compensation_payload(kind, compensation, payload, result):
        """The follow-up for a write that cannot be undone. Fixed wording, made here: the assistant may choose to propose it and never writes it."""
        if kind == 'message.send' and compensation == 'message.correction':
            return {'folder': payload['folder'], 'to': payload['to'], 'corrects': (result or {}).get('record', {}).get('id', ''),
                    'text': 'Please disregard my previous message. It was sent in error.'}
        return None

    @staticmethod
    def verify(kind, payload, found):
        """After a write: does what the provider holds now match what was sent? -> (matches, a short fixed note)."""
        if kind == 'note.delete':
            return found is None, 'the note is gone' if found is None else 'the note is still there'
        if found is None:
            return False, 'the record is not there'
        data = found.get('data') or {}
        if kind in ('note.create', 'note.update'):
            same = all(data.get(f) == payload[f] for f in ('title', 'body') if f in payload)
        elif kind == 'note.restore':
            same = True
        else:
            same = data.get('to') == payload['to'] and data.get('text') == payload['text']
        return same, 'what was sent is what is there' if same else 'what is there differs from what was sent'

    # -- writing -------------------------------------------------------------------------------------------------------------------------------
    def write(self, credential, kind, payload, *, idempotency_key=None, precondition=None):
        account, fault = self._enter(credential, 'write')
        now = int(self.clock())
        from .lifecycle.coordinator import Coordinator
        with Coordinator(self.store).transaction() as con:
            if True:
                repeat = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND idempotency_key=?', (account, idempotency_key)).fetchone() if idempotency_key else None
                if repeat is not None:                          # the same request again: nothing changes, the first answer is given
                    row = repeat
                elif kind in ('note.create', 'message.send', 'message.correction'):
                    rid = uuid.uuid4().hex[:16]
                    title, body = (payload['title'], payload['body']) if kind == 'note.create' else (payload['to'], payload['text'])
                    con.execute('INSERT INTO synthetic_records(account_id,id,kind,folder,title,body,version,idempotency_key,updated_epoch) VALUES (?,?,?,?,?,?,1,?,?)',
                                (account, rid, 'note' if kind == 'note.create' else 'message', payload['folder'], title, body, idempotency_key, now))
                    row = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND id=?', (account, rid)).fetchone()
                else:
                    row = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND id=?', (account, payload['id'])).fetchone()
                    if row is None or (bool(row['deleted']) != (kind == 'note.restore')):
                        raise ProviderError(404)
                    if precondition is not None and str(row['version']) != str(precondition):
                        raise ProviderError(412, 'version_mismatch')
                    if kind == 'note.update':
                        con.execute('UPDATE synthetic_records SET title=?,body=?,version=version+1,idempotency_key=?,updated_epoch=? WHERE account_id=? AND id=?',
                                    (payload.get('title', row['title']), payload.get('body', row['body']), idempotency_key, now, account, row['id']))
                    else:
                        con.execute('UPDATE synthetic_records SET deleted=?,version=version+1,idempotency_key=?,updated_epoch=? WHERE account_id=? AND id=?',
                                    (1 if kind == 'note.delete' else 0, idempotency_key, now, account, row['id']))
                    row = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND id=?', (account, row['id'])).fetchone()
        if fault == 'silent':
            raise Unanswered()                                  # it happened, and the answer was lost on the way back
        found = (_note if row['kind'] == 'note' else _message)(row)
        return {'receipt': f'synthetic-{row["id"]}-v{row["version"]}', 'record': {**found, 'deleted': bool(row['deleted'])}}

    def find_effect(self, credential, kind, payload, idempotency_key):
        """Read back a write whose answer never came. The provider remembers the idempotency key, so this is exact."""
        account, _ = self._enter(credential, 'read')
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM synthetic_records WHERE account_id=? AND idempotency_key=?', (account, idempotency_key)).fetchone()
        if row is None:
            return None
        return {'receipt': f'synthetic-{row["id"]}-v{row["version"]}', 'record': {**(_note if row['kind'] == 'note' else _message)(row), 'deleted': bool(row['deleted'])}}


class SyntheticBench:
    """For tests and the live proof: fill the fake provider, queue faults, issue and refresh its tokens."""
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def seed(self, account, folder, count, *, kind='note', prefix='Note'):
        with self.store.connect() as con:
            for n in range(count):
                con.execute('INSERT INTO synthetic_records(account_id,id,kind,folder,title,body,version,updated_epoch) VALUES (?,?,?,?,?,?,1,?)',
                            (account, f'{folder}-{n:04d}', kind, folder, f'{prefix} {n}', f'Body of {prefix.lower()} {n}', int(self.clock())))

    def fault(self, account, operation, fault, times=1):
        if fault not in ('rate_limit', 'server_error', 'revoked', 'forbidden', 'silent'):
            raise ValueError('unknown fault')
        with self.store.connect() as con:
            con.execute('INSERT INTO synthetic_faults(account_id,operation,fault,remaining) VALUES (?,?,?,?)', (account, operation, fault, times))

    def edit_elsewhere(self, account, record_id, **fields):
        """Somebody else changes a record in the provider (a concurrent edit)."""
        with self.store.connect() as con:
            for name, value in fields.items():
                con.execute(f'UPDATE synthetic_records SET {name}=?,version=version+1 WHERE account_id=? AND id=?', (value, account, record_id))

    def rows(self, account, folder=None):
        with self.store.connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM synthetic_records WHERE account_id=?' + (' AND folder=?' if folder else '') + ' ORDER BY id', (account, folder) if folder else (account,))]

    @staticmethod
    def tokens(account):
        return {'access_token': 'synthetic-' + uuid.uuid4().hex, 'refresh_token': 'refresh-' + uuid.uuid4().hex, 'account': account}

    @staticmethod
    def refresher(tokens):
        """The fake provider's token endpoint. A refresh token it does not know is a refusal the customer has to fix; `refresh-revoked` is the provider ending the access."""
        from .connector_refresh import RefreshFault
        token = str(tokens.get('refresh_token', ''))
        if token == 'refresh-revoked':
            raise RefreshFault('revoked')
        if token == 'refresh-busy':
            raise RefreshFault('temporary')
        if not token.startswith('refresh-') or token == 'refresh-invalid':
            raise RefreshFault('needs_customer')
        return {'tokens': {**tokens, 'access_token': 'synthetic-' + uuid.uuid4().hex}, 'expires_in': 3600}


def register(registry, store, clock=time.time):
    registry.register(DECLARATION, lambda: SyntheticAdapter(store, clock))
    return registry
