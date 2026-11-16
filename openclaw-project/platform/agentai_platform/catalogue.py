"""One catalogue of a customer's files (roadmap #30): what they uploaded and what their assistant made, in one list, in folders they choose.

The files stay where they are: uploads in `project_files`, files the assistant made in `artifacts` (immutable, versioned). The catalogue is a READING of both, plus two
small tables of the customer's own organization: `file_folders` (folders per project) and `file_places` (which folder a file is in, and the name they gave it). So there
is nothing to keep in step and nothing a rename can damage: a file with no place is simply where it was made, under its own name.

An entry: kind ('upload' | 'made'), id, name, media type, size, content hash, project, folder, source ('uploaded' | 'made'; attachments and connected drives join with
their own source when they exist), created, and for a made file its newest version and how many versions it has. Entries with the same content hash are marked as copies.

Every query is scoped by the account of the verified principal. A folder or a file of another account cannot be named.
"""
from __future__ import annotations
import time
import uuid

from .artifacts import BUNDLE_MEDIA, BUNDLE_SUFFIX
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal, require

KINDS = ('upload', 'made')
MAX_FOLDERS = 500
MAX_DEPTH = 6
LIST_LIMIT = 1000


def family(media_type: str, name: str) -> str:
    """What sort of thing a file is, for the Files page's filter: document, spreadsheet, slides, picture, text, data or other."""
    m, n = (media_type or '').lower(), (name or '').lower()
    if m.startswith('image/'):
        return 'picture'
    if 'spreadsheet' in m or n.endswith(('.xlsx', '.csv', '.tsv')):
        return 'spreadsheet'
    if 'presentation' in m or n.endswith('.pptx'):
        return 'slides'
    if m == 'application/pdf' or 'wordprocessing' in m or n.endswith(('.docx', '.pdf')):
        return 'document'
    if m in ('application/json',) or n.endswith(('.json', '.xml', '.yaml', '.yml', '.sql')):
        return 'data'
    if m.startswith('text/') or m == 'message/rfc822':
        return 'text'
    return 'other'


class Catalogue:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.coordinator = Coordinator(store, clock=clock)

    # -- reading ----------------------------------------------------------------------------------------------------------------------------------------
    def entries(self, principal: Principal, *, project_id=None, folder_id=..., source=None, kind=None, query=None) -> dict:
        """-> {'files': [...], 'folders': [...], 'projects': [...]}. `folder_id`: a folder's id, None for "in no folder", or left out for every folder."""
        if source not in (None, 'uploaded', 'made') or (query is not None and (not isinstance(query, str) or len(query) > 200)):
            raise ValueError('invalid filter')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            require(principal, 'file.read', con=con)
            places = {(r['kind'], r['object_id']): r for r in con.execute('SELECT kind,object_id,folder_id,name FROM file_places WHERE account_id=?', (principal.account_id,))}
            uploads = con.execute("""SELECT id,display_name,media_type,size_bytes,sha256,project_id,created_at,shares_with FROM project_files
                WHERE account_id=? AND state='scanned' ORDER BY created_at DESC,id LIMIT ?""", (principal.account_id, LIST_LIMIT)).fetchall()
            made = con.execute("""SELECT a.id,a.version,a.display_name,a.media_type,a.size_bytes,a.sha256,a.project_id,a.created_at,
                    (SELECT count(*) FROM artifacts v WHERE v.account_id=a.account_id AND v.id=a.id) AS versions,
                    (SELECT r.conversation_id FROM customer_requests r WHERE r.account_id=a.account_id AND r.id=a.task_id LIMIT 1) AS conversation_id
                FROM artifacts a WHERE a.account_id=? AND a.version=(SELECT max(v.version) FROM artifacts v WHERE v.account_id=a.account_id AND v.id=a.id)
                AND NOT (a.media_type=? AND a.display_name LIKE ?) ORDER BY a.created_at DESC,a.id LIMIT ?""",
                               (principal.account_id, BUNDLE_MEDIA, '%' + BUNDLE_SUFFIX, LIST_LIMIT)).fetchall()
            folders = [dict(r) for r in con.execute('SELECT id,project_id,parent_id,name FROM file_folders WHERE account_id=? ORDER BY lower(name),id', (principal.account_id,))]
            projects = [dict(r) for r in con.execute('SELECT id,name FROM projects WHERE account_id=? ORDER BY name,id', (principal.account_id,))]
        files = []
        for what, rows in (('upload', uploads), ('made', made)):
            for r in rows:
                place = places.get((what, r['id']))
                name = (place['name'] if place and place['name'] else r['display_name'])
                files.append({'kind': what, 'id': r['id'], 'name': name, 'original_name': r['display_name'], 'media_type': r['media_type'], 'size_bytes': r['size_bytes'],
                              'sha256': r['sha256'], 'project_id': r['project_id'], 'folder_id': place['folder_id'] if place else None, 'source': 'uploaded' if what == 'upload' else 'made',
                              'created_at': r['created_at'], 'family': family(r['media_type'], name),
                              **({'version': r['version'], 'versions': r['versions'], 'conversation_id': r['conversation_id']} if what == 'made' else {})})
        seen = {}
        for f in sorted(files, key=lambda f: f['created_at']):
            f['copy_of'] = seen.get(f['sha256'])                 # the oldest file with this content is the original; later ones say whose copy they are
            seen.setdefault(f['sha256'], {'kind': f['kind'], 'id': f['id'], 'name': f['name']})
        words = [w for w in (query or '').lower().split() if w]
        shown = [f for f in files if (project_id is None or f['project_id'] == project_id) and (folder_id is ... or f['folder_id'] == folder_id)
                 and (source is None or f['source'] == source) and (kind is None or f['family'] == kind) and all(w in f['name'].lower() for w in words)]
        shown.sort(key=lambda f: (f['created_at'], f['id']), reverse=True)
        counts = {}
        for f in files:
            counts[f['folder_id']] = counts.get(f['folder_id'], 0) + 1
        return {'files': shown, 'folders': [{**f, 'files': counts.get(f['id'], 0)} for f in folders], 'projects': projects, 'total': len(files)}

    # -- folders ----------------------------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _name(value) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120 or any(ch in value for ch in '/\\\x00') or value.strip() in ('.', '..'):
            raise ValueError('invalid name')
        return value.strip()

    def _folder(self, con, principal, folder_id):
        row = con.execute('SELECT * FROM file_folders WHERE account_id=? AND id=?', (principal.account_id, identifier(folder_id))).fetchone()
        if row is None:
            raise NotFound('unavailable')
        return row

    def _depth(self, con, account, folder_id) -> int:
        depth = 0
        while folder_id is not None and depth <= MAX_DEPTH + 1:
            row = con.execute('SELECT parent_id FROM file_folders WHERE account_id=? AND id=?', (account, folder_id)).fetchone()
            folder_id = row['parent_id'] if row else None
            depth += 1
        return depth

    def _free(self, con, account, project_id, parent_id, name, but=None):
        taken = con.execute("SELECT id FROM file_folders WHERE account_id=? AND project_id=? AND coalesce(parent_id,'')=? AND lower(name)=lower(?)",
                            (account, project_id, parent_id or '', name)).fetchone()
        if taken is not None and taken['id'] != but:
            raise Conflict('a folder with that name is already there')

    def create_folder(self, principal: Principal, project_id: str, name: str, parent_id: str | None = None) -> dict:
        name, now = self._name(name), int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'file.write', con=con)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?', (principal.account_id, identifier(project_id))).fetchone():
                raise NotFound('unavailable')
            if parent_id is not None and self._folder(con, principal, parent_id)['project_id'] != project_id:
                raise NotFound('unavailable')
            if self._depth(con, principal.account_id, parent_id) >= MAX_DEPTH:
                raise Conflict('folders cannot be nested deeper')
            if con.execute('SELECT count(*) FROM file_folders WHERE account_id=?', (principal.account_id,)).fetchone()[0] >= MAX_FOLDERS:
                raise Conflict('too many folders')
            self._free(con, principal.account_id, project_id, parent_id, name)
            folder_id = uuid.uuid4().hex
            con.execute('INSERT INTO file_folders(account_id,id,project_id,parent_id,name,created_epoch) VALUES (?,?,?,?,?,?)', (principal.account_id, folder_id, project_id, parent_id, name, now))
            return {'id': folder_id, 'project_id': project_id, 'parent_id': parent_id, 'name': name, 'files': 0}

    def change_folder(self, principal: Principal, folder_id: str, *, name=None, parent_id=...) -> dict:
        """Rename a folder, or move it under another folder of the same project (never under itself or one of its own subfolders)."""
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'file.write', con=con)
            row = self._folder(con, principal, folder_id)
            new_name = self._name(name) if name is not None else row['name']
            new_parent = row['parent_id'] if parent_id is ... else parent_id
            if new_parent is not None:
                if self._folder(con, principal, new_parent)['project_id'] != row['project_id']:
                    raise NotFound('unavailable')
                walk = new_parent
                while walk is not None:
                    if walk == folder_id:
                        raise Conflict('a folder cannot be moved into itself')
                    walk = con.execute('SELECT parent_id FROM file_folders WHERE account_id=? AND id=?', (principal.account_id, walk)).fetchone()['parent_id']
                if self._depth(con, principal.account_id, new_parent) >= MAX_DEPTH:
                    raise Conflict('folders cannot be nested deeper')
            self._free(con, principal.account_id, row['project_id'], new_parent, new_name, but=folder_id)
            con.execute('UPDATE file_folders SET name=?,parent_id=? WHERE account_id=? AND id=?', (new_name, new_parent, principal.account_id, folder_id))
            return {'id': folder_id, 'project_id': row['project_id'], 'parent_id': new_parent, 'name': new_name}

    def delete_folder(self, principal: Principal, folder_id: str) -> dict:
        """Remove a folder. Nothing in it is deleted: its files and subfolders move up to where the folder was."""
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'file.write', con=con)
            row = self._folder(con, principal, folder_id)
            for child in con.execute('SELECT id,name FROM file_folders WHERE account_id=? AND parent_id=?', (principal.account_id, folder_id)).fetchall():
                name, n = child['name'], 1
                while con.execute("SELECT 1 FROM file_folders WHERE account_id=? AND project_id=? AND coalesce(parent_id,'')=? AND lower(name)=lower(?) AND id!=?",
                                  (principal.account_id, row['project_id'], row['parent_id'] or '', name, child['id'])).fetchone():
                    n += 1; name = f"{child['name'][:110]} ({n})"
                con.execute('UPDATE file_folders SET parent_id=?,name=? WHERE account_id=? AND id=?', (row['parent_id'], name, principal.account_id, child['id']))
            moved = con.execute('UPDATE file_places SET folder_id=? WHERE account_id=? AND folder_id=?', (row['parent_id'], principal.account_id, folder_id)).rowcount
            con.execute('DELETE FROM file_folders WHERE account_id=? AND id=?', (principal.account_id, folder_id))
            return {'deleted': folder_id, 'files_moved_up': moved}

    # -- placing a file ---------------------------------------------------------------------------------------------------------------------------------
    def place(self, principal: Principal, kind: str, object_id: str, *, folder_id=..., name=...) -> dict:
        """Put a file in a folder (None: out of every folder) and/or give it a name (None: its own name again). The file itself is not touched. A folder must belong to the
        file's own project."""
        if kind not in KINDS:
            raise ValueError('invalid kind')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            require(principal, 'file.write', con=con)
            table = 'project_files' if kind == 'upload' else 'artifacts'
            found = con.execute(f'SELECT project_id FROM {table} WHERE account_id=? AND id=? LIMIT 1', (principal.account_id, identifier(object_id))).fetchone()
            if found is None:
                raise NotFound('unavailable')
            old = con.execute('SELECT folder_id,name FROM file_places WHERE account_id=? AND kind=? AND object_id=?', (principal.account_id, kind, object_id)).fetchone()
            new_folder = (old['folder_id'] if old else None) if folder_id is ... else folder_id
            new_name = (old['name'] if old else None) if name is ... else (self._file_name(name) if name is not None else None)
            if new_folder is not None and self._folder(con, principal, new_folder)['project_id'] != found['project_id']:
                raise NotFound('unavailable')
            if new_folder is None and new_name is None:
                con.execute('DELETE FROM file_places WHERE account_id=? AND kind=? AND object_id=?', (principal.account_id, kind, object_id))
            else:
                con.execute('''INSERT INTO file_places(account_id,kind,object_id,folder_id,name,updated_epoch) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(account_id,kind,object_id) DO UPDATE SET folder_id=excluded.folder_id,name=excluded.name,updated_epoch=excluded.updated_epoch''',
                            (principal.account_id, kind, object_id, new_folder, new_name, now))
            return {'kind': kind, 'id': object_id, 'folder_id': new_folder, 'name': new_name}

    @staticmethod
    def _file_name(value) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128 or any(ch in value for ch in '/\\\x00') or value.strip().startswith('.'):
            raise ValueError('invalid name')
        return value.strip()
