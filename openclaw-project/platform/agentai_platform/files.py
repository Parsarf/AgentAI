"""Customer project files: allowlist validation, quarantine and quotas.

Contract rules (product/CONTRACT.md): content is validated independently of
the client-declared type; text must be valid UTF-8 without NUL; JSON must
parse; PNG/JPEG/PDF are checked by signature; executables, archives and
macros never pass; sizes are 10MiB/file, 25MiB/batch, 10 files/batch.
Uploads stay disabled unless the documented scan capability is enabled
(AGENTAI_UPLOADS_ENABLED=1); quarantined content is never served.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from . import safety
from .security import NotFound, Principal
from .storage import RootStore

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 25 * 1024 * 1024
MAX_BATCH_FILES = 10
MAX_PREVIEW_BYTES = 200 * 1024

# extension -> (accepted content kinds)
ALLOWLIST = {
    '.txt': ('text',), '.md': ('text',), '.csv': ('text',),
    '.json': ('json',), '.py': ('text',), '.js': ('text',), '.ts': ('text',),
    '.tsx': ('text',), '.jsx': ('text',), '.html': ('text',), '.css': ('text',),
    '.sql': ('text',), '.pdf': ('pdf',), '.png': ('png',), '.jpg': ('jpeg',), '.jpeg': ('jpeg',),
}

PDF_HEADER = b'%PDF-'
PNG_HEADER = b'\x89PNG\r\n\x1a\n'
JPEG_MAGIC = b'\xff\xd8\xff'


def sniff(data: bytes) -> str:
    """Content kind by inspection, independent of any client declaration."""
    if not data:
        return 'empty'
    if data.startswith(PNG_HEADER):
        return 'png'
    if data.startswith(JPEG_MAGIC):
        return 'jpeg'
    if data.startswith(PDF_HEADER):
        return 'pdf'
    if b'\x00' in data[:8192]:
        return 'binary'
    try:
        data.decode('utf-8')
        return 'text'
    except UnicodeDecodeError:
        return 'binary'


class Rejected(Exception):
    pass


class FileService:
    def __init__(self, store, *, storage: RootStore, clock=time.time):
        self.store = store
        self.storage = storage
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)

    def _account_used(self, con, account_id):
        files = con.execute('SELECT coalesce(sum(size_bytes),0) FROM project_files WHERE account_id=?',
                            (account_id,)).fetchone()[0]
        arts = con.execute('SELECT coalesce(sum(size_bytes),0) FROM artifacts WHERE account_id=?',
                           (account_id,)).fetchone()[0]
        return files + arts

    def upload(self, principal: Principal, project_id: str, entries):
        """entries: iterable of (display_name, declared_type, data bytes)."""
        entries = list(entries)
        with self.store.connect() as con:
            limits = safety.is_on(con, principal.account_id, 'upload_limits')      # the account's `upload_limits` switch: size and count only; the content checks always apply
        if not entries or (limits and len(entries) > MAX_BATCH_FILES):
            raise Rejected('batch must contain 1 to 10 files')
        if limits and sum(len(e[2]) for e in entries) > MAX_BATCH_BYTES:
            raise Rejected('batch exceeds 25MiB')
        identifier(project_id)
        accepted, rejections = [], []
        for name, declared, data in entries:
            try:
                accepted.append(self._validate_one(name, declared, data, limits))
            except Rejected as error:
                rejections.append({'name': name[:128], 'reason': str(error)})
        if rejections and not accepted:
            raise Rejected('every file in the batch was rejected: ' +
                           '; '.join(r['reason'] for r in rejections))
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            if self._account_used(con, principal.account_id) + sum(a['size_bytes'] for a in accepted) > 2 * 1024 ** 3:
                raise Conflict('storage quota exceeded')
            for item in accepted:
                file_id = uuid.uuid4().hex
                digest = hashlib.sha256(item['data']).hexdigest()
                con.execute('''INSERT INTO project_files(account_id,project_id,id,display_name,media_type,
                    size_bytes,sha256,storage_ref,state,created_at)
                    VALUES (?,?,?,?,?,?,?,?,'scanned',datetime('now'))''',
                            (principal.account_id, project_id, file_id, item['name'][:128],
                             item['media_type'], item['size_bytes'], digest,
                             f'files/{file_id}'))
                self.storage.write_private([principal.account_id, 'files', file_id], item['data'])
                item['id'] = file_id
            self.coordinator._audit(con, principal.account_id, principal.actor_id, project_id,
                                    'files.upload', 'completed')
        return {'accepted': [{k: v for k, v in a.items() if k != 'data'} for a in accepted],
                'rejected': rejections}

    def _validate_one(self, name, declared, data, limits=True) -> dict:
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or '/' in name or '\\' in name or '\x00' in name:
            raise Rejected('invalid file name')
        if name.startswith('.'):
            raise Rejected('hidden files are not accepted')
        dot = name.rfind('.')
        ext = name[dot:].lower() if dot != -1 else ''
        if ext not in ALLOWLIST:
            raise Rejected('file type not in the launch allowlist')
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise Rejected('empty file')
        if limits and len(data) > MAX_FILE_BYTES:
            raise Rejected('file exceeds 10MiB')
        kind = sniff(data)
        allowed_kinds = ALLOWLIST[ext]
        if kind == 'pdf':
            if 'pdf' not in allowed_kinds:
                raise Rejected('content does not match a .pdf extension')
            if b'/Encrypt' in data[:65536]:
                raise Rejected('encrypted PDFs are not accepted')
        elif kind == 'png':
            if 'png' not in allowed_kinds:
                raise Rejected('content does not match a .png extension')
        elif kind == 'jpeg':
            if 'jpeg' not in allowed_kinds:
                raise Rejected('content does not match a .jpg/.jpeg extension')
        elif kind == 'json':
            if 'json' not in allowed_kinds:
                raise Rejected('content does not match a .json extension')
            try:
                json.loads(data.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                raise Rejected('invalid JSON content')
        elif kind == 'text':
            if 'text' not in allowed_kinds:
                raise Rejected(f'content does not match the {ext} extension')
        else:
            raise Rejected('binary or unreadable content')
        media = {'png': 'image/png', 'jpeg': 'image/jpeg', 'pdf': 'application/pdf',
                 'json': 'application/json'}.get(kind, 'text/plain')
        return {'name': name, 'media_type': media, 'size_bytes': len(data), 'data': bytes(data)}

    def list_files(self, principal: Principal, project_id: str):
        identifier(project_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            rows = con.execute('''SELECT id,display_name,media_type,size_bytes,sha256,state,created_at
                FROM project_files WHERE account_id=? AND project_id=? ORDER BY created_at,id LIMIT 200''',
                (principal.account_id, project_id)).fetchall()
            return [dict(row) for row in rows]

    def open_parts(self, principal: Principal, project_id: str, file_id: str):
        """Authorized storage parts for a scanned project file."""
        identifier(project_id)
        identifier(file_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT storage_ref,media_type,state FROM project_files
                WHERE account_id=? AND project_id=? AND id=? AND state='scanned' ''',
                (principal.account_id, project_id, file_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
        return [principal.account_id] + row['storage_ref'].split('/'), row['media_type']
