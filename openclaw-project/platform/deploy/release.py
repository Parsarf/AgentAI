#!/usr/bin/env python3
"""Canary release with schema-compatible rollback (host-run, root).

  release.py --tarball /root/release.tgz --id 20261012T2000Z-name [--dry-run]

1. Build the new release beside the live one (venv from the hash-pinned lock).
2. Copy the live database, migrate the COPY with the new code and start the new release on a loopback canary
   port against it; probe it. Nothing live is touched until this passes.
3. Start the PREVIOUS release against the migrated copy. If it still answers, a binary rollback is safe; if not,
   rollback means restoring the pre-migration database backup. The result is recorded either way.
4. Briefly stop the app, take a final database backup, migrate the live database, switch the `current` link,
   start, and probe. Any failure switches back (and restores the backup when the old code cannot read the new schema).
Exit 0 released, 2 rolled back, 1 refused before touching anything.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path('/opt/agentai-platform')
STATE = Path('/var/lib/agentai-platform')
DRILL_FAIL = False
ENV_FILE = Path('/etc/agentai-platform/accounts.env')
LOG = Path('/var/lib/agentai-ops/releases.log')
PROBES = [('/healthz', 200), ('/readyz', 200), ('/account/login/', 200), ('/v1/me', 401), ('/v1/billing/webhook', 405)]


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def read_env(path=ENV_FILE):
    env = {}
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, _, v = line.partition('='); env[k.strip()] = v.strip().strip('"\'')
    return env


def as_app_user(argv, env, cwd):
    import pwd
    user = pwd.getpwnam('agentai-platform')
    return subprocess.Popen(['setpriv', '--reuid', str(user.pw_uid), '--regid', str(user.pw_gid), '--clear-groups', *argv], env=env, cwd=cwd,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)


def sqlite_copy(src, dst):
    a = sqlite3.connect(f'file:{src}?mode=ro', uri=True); b = sqlite3.connect(dst)
    try: a.backup(b)
    finally: b.close(); a.close()
    check = sqlite3.connect(dst)
    try:
        if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('database copy failed its integrity check')
    finally: check.close()
    os.chmod(dst, 0o600)


def probe(port, expected=PROBES, wait=40):
    deadline, results = time.time() + wait, {}
    while time.time() < deadline:
        results = {}
        for path, want in expected:
            req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers={'X-Forwarded-Proto': 'https', 'Host': 'getlumina.pro'})
            try:
                with urllib.request.urlopen(req, timeout=5) as r: code = r.status
            except urllib.error.HTTPError as e: code = e.code
            except OSError: code = 0
            results[path] = (code, want)
        if all(c == w for c, w in results.values()): return True, results
        time.sleep(1.5)
    return False, results


class SystemdControl:
    port = 18800
    def stop(self): run(['systemctl', 'stop', 'agentai-platform-app']); run(['systemctl', 'stop', 'agentai-billing-worker.timer'])
    def start(self): run(['systemctl', 'start', 'agentai-platform-app'])
    def timers_start(self): run(['systemctl', 'start', 'agentai-billing-worker.timer'])


class SandboxControl:
    """Drill stand-in for systemd: the 'live' instance is a throwaway process on its own port."""
    def __init__(self, box, env, port): self.box, self.env, self.port, self.proc = box, env, port, None
    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired: self.proc.kill()
    def start(self):
        release = Path(os.path.realpath(self.box / 'current'))
        self.proc = as_app_user([str(release / '.venv/bin/gunicorn'), '-c', 'deploy/gunicorn.conf.py', '--bind', f'127.0.0.1:{self.port}', 'accounts.wsgi:application'],
                                {**self.env, 'AGENTAI_STATE_DIR': str(STATE), 'PATH': '/usr/bin:/bin'}, release)
    def timers_start(self): pass


CONTROL = SystemdControl()


class Canary:
    """One release served on a loopback port against a database copy as the unprivileged app user."""

    def __init__(self, release, db_copy_dir, port, env):
        self.release, self.port = Path(release), port
        self.env = {**env, 'AGENTAI_STATE_DIR': str(db_copy_dir), 'PATH': '/usr/bin:/bin'}
        self.proc = None

    def migrate(self):
        p = as_app_user([str(self.release / '.venv/bin/python'), 'manage.py', 'bootstrap_accounts'], self.env, self.release)
        _, err = p.communicate(timeout=300)
        return p.returncode == 0, err.decode()[-300:]

    def start(self):
        self.proc = as_app_user([str(self.release / '.venv/bin/gunicorn'), '-c', 'deploy/gunicorn.conf.py', '--bind', f'127.0.0.1:{self.port}', 'accounts.wsgi:application'],
                                self.env, self.release)
        return probe(self.port)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired: self.proc.kill()


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('--tarball', required=True); ap.add_argument('--id', required=True); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sandbox', help='run the whole procedure against a throwaway copy in this directory (drills): own release tree, own database copy, own port, no systemd')
    ap.add_argument('--drill-fail-live', action='store_true', help='drill only: pretend the live probes failed so the rollback path runs')
    args = ap.parse_args(argv)
    global ROOT, STATE, CONTROL, DRILL_FAIL
    DRILL_FAIL = args.drill_fail_live
    if args.sandbox:
        box = Path(args.sandbox); (box / 'releases').mkdir(parents=True, exist_ok=True); (box / 'state').mkdir(exist_ok=True)
        live_release = Path(os.path.realpath('/opt/agentai-platform/current'))
        if not (box / 'current').exists(): os.symlink(live_release, box / 'current')
        sqlite_copy('/var/lib/agentai-platform/platform.sqlite3', box / 'state' / 'platform.sqlite3')
        for d in (box, box / 'state'): shutil.chown(d, 'agentai-platform', 'agentai-platform')
        shutil.chown(box / 'state' / 'platform.sqlite3', 'agentai-platform', 'agentai-platform'); (box / 'state').chmod(0o700)   # the app refuses a state tree that is not private
        ROOT, STATE = box, box / 'state'
        CONTROL = SandboxControl(box, read_env(), 18897)
    report = {'release': args.id, 'steps': [], 'result': 'refused'}
    def step(name, ok, detail=''):
        report['steps'].append({'step': name, 'ok': bool(ok), 'detail': str(detail)[:200]}); print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else ' :: ' + str(detail)[:400]), flush=True); return ok
    current = ROOT / 'current'; previous = Path(os.path.realpath(current)); new = ROOT / 'releases' / args.id
    if new.exists(): step('release id is unused', False, str(new)); return finish(report, 1)
    try:
        new.mkdir(parents=True); run(['tar', '-xzf', args.tarball, '-C', str(new)], check=True)
        run([sys.executable, '-m', 'venv', str(new / '.venv')], check=True)
        pip = run([str(new / '.venv/bin/pip'), 'install', '-q', '--require-hashes', '--no-deps', '-r', str(new / 'requirements.lock')])
        step('build release (hash-pinned dependencies)', pip.returncode == 0, pip.stderr[-200:])
        if pip.returncode: shutil.rmtree(new, ignore_errors=True); return finish(report, 1)
        run(['chown', '-R', 'root:root', str(new)]); run(['chmod', '-R', 'go-w', str(new)])
        env = read_env()
        with tempfile.TemporaryDirectory(prefix='canary-', dir=STATE) as scratch:   # inside the app's own state tree so the app user can reach it
            scratch = Path(scratch); shutil.chown(scratch, 'agentai-platform', 'agentai-platform'); scratch.chmod(0o700)
            new_state, old_state = scratch / 'new', scratch / 'old'
            for d in (new_state, old_state): d.mkdir(); shutil.chown(d, 'agentai-platform', 'agentai-platform'); d.chmod(0o700)
            sqlite_copy(STATE / 'platform.sqlite3', new_state / 'platform.sqlite3'); shutil.chown(new_state / 'platform.sqlite3', 'agentai-platform', 'agentai-platform')
            canary = Canary(new, new_state, 18899, env)
            ok, why = canary.migrate(); step('migrate a COPY of the database with the new release', ok, why)
            good, results = (canary.start() if ok else (False, {}))
            step('new release passes its canary probes on the copy', good, json.dumps(results))
            canary.stop()
            if not (ok and good): shutil.rmtree(new, ignore_errors=True); return finish(report, 1)
            # Would the previous release still run on the migrated schema?
            shutil.copy2(new_state / 'platform.sqlite3', old_state / 'platform.sqlite3'); shutil.chown(old_state / 'platform.sqlite3', 'agentai-platform', 'agentai-platform')
            old_canary = Canary(previous, old_state, 18898, env)
            compatible, old_results = old_canary.start(); old_canary.stop()
            report['binary_rollback_compatible'] = compatible
            step('previous release still serves the migrated schema (binary rollback possible)' if compatible else 'previous release cannot read the new schema: rollback = restore the pre-migration backup', True, json.dumps(old_results))
        if args.dry_run:
            step('dry run: stopping before any live change', True); shutil.rmtree(new, ignore_errors=True); return finish(report, 0, 'dry-run-passed')
        return apply_live(report, step, new, previous, compatible)
    except Exception as exc:   # anything unexpected before the live switch leaves the live release untouched
        step('unexpected error before the live switch', False, repr(exc)); shutil.rmtree(new, ignore_errors=True); return finish(report, 1)


def apply_live(report, step, new, previous, compatible):
    env = read_env(); current = ROOT / 'current'
    backup = STATE / f'backup-{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-premigrate-{new.name}.sqlite3'
    CONTROL.stop()
    try:
        sqlite_copy(STATE / 'platform.sqlite3', backup); step('final database backup with the app stopped', True, backup.name)
        migrate = Canary(new, STATE, 0, env); ok, why = migrate.migrate(); step('migrate the live database', ok, why)
        if not ok: raise RuntimeError('live migration failed')
        tmp = ROOT / '.current.new'; tmp.unlink(missing_ok=True); os.symlink(new, tmp); os.replace(tmp, current)
        CONTROL.start(); good, results = probe(CONTROL.port, wait=60)
        if DRILL_FAIL: good = False; results = {'drill': 'forced failure'}
        step('live release answers its probes', good, json.dumps(results))
        if not good: raise RuntimeError('live release unhealthy')
        CONTROL.timers_start()
        return finish(report, 0, 'released')
    except Exception as exc:
        step('ROLLING BACK', True, repr(exc))
        CONTROL.stop()
        tmp = ROOT / '.current.new'; tmp.unlink(missing_ok=True); os.symlink(previous, tmp); os.replace(tmp, current)
        if not compatible:
            shutil.copy2(backup, STATE / 'platform.sqlite3'); shutil.chown(STATE / 'platform.sqlite3', 'agentai-platform', 'agentai-platform')
            for suffix in ('-wal', '-shm'): (STATE / f'platform.sqlite3{suffix}').unlink(missing_ok=True)
            step('restored the pre-migration database (old code cannot read the new schema)', True)
        CONTROL.start(); good, results = probe(CONTROL.port, wait=60)
        step('previous release serves again after rollback', good, json.dumps(results))
        CONTROL.timers_start()
        return finish(report, 2, 'rolled-back')


def finish(report, code, result=None):
    report['result'] = result or report['result']
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a') as handle: handle.write(json.dumps({'at': int(time.time()), **report}) + '\n')
    except OSError: pass
    print(json.dumps({'result': report['result'], 'binary_rollback_compatible': report.get('binary_rollback_compatible')}))
    return code


if __name__ == '__main__':
    sys.exit(main())
