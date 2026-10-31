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
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or '/' in name or '\\' in name or '\x00' in name or name.startswith('.'):
            raise ValueError('invalid artifact name')
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError('empty artifact content')
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError('artifact exceeds 100MiB')
        digest = hashlib.sha256(data).hexdigest()
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            used = con.execute('SELECT coalesce(sum(size_bytes),0) FROM artifacts WHERE account_id=?',
                               (account_id,)).fetchone()[0]
            if used + len(data) > 2 * 1024 ** 3:
                raise Conflict('storage quota exceeded')
            artifact_id = uuid.uuid4().hex
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,
                media_type,size_bytes,sha256,storage_ref)
                VALUES (?,?,?,?,1,?,?,?,?,?)''',
                        (account_id, project_id, task_id, artifact_id, name[:128], media_type,
                         len(data), digest, f'artifacts/{artifact_id}/1'))
            self.storage.write_private([account_id, 'artifacts', artifact_id, '1'], bytes(data))
            self.coordinator._audit(con, account_id, 'worker', artifact_id, 'artifact.capture', 'completed')
            return {'artifact_id': artifact_id, 'version': 1, 'sha256': digest, 'size_bytes': len(data)}

    def capture_or_version(self, *, account_id, project_id, task_id, name, media_type, data: bytes):
        """Trusted host path for files an assistant wrote: same name in the project -> a new version (nothing if unchanged)."""
        digest = hashlib.sha256(data).hexdigest()
        with self.coordinator.transaction() as con:
            row = con.execute('''SELECT id,version,sha256 FROM artifacts WHERE account_id=? AND project_id=? AND display_name=?
                ORDER BY created_at DESC, version DESC LIMIT 1''', (account_id, project_id, name[:128])).fetchone()
        if row is None:
            return self.capture(account_id=account_id, project_id=project_id, task_id=task_id, name=name, media_type=media_type, data=data)
        if row['sha256'] == digest:
            return None
        if row['version'] >= 1000 or len(data) > MAX_ARTIFACT_BYTES:
            raise Conflict('version limit reached')
        version = row['version'] + 1
        with self.coordinator.transaction() as con:
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,media_type,size_bytes,sha256,storage_ref)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (account_id, project_id, task_id, row['id'], version, name[:128], media_type, len(data), digest,
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
            row = con.execute('''SELECT version FROM artifacts WHERE account_id=? AND id=?''',
                              (principal.account_id, artifact_id)).fetchone()
            if not row:
                raise NotFound('unavailable')
            if row['version'] >= 1000:
                raise Conflict('version limit reached')
            version = row['version'] + 1
            storage_ref = f'artifacts/{artifact_id}/{version}'
            con.execute('''INSERT INTO artifacts(account_id,project_id,task_id,id,version,display_name,
                media_type,size_bytes,sha256,storage_ref)
                SELECT account_id,project_id,task_id,id,?,display_name,media_type,?,?,?
                FROM artifacts WHERE account_id=? AND id=?''',
                        (version, len(data), digest, storage_ref, principal.account_id, artifact_id))
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

    def build_bundle(self, principal: Principal, project_id: str) -> dict:
        identifier(project_id)
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            if not con.execute('SELECT 1 FROM projects WHERE account_id=? AND id=?',
                               (principal.account_id, project_id)).fetchone():
                raise NotFound('unavailable')
            latest = con.execute('''SELECT id, max(version) AS v FROM artifacts WHERE account_id=? AND project_id=?
                GROUP BY id ORDER BY id''', (principal.account_id, project_id)).fetchall()
            entries = []
            for row in latest:
                art = con.execute('''SELECT id,version,display_name,media_type,size_bytes,sha256,storage_ref,created_at
                    FROM artifacts WHERE account_id=? AND id=? AND version=?''',
                    (principal.account_id, row['id'], row['v'])).fetchone()
                entries.append(dict(art))
            provenance = con.execute('''SELECT id FROM tasks WHERE account_id=? AND project_id=?
                ORDER BY created_at DESC,id DESC LIMIT 1''', (principal.account_id, project_id)).fetchone()
        if not entries:
            raise Conflict('no results to bundle')
        if not provenance:
            raise Conflict('bundle requires a task in the project for provenance')
        total = sum(e['size_bytes'] for e in entries)
        if total > MAX_BUNDLE_UNCOMPRESSED:
            raise Conflict('bundle exceeds 250MiB uncompressed')
        buffer = BytesIO()
        manifest = {'project_id': project_id, 'task_id': provenance[0], 'files': [],
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
        result = self.capture(account_id=principal.account_id, project_id=project_id, task_id=provenance[0],
                              name=f'project-{project_id[:12]}-bundle.zip', media_type=BUNDLE_MEDIA, data=payload)
        return {**result, 'file_count': len(entries)}


def secrets_token() -> str:
    import secrets as _secrets
    return _secrets.token_urlsafe(32)
