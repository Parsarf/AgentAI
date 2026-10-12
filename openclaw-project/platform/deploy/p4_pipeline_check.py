#!/usr/bin/env python3
"""Disposable end-to-end pipeline check: queue -> worker -> socket -> supervisor -> Fleet cells.

Host-run (root). Scratch app database, scratch supervisor state and socket, throwaway
accounts and real cells under gVisor. The worker runs as the unprivileged app user.
Never touches the production account database or custody. Exit 0 only if all pass.
"""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.environ.get('AGENTAI_PLATFORM', '/opt/agentai-supervisor/current'))
from agentai_platform.security import Principal                                     # noqa: E402
from agentai_platform.store import Store                                            # noqa: E402
from agentai_platform.lifecycle.coordinator import Coordinator                      # noqa: E402
from agentai_platform.lifecycle.native_wiring import build_native_backend           # noqa: E402

IMAGE = 'ghcr.io/openclaw/openclaw@sha256:62832668e3e5e139f745f7d3df892c9251eb53318b7d14a76c410dde1f25d730'
APP = pwd.getpwnam('agentai-platform')
ROOT = Path('/var/lib/agentai-p4pipe')
results = []


def record(name, ok, detail=''):
    results.append({'check': name, 'pass': bool(ok), 'detail': str(detail)[:300]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)
    return ok


def worker_tick(db, sock):
    done = subprocess.run(
        ['setpriv', '--reuid', str(APP.pw_uid), '--regid', str(APP.pw_gid), '--clear-groups',
         'env', f'PYTHONPATH={os.environ.get("AGENTAI_PLATFORM", "/opt/agentai-supervisor/current")}',
         'python3', '-m', 'agentai_platform.lifecycle.worker_main', '--db', str(db), '--socket', str(sock), '--once'],
        capture_output=True, text=True, timeout=600)
    try:
        return json.loads(done.stdout.strip().splitlines()[-1])
    except Exception:
        return {'error': (done.stderr or done.stdout)[-300:]}


def main():
    evidence = Path(sys.argv[1])
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(mode=0o755)
    state = ROOT / 'app'
    store = Store(state / 'db.sqlite3')
    store.initialize()
    shutil.chown(state, APP.pw_uid, APP.pw_gid)
    os.chmod(state, 0o700)
    for suffix in ('', '-wal', '-shm'):
        p = Path(str(state / 'db.sqlite3') + suffix)
        if p.exists():
            shutil.chown(p, APP.pw_uid, APP.pw_gid)
    engine = Coordinator(store, profiles={'trial-measured-v1'})
    with store.connect() as con:
        con.execute('CREATE TABLE auth_user(id INTEGER PRIMARY KEY,is_active INTEGER)')
        con.execute('CREATE TABLE accounts_identity(user_id INTEGER,role TEXT,verified INTEGER)')
        con.execute('CREATE TABLE accounts_operatorgrant(user_id INTEGER,account_id TEXT,action TEXT,expires_at TEXT)')
        con.execute('INSERT INTO auth_user VALUES (1,1)')
        con.execute("INSERT INTO accounts_identity VALUES (1,'operator',1)")
        for a in ('pipea', 'pipeb'):
            con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
            con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'cust-' + a))
            for kind in ('create', 'start', 'stop', 'backup', 'delete'):
                con.execute("INSERT INTO accounts_operatorgrant VALUES (1,?,?,datetime('now','+1 hour'))", (a, 'lifecycle_' + kind))
    run = ROOT / 'run'
    run.mkdir(mode=0o750)
    shutil.chown(run, 0, APP.pw_gid)
    sock = run / 'control.sock'
    supervisor = subprocess.Popen(
        [sys.executable, '-m', 'agentai_platform.lifecycle.supervisor_main', '--controller-user', 'agentai-platform',
         '--state-dir', str(ROOT / 'sup'), '--socket', str(sock), '--native-wiring', '/etc/agentai-supervisor/native-wiring.json'],
        env={**os.environ, 'PYTHONPATH': os.environ.get('AGENTAI_PLATFORM', '/opt/agentai-supervisor/current')},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.2)
    record('supervisor socket is up', sock.exists())
    driver, _ = build_native_backend('/etc/agentai-supervisor/native-wiring.json')

    def op_state(op):
        with store.connect() as con:
            return con.execute('SELECT state FROM operations WHERE id=?', (op['id'],)).fetchone()[0]

    def cell_state(a):
        with store.connect() as con:
            return con.execute('SELECT observed_state FROM lifecycle_cells WHERE account_id=?', (a,)).fetchone()[0]

    def gen(a):
        with store.connect() as con:
            return con.execute('SELECT generation FROM deployments WHERE account_id=?', (a,)).fetchone()[0]

    def queue(a, kind):
        g = None if kind == 'create' else gen(a)
        return engine.request(Principal(a, '1', 'operator'), kind=kind, key=f'{kind}-{a}-{int(time.time())}',
                              generation=g, target_profile='trial-measured-v1')

    try:
        ops = {a: queue(a, 'create') for a in ('pipea', 'pipeb')}
        report = worker_tick(state / 'db.sqlite3', sock)
        record('unenrolled accounts wait (nothing runs, nothing poisoned)',
               all(op_state(o) == 'pending' for o in ops.values()) and report.get('waiting') == 2, report)
        for a in ('pipea', 'pipeb'):
            done = subprocess.run([sys.executable, '-m', 'agentai_platform.lifecycle.enroll_cli', '--app-db', str(state / 'db.sqlite3'),
                                   '--account', a, '--image', IMAGE, '--state-dir', str(ROOT / 'sup'), '--backup-root', str(ROOT / 'bk')],
                                  capture_output=True, text=True,
                                  env={**os.environ, 'PYTHONPATH': os.environ.get('AGENTAI_PLATFORM', '/opt/agentai-supervisor/current')})
            record(f'host enrolls {a}', done.returncode == 0, done.stderr[-200:])
        report = worker_tick(state / 'db.sqlite3', sock)
        record('worker creates both cells via the socket', report.get('ran') == 2
               and cell_state('pipea') == cell_state('pipeb') == 'stopped', report)
        queue('pipea', 'start')
        queue('pipeb', 'start')
        report = worker_tick(state / 'db.sqlite3', sock)
        record('only one cell starts; the other waits', sorted([cell_state('pipea'), cell_state('pipeb')]) == ['running', 'stopped'], report)
        running = 'pipea' if cell_state('pipea') == 'running' else 'pipeb'
        waiting = 'pipeb' if running == 'pipea' else 'pipea'
        # Make the running cell look idle for two hours, then let the sleep policy drain it.
        with store.connect() as con:
            con.execute("UPDATE operations SET created_at='2026-01-01T00:00:00.000Z'")
        report = worker_tick(state / 'db.sqlite3', sock)
        record('idle cell gets a system drain request', report.get('drained') == 1, report)
        report = worker_tick(state / 'db.sqlite3', sock)
        record('drain stops the idle cell', cell_state(running) == 'stopped', report)
        with store.connect() as con:
            con.execute("UPDATE operations SET created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE state='pending'")
        report = worker_tick(state / 'db.sqlite3', sock)
        record('the waiting account then wakes and runs', cell_state(waiting) == 'running', report)
        for a in ('pipea', 'pipeb'):
            if cell_state(a) == 'running':
                queue(a, 'stop')
                worker_tick(state / 'db.sqlite3', sock)
            queue(a, 'delete')
        worker_tick(state / 'db.sqlite3', sock)
        record('both cells deleted through the pipeline', all(cell_state(a) == 'absent' for a in ('pipea', 'pipeb')),
               [cell_state('pipea'), cell_state('pipeb')])
    except Exception as exc:
        record('unexpected error', False, repr(exc))
    finally:
        supervisor.terminate()
        try:
            supervisor.wait(timeout=15)
        except subprocess.TimeoutExpired:
            supervisor.kill()
        # Remove any cell or volume this run left behind (exact tenants from the scratch database).
        try:
            with store.connect() as con:
                tenants = [r[0] for r in con.execute('SELECT tenant_ref FROM lifecycle_cells')]
            from agentai_platform.lifecycle.fleet_plan import FleetBinding
            for t in tenants:
                subprocess.run(['docker', 'rm', '-f', f'openclaw-cell-{t}'], capture_output=True,
                               env={**os.environ, 'DOCKER_HOST': 'unix:///run/agentai-cells/docker.sock'})
                driver._run([str(driver.custody.node), str(driver.custody.entry), 'fleet', 'rm', t])
                driver.volumes.release(t)
                driver.volumes.purge(t)
                shutil.rmtree(driver.volumes.auth_dir(t), ignore_errors=True)
                driver.secrets.destroy(t)
        except Exception:
            pass
        shutil.rmtree(ROOT, ignore_errors=True)
    evidence.write_text(json.dumps({'results': results, 'all_pass': all(r['pass'] for r in results)}, indent=2))
    sys.exit(0 if all(r['pass'] for r in results) else 1)


if __name__ == '__main__':
    main()
