"""Consistency-aware, encrypted, verified backup sets with per-tenant manifests and bounded retention.

A set is written only after every artifact was verified in plain form, encrypted to the owner's
public key, and re-checked at the destination. A set with any failed source is recorded as incomplete,
never counted for freshness and never allowed to cause pruning of older complete sets.
Plain copies exist only inside a private work directory and are removed in all cases.
"""
import calendar
from dataclasses import dataclass
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
import uuid

SET_ID = re.compile(r'\d{8}T\d{6}Z')
KEEP_DAILY, KEEP_WEEKLY, KEEP_MONTHLY = 14, 8, 6


class BackupError(Exception): pass
class StaleSource(BackupError): pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while chunk := handle.read(1 << 20): digest.update(chunk)
    return digest.hexdigest()


def tenant_hash(tenant_ref):
    """Stable, non-reversible label so manifests and alerts never carry the tenant reference itself."""
    return hashlib.sha256(('tenant-label:' + tenant_ref).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- verification

def verify_sqlite(path):
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise BackupError('sqlite integrity check failed')
        if con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] < 1: raise BackupError('sqlite snapshot is empty')
    finally: con.close()


def verify_tar(path):
    try:
        with tarfile.open(path, 'r:gz') as archive:
            count = 0
            for member in archive:
                if member.name.startswith('/') or '..' in Path(member.name).parts: raise BackupError('unsafe archive member')
                count += 1
            if count == 0: raise BackupError('archive is empty')
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError('archive is not a readable gzip tar') from exc


def verify_pgdump(path):
    with open(path, 'rb') as handle: head = handle.read(4096)
    if b'PostgreSQL database dump' not in head: raise BackupError('not a PostgreSQL dump')
    if os.path.getsize(path) < 1024: raise BackupError('dump is implausibly small')


def verify_json(path):
    try:
        if not isinstance(json.loads(Path(path).read_text()), dict): raise BackupError('json document is not an object')
    except ValueError as exc:
        raise BackupError('not valid JSON') from exc


VERIFIERS = {'sqlite': verify_sqlite, 'tar': verify_tar, 'pgdump': verify_pgdump, 'json': verify_json}


# --------------------------------------------------------------------- sources

@dataclass
class Source:
    name: str            # file name stem, e.g. app-db
    kind: str            # key of VERIFIERS
    produce: object      # callable(work_dir: Path) -> Path (plain artifact)
    tenant: str | None = None
    asset: str = ''      # inventory asset id this source covers
    optional: bool = False   # a miss is a warning (e.g. a running cell cannot be archived), not a failed set


def sqlite_source(name, db_path, asset=''):
    def produce(work):
        out = work / f'{name}.sqlite3'
        src = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        dst = sqlite3.connect(out)
        try: src.backup(dst)   # online backup API: consistent while the app keeps writing
        finally: dst.close(); src.close()
        return out
    return Source(name, 'sqlite', produce, asset=asset)


def files_source(name, paths, asset='', missing_ok=True):
    def produce(work):
        out = work / f'{name}.tar.gz'
        found = 0
        with tarfile.open(out, 'w:gz') as archive:
            for path in paths:
                path = Path(path)
                if path.exists():
                    archive.add(path, arcname=str(path).lstrip('/')); found += 1
                elif not missing_ok: raise BackupError(f'required path missing: {path.name}')
        if found == 0: raise BackupError('none of the listed files exist')
        return out
    return Source(name, 'tar', produce, asset=asset)


def latest_file_source(name, directory, pattern, kind, max_age_seconds, clock=time.time, asset='', tenant=None):
    def produce(work):
        matches = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches: raise StaleSource(f'no file matching {pattern}')
        newest = matches[0]
        if clock() - newest.stat().st_mtime > max_age_seconds: raise StaleSource(f'newest {pattern} is older than the freshness bound')
        out = work / (name + ('.tar.gz' if newest.name.endswith('.tar.gz') else newest.suffix))
        shutil.copyfile(newest, out)
        return out
    return Source(name, kind, produce, tenant=tenant, asset=asset)


# ------------------------------------------------------------------- retention

def select_keep(set_ids, now, daily=KEEP_DAILY, weekly=KEEP_WEEKLY, monthly=KEEP_MONTHLY):
    """Newest set always; then newest-per-day, per-ISO-week and per-month within the bounds."""
    parsed = sorted(((calendar.timegm(time.strptime(s, '%Y%m%dT%H%M%SZ')), s) for s in set_ids), reverse=True)
    keep = {parsed[0][1]} if parsed else set()
    for limit, key in ((daily, lambda t: time.strftime('%Y%m%d', time.gmtime(t))),
                       (weekly, lambda t: '%d-%02d' % datetime.date.fromtimestamp(t).isocalendar()[:2]),
                       (monthly, lambda t: time.strftime('%Y%m', time.gmtime(t)))):
        seen = []
        for stamp, sid in parsed:
            label = key(stamp)
            if label not in seen:
                seen.append(label)
                if len(seen) <= limit: keep.add(sid)
    return keep


# ------------------------------------------------------------------------- job

class BackupJob:
    def __init__(self, sources, crypto, destinations, *, work_root, status_path, clock=time.time, alert=None,
                 release=None, expected_assets=()):
        self.sources, self.crypto, self.destinations = list(sources), crypto, list(destinations)
        self.work_root, self.status_path, self.clock, self.alert = Path(work_root), Path(status_path), clock, alert
        self.release, self.expected_assets = release, tuple(expected_assets)

    def _set_id(self): return time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(self.clock()))

    def run(self):
        set_id = self._set_id()
        self.work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='bk-', dir=self.work_root)); work.chmod(0o700)
        artifacts, failures, warnings = [], [], []
        try:
            for source in self.sources:
                try: artifacts.append(self._one(source, work))
                except Exception as exc:
                    entry = {'source': source.name, 'tenant': tenant_hash(source.tenant) if source.tenant else None,
                             'error': type(exc).__name__ + ': ' + str(exc)[:160]}
                    (warnings if source.optional else failures).append(entry)
            covered = {a['asset'] for a in artifacts if a['asset']}
            missing_assets = sorted(set(self.expected_assets) - covered)
            complete = not failures and not missing_assets
            manifest = {'set_id': set_id, 'created_epoch': int(self.clock()), 'complete': complete, 'release': self.release,
                        'artifacts': artifacts, 'failures': failures, 'warnings': warnings, 'missing_assets': missing_assets,
                        'destinations': [{'kind': d.kind, 'offsite': bool(d.offsite)} for d in self.destinations],
                        'encryption': 'age (public recipients only on host)'}
            delivered = self._deliver(set_id, manifest, work) if artifacts else {}
            offsite_ok = any(d.offsite and delivered.get(i) for i, d in enumerate(self.destinations))
            report = {'set_id': set_id, 'complete': complete, 'failures': failures, 'warnings': warnings, 'missing_assets': missing_assets,
                      'delivered': delivered, 'offsite_copy': offsite_ok, 'artifacts': len(artifacts)}
            if complete and all(delivered.get(i) for i in range(len(self.destinations))): self._prune()
            else: report['complete'] = False
            self._status(report)
            if not report['complete'] and self.alert: self.alert('backup_failed', report)
            return report
        finally:
            shutil.rmtree(work, ignore_errors=True)   # plain artifacts never outlive the run

    def _one(self, source, work):
        plain = Path(source.produce(work))
        VERIFIERS[source.kind](plain)
        plain_hash, plain_size = sha256_file(plain), plain.stat().st_size
        encrypted = work / (plain.name + '.age')
        self.crypto.encrypt(plain, encrypted)
        plain.unlink()
        return {'name': encrypted.name, 'source': source.name, 'kind': source.kind, 'asset': source.asset,
                'tenant': tenant_hash(source.tenant) if source.tenant else None, 'plain_sha256': plain_hash,
                'plain_bytes': plain_size, 'sha256': sha256_file(encrypted), 'bytes': encrypted.stat().st_size}

    def _deliver(self, set_id, manifest, work):
        base = f'sets/{set_id}'
        results = {}
        manifest_path = work / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        tenant_manifests = {}
        for art in manifest['artifacts']:
            if art['tenant']: tenant_manifests.setdefault(art['tenant'], []).append(art)
        for label, arts in tenant_manifests.items():
            (work / f'tenant-{label}.manifest.json').write_text(json.dumps(
                {'set_id': set_id, 'tenant': label, 'artifacts': arts}, indent=2, sort_keys=True))
        for index, dest in enumerate(self.destinations):
            try:
                for art in manifest['artifacts']:
                    dest.put(work / art['name'], f"{base}/{art['name']}")
                    if dest.size(f"{base}/{art['name']}") != art['bytes']: raise BackupError('size mismatch after copy')
                for label in tenant_manifests: dest.put(work / f'tenant-{label}.manifest.json', f'{base}/tenant-{label}.manifest.json')
                dest.put(manifest_path, f'{base}/manifest.json')   # manifest last: a set without one is incomplete
                results[index] = True
            except Exception:
                results[index] = False
        return results

    def _prune(self):
        for dest in self.destinations:
            try:
                names = [n for n, _, _ in dest.list('sets/')]
                complete = sorted({n.split('/')[1] for n in names if n.endswith('/manifest.json') and SET_ID.fullmatch(n.split('/')[1])})
                keep = select_keep(complete, self.clock())
                for sid in {n.split('/')[1] for n in names if SET_ID.fullmatch(n.split('/')[1])}:
                    # Only exact set ids under sets/ are ever removed; sets without a manifest are partial leftovers.
                    if sid not in keep:
                        for n in [n for n in names if n.startswith(f'sets/{sid}/')]: dest.remove(n)
            except Exception:
                continue   # pruning failure must never fail or shrink a good backup

    def _status(self, report):
        previous = {}
        try: previous = json.loads(self.status_path.read_text())
        except (OSError, ValueError): pass
        status = {'updated_epoch': int(self.clock()), 'last_set': report['set_id'], 'last_complete': report['complete'],
                  'last_success_epoch': int(self.clock()) if report['complete'] else previous.get('last_success_epoch'),
                  'last_success_set': report['set_id'] if report['complete'] else previous.get('last_success_set'),
                  'offsite_copy': report['offsite_copy'],
                  'last_offsite_epoch': int(self.clock()) if report['offsite_copy'] and report['complete'] else previous.get('last_offsite_epoch'),
                  'failures': report['failures'], 'warnings': report.get('warnings', []), 'missing_assets': report['missing_assets']}
        tmp = self.status_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(status, indent=2)); os.chmod(tmp, 0o640); os.replace(tmp, self.status_path)
