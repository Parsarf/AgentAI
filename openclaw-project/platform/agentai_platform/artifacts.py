"""Immutable, versioned artifacts with authorized downloads and bundles.

A version is a database row (artifact id + version number + hash + size);
the storage path is derived server-side and never client-supplied. Downloads
require a customer session to mint a short-lived single-use ticket bound to
account, artifact and version; guessed ids or replayed tickets fail. Bundles
are reproducible ZIPs of a project's latest artifact versions with a manifest,
bounded uncompressed size, no secrets and no unrelated state.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import time
import uuid
import zipfile
from io import BytesIO
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal
from .storage import RootStore

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
MAX_BUNDLE_UNCOMPRESSED = 250 * 1024 * 1024
TICKET_TTL_SECONDS = 300
BUNDLE_MEDIA = 'application/zip'
BUNDLE_SUFFIX = '-bundle.zip'            # "Download all" archives: made on demand, replaced by the next one, never listed as a file
ACCOUNT_QUOTA_BYTES = 2 * 1024 ** 3
NAME_LIMIT = 200
LIST_LIMIT = 500

# Any format may be stored and downloaded; the type only decides what a browser is told. Unknown formats download as plain bytes.
MEDIA = {
    '.txt': 'text/plain', '.md': 'text/markdown', '.csv': 'text/csv', '.tsv': 'text/tab-separated-values', '.json': 'application/json', '.xml': 'application/xml',
    '.yaml': 'application/yaml', '.yml': 'application/yaml', '.html': 'text/html', '.htm': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
    '.py': 'text/x-python', '.ts': 'text/plain', '.tsx': 'text/plain', '.jsx': 'text/plain', '.sql': 'text/plain', '.sh': 'text/plain', '.tex': 'text/plain',
    '.pdf': 'application/pdf', '.rtf': 'application/rtf', '.epub': 'application/epub+zip',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation', '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel',
    '.ppt': 'application/vnd.ms-powerpoint', '.odt': 'application/vnd.oasis.opendocument.text', '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    '.odp': 'application/vnd.oasis.opendocument.presentation',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.bmp': 'image/bmp',
    '.tif': 'image/tiff', '.tiff': 'image/tiff', '.ico': 'image/x-icon',
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.zip': 'application/zip', '.tar': 'application/x-tar', '.gz': 'application/gzip', '.7z': 'application/x-7z-compressed',
    '.ics': 'text/calendar', '.vcf': 'text/vcard', '.glb': 'model/gltf-binary',
}


def media_for(name: str) -> str:
    dot = name.rfind('.')
    return MEDIA.get(name[dot:].lower() if dot != -1 else '', 'application/octet-stream')


def safe_name(name) -> str:
    """A display name: a file name, optionally inside folders ('report/q3.xlsx'). Never a path that could leave anything: bytes are stored under ids, not names."""
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_LIMIT or '\\' in name or '\x00' in name or name.startswith('/'):
        raise ValueError('invalid artifact name')
    for part in name.split('/'):
        if not part.strip() or part.startswith('.') or part in {'.', '..'} or any(ord(ch) < 32 for ch in part):
            raise ValueError('invalid artifact name')
    return name


def base_name(name: str) -> str:
    return name.rsplit('/', 1)[-1]


class ArtifactService:
    def __init__(self, store, *, storage: RootStore, signing_key: bytes, clock=time.time):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError('artifact signing key must be at least 32 bytes')
        self.store = store
        self.storage = storage
        self.key = signing_key
        self.clock = clock
        self.coordinator = Coordinator(store, clock=clock)

    # ---------- capture (trusted host path) ----------

    def capture(self, *, account_id, project_id, task_id, name, media_type, data: bytes) -> dict:
        safe_name(name)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError('empty artifact content')
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError('artifact exceeds 100MiB')
        digest = hashlib.sha256(data).hexdigest()
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            if self.used(con, account_id) + len(data) > ACCOUNT_QUOTA_BYTES:
                raise Conflict('storage quota exceeded')
            artifact_id = uuid.uuid4().hex
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,
                media_type,size_bytes,sha256,storage_ref)
                VALUES (?,?,?,?,1,?,?,?,?,?)''',
                        (account_id, project_id, task_id, artifact_id, name, media_type,
                         len(data), digest, f'artifacts/{artifact_id}/1'))
            self.storage.write_private([account_id, 'artifacts', artifact_id, '1'], bytes(data))
            self.coordinator._audit(con, account_id, 'worker', artifact_id, 'artifact.capture', 'completed')
            return {'artifact_id': artifact_id, 'version': 1, 'sha256': digest, 'size_bytes': len(data)}

    @staticmethod
    def used(con, account_id) -> int:
        """Bytes this account holds: everything Lumina made for it plus everything it uploaded."""
        return sum(con.execute(f'SELECT coalesce(sum(size_bytes),0) FROM {table} WHERE account_id=?', (account_id,)).fetchone()[0] for table in ('artifacts', 'project_files'))

    def capture_or_version(self, *, account_id, project_id, task_id, name, media_type, data: bytes):
        """Trusted host path for files an assistant wrote: same name in the project -> a new version (nothing if unchanged)."""
        safe_name(name)
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError('empty artifact content')
        digest = hashlib.sha256(data).hexdigest()
        with self.coordinator.transaction() as con:
            row = con.execute('''SELECT id,version,sha256 FROM artifacts WHERE account_id=? AND project_id=? AND display_name=?
                ORDER BY created_at DESC, version DESC LIMIT 1''', (account_id, project_id, name)).fetchone()
        if row is None:
            return self.capture(account_id=account_id, project_id=project_id, task_id=task_id, name=name, media_type=media_type, data=data)
        if row['sha256'] == digest:
            return None
        if row['version'] >= 1000 or len(data) > MAX_ARTIFACT_BYTES:
            raise Conflict('version limit reached')
        version = row['version'] + 1
        with self.coordinator.transaction() as con:
            if self.used(con, account_id) + len(data) > ACCOUNT_QUOTA_BYTES:
                raise Conflict('storage quota exceeded')
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,media_type,size_bytes,sha256,storage_ref)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (account_id, project_id, task_id, row['id'], version, name, media_type, len(data), digest,
                                                   f'artifacts/{row["id"]}/{version}'))
            self.storage.write_private([account_id, 'artifacts', row['id'], str(version)], bytes(data))
            self.coordinator._audit(con, account_id, 'worker', row['id'], 'artifact.version', 'completed')
        return {'artifact_id': row['id'], 'version': version, 'sha256': digest, 'size_bytes': len(data)}

    def add_version(self, principal: Principal, artifact_id: str, data: bytes) -> dict:
        """Customers may add a new immutable version of their own artifact."""
        identifier(artifact_id)
        if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError('invalid artifact content')
        digest = hashlib.sha256(data).hexdigest()
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            row = con.execute('''SELECT max(version) AS version FROM artifacts WHERE account_id=? AND id=?''',
                              (principal.account_id, artifact_id)).fetchone()
            if not row or row['version'] is None:
                raise NotFound('unavailable')
            if row['version'] >= 1000:
                raise Conflict('version limit reached')
            if self.used(con, principal.account_id) + len(data) > ACCOUNT_QUOTA_BYTES:
                raise Conflict('storage quota exceeded')
            version = row['version'] + 1
            storage_ref = f'artifacts/{artifact_id}/{version}'
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,
                media_type,size_bytes,sha256,storage_ref)
                SELECT account_id,project_id,task_id,id,?,display_name,media_type,?,?,?
                FROM artifacts WHERE account_id=? AND id=? AND version=?''',
                        (version, len(data), digest, storage_ref, principal.account_id, artifact_id, row['version']))
            self.storage.write_private([principal.account_id, 'artifacts', artifact_id, str(version)], bytes(data))
            self.coordinator._audit(con, principal.account_id, principal.actor_id, artifact_id,
                                    'artifact.version', 'completed')
            return {'artifact_id': artifact_id, 'version': version, 'sha256': digest}

    # ---------- listing ----------

    def list_artifacts(self, principal: Principal, project_id: str):
        identifier(project_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('''SELECT a.id,a.version,a.display_name,a.media_type,a.size_bytes,a.sha256,a.created_at,a.task_id,
                    t.state AS task_state
                FROM artifacts a LEFT JOIN tasks t ON t.account_id=a.account_id AND t.id=a.task_id
                WHERE a.account_id=? AND a.project_id=? ORDER BY a.created_at,a.id,a.version LIMIT 200''',
                (principal.account_id, project_id)).fetchall()
            return [dict(row) for row in rows]

    def list_account(self, principal: Principal):
        """Every version of every file made for this account, newest first, with the chat it came from. One query: the Files page and chat both read this."""
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            rows = con.execute('''SELECT a.id,a.version,a.display_name,a.media_type,a.size_bytes,a.sha256,a.created_at,a.task_id,a.project_id,
                    (SELECT c.id FROM customer_requests r JOIN conversations c ON c.account_id=r.account_id AND c.id=r.conversation_id
                     WHERE r.account_id=a.account_id AND r.id=a.task_id LIMIT 1) AS conversation_id
                FROM artifacts a WHERE a.account_id=? AND NOT (a.media_type=? AND a.display_name LIKE ?)
                ORDER BY a.created_at DESC,a.id,a.version DESC LIMIT ?''',
                (principal.account_id, BUNDLE_MEDIA, '%' + BUNDLE_SUFFIX, LIST_LIMIT)).fetchall()
            return {'files': [dict(row) for row in rows], 'used_bytes': self.used(con, principal.account_id), 'quota_bytes': ACCOUNT_QUOTA_BYTES}

    def delete(self, principal: Principal, artifact_id: str) -> dict:
        """Permanently remove a file: every version, its bytes and any unused download ticket. There is no trash and no copy kept."""
        identifier(artifact_id)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            removed = self._delete(con, principal.account_id, artifact_id)
            if not removed:
                raise NotFound('unavailable')
            self.coordinator._audit(con, principal.account_id, principal.actor_id, artifact_id, 'artifact.delete', 'completed')
        self._unlink(principal.account_id, artifact_id, removed)
        return {'artifact_id': artifact_id, 'versions': len(removed)}

    def _delete(self, con, account_id, artifact_id):
        """Inside a transaction: drop the rows and return the versions whose bytes `_unlink` must remove once it commits."""
        versions = [row['version'] for row in con.execute('SELECT version FROM artifacts WHERE account_id=? AND id=?', (account_id, artifact_id)).fetchall()]
        if versions:
            con.execute('DELETE FROM download_tickets WHERE account_id=? AND artifact_id=?', (account_id, artifact_id))
            con.execute('DELETE FROM artifacts WHERE account_id=? AND id=?', (account_id, artifact_id))
        return versions

    def _unlink(self, account_id, artifact_id, versions):
        """Remove bytes after the rows are gone: a crash in between leaves unreachable bytes, never a listed file with no content."""
        for version in versions:
            try:
                self.storage.delete([account_id, 'artifacts', artifact_id, str(version)])
            except (OSError, ValueError):
                pass
            try:
                self.storage.delete([account_id, 'previews', artifact_id, f'{version}.jpg'])
            except (OSError, ValueError):
                pass
        for folder in ('artifacts', 'previews'):
            try:
                self.storage.remove_empty_dir([account_id, folder, artifact_id])
            except (OSError, ValueError):
                pass

    # ---------- first-page pictures ----------

    def save_preview(self, account_id, artifact_id, version, jpeg: bytes):
        """Keep the first-page picture of one version (made when the file was converted, or the first time it is looked at). Best-effort; removed with the file."""
        if not isinstance(jpeg, bytes) or not jpeg.startswith(b'\xff\xd8\xff') or len(jpeg) > 2_000_000 or type(version) is not int:
            return
        try:
            self.storage.write_private([account_id, 'previews', artifact_id, f'{version}.jpg'], jpeg)
        except (OSError, ValueError):
            pass

    def read_preview(self, account_id, artifact_id, version):
        try:
            return self.storage.read_private([account_id, 'previews', artifact_id, f'{version}.jpg'], max_bytes=2_000_000)
        except (OSError, ValueError):
            return None

    def open_version(self, principal: Principal, artifact_id: str, version: int):
        """-> (storage parts, row) of one version the caller owns, for an inline preview in their own session."""
        identifier(artifact_id)
        if type(version) is not int or version < 1:
            raise NotFound('unavailable')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = self._authorized_version(con, principal, artifact_id, version)
        return [principal.account_id] + row['storage_ref'].split('/'), dict(row)

    def _authorized_version(self, con, principal: Principal, artifact_id, version):
        row = con.execute('''SELECT id,version,display_name,media_type,size_bytes,sha256,storage_ref
            FROM artifacts WHERE account_id=? AND id=? AND version=?''',
            (principal.account_id, artifact_id, version)).fetchone()
        if not row:
            raise NotFound('unavailable')
        return row

    # ---------- tickets ----------

    def _ticket_hash(self, ticket: str) -> str:
        return hmac.new(self.key, ticket.encode(), hashlib.sha256).hexdigest()

    def mint_ticket(self, principal: Principal, artifact_id: str, version: int):
        if type(version) is not int or version < 1:
            raise ValueError('invalid version')
        ticket = secrets_token()
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            row = self._authorized_version(con, principal, artifact_id, version)
            digest = self._ticket_hash(ticket)
            con.execute('''INSERT INTO download_tickets(ticket_hash,account_id,artifact_id,version,
                expires_epoch,created_epoch) VALUES (?,?,?,?,?,?)''',
                (digest, principal.account_id, artifact_id, version, now + TICKET_TTL_SECONDS, now))
            return {'path': f'/v1/artifacts/{artifact_id}/versions/{version}/download?ticket={ticket}',
                    'expires_in': TICKET_TTL_SECONDS, 'size_bytes': row['size_bytes'],
                    'media_type': row['media_type'], 'name': row['display_name']}

    def consume_ticket(self, artifact_id: str, version: int, ticket: str):
        """Single use: consumed or expired tickets never fetch content."""
        if type(version) is not int or version < 1 or not isinstance(ticket, str) or not ticket:
            raise NotFound('unavailable')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            digest = self._ticket_hash(ticket)
            row = con.execute('''SELECT account_id,expires_epoch FROM download_tickets
                WHERE ticket_hash=? AND artifact_id=? AND version=?''', (digest, artifact_id, version)).fetchone()
            if not row or row['expires_epoch'] <= now:
                raise NotFound('unavailable')
            consumed = con.execute('''UPDATE download_tickets SET consumed_epoch=? WHERE ticket_hash=?
                AND consumed_epoch IS NULL''', (now, digest)).rowcount
            if consumed != 1:
                raise NotFound('unavailable')
            art = con.execute('''SELECT storage_ref,display_name,media_type FROM artifacts
                WHERE account_id=? AND id=? AND version=?''',
                (row['account_id'], artifact_id, version)).fetchone()
            if not art:
                raise NotFound('unavailable')
        parts = [row['account_id']] + art['storage_ref'].split('/')
        return parts, art['display_name'], art['media_type']

    # ---------- bundles ----------

    def build_bundle(self, principal: Principal, project_id: str | None = None) -> dict:
        """A ZIP of the newest version of every file in one project, or (no project) in the whole account.

        Made on demand: it replaces the previous archive instead of piling up, and archives are never packed into the next one."""
        if project_id is not None:
            identifier(project_id)
        scope, args = ('AND project_id=?', (project_id,)) if project_id is not None else ('', ())
        not_bundle = 'AND NOT (media_type=? AND display_name LIKE ?)'
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            if project_id is not None and not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?', (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            entries = [dict(row) for row in con.execute(f'''SELECT a.id,a.version,a.display_name,a.media_type,a.size_bytes,a.sha256,a.storage_ref,a.created_at,a.project_id,a.task_id
                FROM artifacts a WHERE a.account_id=? {scope} {not_bundle}
                AND a.version=(SELECT max(version) FROM artifacts b WHERE b.account_id=a.account_id AND b.id=a.id)
                ORDER BY a.id''', (principal.account_id, *args, BUNDLE_MEDIA, '%' + BUNDLE_SUFFIX)).fetchall()]
            old = [row['id'] for row in con.execute(f'''SELECT DISTINCT id FROM artifacts WHERE account_id=? {scope} AND media_type=? AND display_name LIKE ?''',
                                                    (principal.account_id, *args, BUNDLE_MEDIA, '%' + BUNDLE_SUFFIX)).fetchall()]
            if project_id is not None:
                provenance = con.execute('''SELECT id,project_id FROM tasks WHERE account_id=? AND project_id=?
                    ORDER BY created_at DESC,id DESC LIMIT 1''', (principal.account_id, project_id)).fetchone()
            else:
                newest = max(entries, key=lambda e: e['created_at'], default=None)
                provenance = {'id': newest['task_id'], 'project_id': newest['project_id']} if newest else None
        if not entries:
            raise Conflict('no results to bundle')
        if not provenance:
            raise Conflict('bundle requires a task in the project for provenance')
        total = sum(e['size_bytes'] for e in entries)
        if total > MAX_BUNDLE_UNCOMPRESSED:
            raise Conflict('bundle exceeds 250MiB uncompressed')
        buffer = BytesIO()
        manifest = {'project_id': project_id, 'task_id': provenance['id'], 'files': [],
                    'missing': [], 'generated_epoch': int(self.clock())}
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for entry in entries:
                arcname = f"artifacts/{entry['id']}/v{entry['version']}/{entry['display_name']}"
                try:
                    content = self.storage.read_private(
                        [principal.account_id] + entry['storage_ref'].split('/'),
                        max_bytes=MAX_BUNDLE_UNCOMPRESSED)
                except (FileNotFoundError, ValueError):
                    # Content missing from storage: bundle is labeled partial.
                    manifest['missing'].append({'id': entry['id'], 'version': entry['version'],
                                                'name': entry['display_name']})
                    continue
                bundle.writestr(arcname, content)
                manifest['files'].append({'path': arcname, 'sha256': entry['sha256'],
                                          'size_bytes': entry['size_bytes'], 'media_type': entry['media_type'],
                                          'created_at': entry['created_at']})
            bundle.writestr('manifest.json', json.dumps(manifest, indent=1, sort_keys=True))
        payload = buffer.getvalue()
        for artifact_id in old:                                     # the previous archive goes first, so it never counts against the quota twice
            with self.coordinator.transaction() as con:
                removed = self._delete(con, principal.account_id, artifact_id)
            self._unlink(principal.account_id, artifact_id, removed)
        label = project_id[:12] if project_id is not None else 'all'
        result = self.capture(account_id=principal.account_id, project_id=provenance['project_id'], task_id=provenance['id'],
                              name=f'project-{label}{BUNDLE_SUFFIX}', media_type=BUNDLE_MEDIA, data=payload)
        return {**result, 'file_count': len(entries)}


def secrets_token() -> str:
    import secrets as _secrets
    return _secrets.token_urlsafe(32)
