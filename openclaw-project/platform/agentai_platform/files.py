"""Customer project files: allowlist validation, quarantine and quotas.

Contract rules (product/CONTRACT.md): content is validated independently of
the client-declared type; text must be valid UTF-8 without NUL; JSON must
parse; PNG/JPEG/PDF are checked by signature; executables, archives and
macros never pass; sizes are 10MiB/file, 25MiB/batch, 10 files/batch.
Uploads stay disabled unless the host enables them (AGENTAI_UPLOADS_ENABLED=1) and the owner's `customer_uploads` switch is on. Every file passes the content
scan (content_scan.py) BEFORE it is stored: what the scan refuses is never written, so there is nothing quarantined to serve. Word, Excel and PowerPoint are accepted in
their modern formats only, never with macros. A file with the same content as one the account already has is linked to it, not stored twice (roadmap #30).
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from . import content_scan, safety
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
    '.gif': ('gif',), '.webp': ('webp',), '.docx': ('docx',), '.xlsx': ('xlsx',), '.pptx': ('pptx',),
    '.eml': ('text',), '.htm': ('text',), '.tsv': ('text',), '.markdown': ('text',), '.log': ('text',), '.xml': ('text',), '.yaml': ('text',), '.yml': ('text',),
}
MEDIA = {'png': 'image/png', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp', 'pdf': 'application/pdf', 'json': 'application/json',
         'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
TEXT_MEDIA = {'.csv': 'text/csv', '.tsv': 'text/tab-separated-values', '.md': 'text/markdown', '.markdown': 'text/markdown', '.html': 'text/html', '.htm': 'text/html',
              '.eml': 'message/rfc822'}
ACCOUNT_QUOTA = 2 * 1024 ** 3

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
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data.startswith(b'PK\x03\x04'):
        return content_scan.office_kind(data) or 'archive'      # a modern Office file is a zip; any other zip is an archive and never passes
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
    def __init__(self, store, *, storage: RootStore, clock=time.time, engine=None):
        self.store = store
        self.storage = storage
        self.clock = clock
        self.engine = engine          # an optional scanning engine on this host (content_scan.scan); None: the structural scan alone
        self.coordinator = Coordinator(store, clock=clock)

    def _account_used(self, con, account_id):
        files = con.execute('SELECT coalesce(sum(size_bytes),0) FROM project_files WHERE account_id=?',
                            (account_id,)).fetchone()[0]
        arts = con.execute('SELECT coalesce(sum(size_bytes),0) FROM artifacts WHERE account_id=?',
                           (account_id,)).fetchone()[0]
        return files + arts

    def upload(self, principal: Principal, project_id: str, entries, *, folder_id: str | None = None):
        """entries: iterable of (display_name, declared_type, data bytes). Each file is validated and scanned on its own: one refused file does not refuse the others.
        A file whose content the account already has is linked to that one (`same_as`) and its bytes are not stored again."""
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
            if folder_id is not None and not con.execute('SELECT 1 FROM file_folders WHERE account_id=? AND project_id=? AND id=?',
                                                         (principal.account_id, project_id, identifier(folder_id))).fetchone():
                raise NotFound('unavailable')
            for item in accepted:
                item['sha256'] = hashlib.sha256(item['data']).hexdigest()
                item['twin'] = con.execute("SELECT id,storage_ref,project_id FROM project_files WHERE account_id=? AND sha256=? AND state='scanned' ORDER BY created_at,id LIMIT 1",
                                           (principal.account_id, item['sha256'])).fetchone()
            new_bytes = sum(a['size_bytes'] for a in accepted if a['twin'] is None)
            if self._account_used(con, principal.account_id) + new_bytes > ACCOUNT_QUOTA:
                raise Conflict('storage quota exceeded')
            for item in accepted:
                twin = item.pop('twin')
                if twin is not None and twin['project_id'] == project_id and folder_id is None:
                    item['id'], item['same_as'], item['already_here'] = twin['id'], twin['id'], True      # the very same file in the same place: nothing new is recorded
                    continue
                file_id = uuid.uuid4().hex
                con.execute('''INSERT INTO project_files(account_id,project_id,id,display_name,media_type,
                    size_bytes,sha256,storage_ref,state,created_at,shares_with)
                    VALUES (?,?,?,?,?,?,?,?,'scanned',datetime('now'),?)''',
                            (principal.account_id, project_id, file_id, item['name'][:128],
                             item['media_type'], item['size_bytes'], item['sha256'],
                             twin['storage_ref'] if twin is not None else f'files/{file_id}', twin['id'] if twin is not None else None))
                if twin is None:
                    self.storage.write_private([principal.account_id, 'files', file_id], item['data'])
                else:
                    item['same_as'] = twin['id']
                if folder_id is not None:
                    con.execute("INSERT INTO file_places(account_id,kind,object_id,folder_id,updated_epoch) VALUES (?,'upload',?,?,?)", (principal.account_id, file_id, folder_id, now))
                item['id'] = file_id
            self.coordinator._audit(con, principal.account_id, principal.actor_id, project_id,
                                    'files.upload', 'completed')
        return {'accepted': [{k: v for k, v in a.items() if k != 'data'} for a in accepted],
                'rejected': rejections}

    def delete_upload(self, principal: Principal, file_id: str) -> dict:
        """Remove an upload for good. Its bytes go with it unless another upload shares them (the same content uploaded twice)."""
        identifier(file_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT storage_ref FROM project_files WHERE account_id=? AND id=?', (principal.account_id, file_id)).fetchone()
            if row is None:
                raise NotFound('unavailable')
            con.execute("DELETE FROM file_places WHERE account_id=? AND kind='upload' AND object_id=?", (principal.account_id, file_id))
            con.execute('DELETE FROM project_files WHERE account_id=? AND id=?', (principal.account_id, file_id))
            shared = con.execute('SELECT 1 FROM project_files WHERE account_id=? AND storage_ref=? LIMIT 1', (principal.account_id, row['storage_ref'])).fetchone() is not None
            self.coordinator._audit(con, principal.account_id, principal.actor_id, file_id, 'files.delete', 'completed')
        if not shared:
            try:
                self.storage.delete([principal.account_id] + row['storage_ref'].split('/'))
            except (OSError, ValueError):
                pass                                            # the row is gone; an orphaned blob is removed with the account
        return {'file_id': file_id, 'bytes_removed': not shared}

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
            if 'json' in allowed_kinds:                       # JSON is text that must also parse
                kind = 'json'
                try:
                    json.loads(data.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    raise Rejected('invalid JSON content')
            elif 'text' not in allowed_kinds:
                raise Rejected(f'content does not match the {ext} extension')
        elif kind in ('gif', 'webp', 'docx', 'xlsx', 'pptx'):
            if kind not in allowed_kinds:
                raise Rejected(f'content does not match the {ext} extension')
        elif kind == 'archive':
            raise Rejected('archives are not accepted')
        else:
            raise Rejected('binary or unreadable content')
        try:
            content_scan.scan(kind, bytes(data), engine=self.engine)
        except content_scan.Refused as refused:
            raise Rejected(str(refused)) from None
        media = MEDIA.get(kind) or TEXT_MEDIA.get(ext, 'text/plain')
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
