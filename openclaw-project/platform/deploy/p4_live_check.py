#!/usr/bin/env python3
"""Disposable live lifecycle check for Phase 4 (host-run, root, writes sanitized evidence).

Drives the real HostSupervisor + FleetCliDriver against two throwaway tenants on
the cell engine: create/start/stop/backup/quarantined-restore/upgrade/delete/purge,
the global one-running-cell rule, hard volume cap and quarantine egress denial.
Uses a scratch supervisor database, never the production custody. Tokens, keys
and archive contents are never printed or written. Exit 0 only if every check
passed.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

sys.path.insert(0, os.environ.get('AGENTAI_PLATFORM', '/opt/agentai-supervisor/current'))
from agentai_platform.lifecycle.fleet_plan import FleetBinding            # noqa: E402
from agentai_platform.lifecycle.native_wiring import build_native_backend, http_health  # noqa: E402
from agentai_platform.lifecycle.supervisor import HostSupervisor, SupervisorBusy       # noqa: E402
from agentai_platform.lifecycle.types import Claim                         # noqa: E402
from agentai_platform.lifecycle.fleet_driver import HeadroomAdmission, linux_mem_available  # noqa: E402
from agentai_platform.lifecycle.maintenance import quarantine_ref          # noqa: E402

IMAGE = 'ghcr.io/openclaw/openclaw@sha256:62832668e3e5e139f745f7d3df892c9251eb53318b7d14a76c410dde1f25d730'
MIB = 1024 ** 2
results = []


def record(name, ok, detail=''):
    results.append({'check': name, 'pass': bool(ok), 'detail': str(detail)[:300]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)
    return ok


def docker(*args, check=False):
    done = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=120,
                          env={**os.environ, 'DOCKER_HOST': 'unix:///run/agentai-cells/docker.sock'})
    if check and done.returncode:
        raise RuntimeError('docker failed')
    return done.returncode, done.stdout


def exec_in(tenant, script):
    return docker('exec', f'openclaw-cell-{tenant}', 'sh', '-c', script)


def node_probe(tenant, targets):
    probe = Path('/root/nettest.js').read_text()
    code, out = docker('exec', '-e', 'TARGETS=' + json.dumps(targets), f'openclaw-cell-{tenant}', 'node', '-e', probe)
    return json.loads(out) if code == 0 and out.strip().startswith('{') else {}


def mem_available_mib():
    return linux_mem_available() // MIB


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wiring', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    driver, admission = build_native_backend(args.wiring)
    scratch = Path('/var/lib/agentai-supervisor-p4check')
    scratch.mkdir(mode=0o700, exist_ok=True)
    state = scratch / ('run-' + secrets.token_hex(4))
    supervisor = HostSupervisor(state, driver, owner_uid=0, admission=admission)

    tenants = {}
    for label, port in (('A', 19111), ('B', 19112)):
        ref = 'aa-' + secrets.token_hex(16)
        tenants[label] = FleetBinding(
            account_id='acct' + label, deployment_id=secrets.token_hex(16), tenant_ref=ref,
            profile_revision='trial-v1', image=IMAGE, port=port, memory_bytes=1024 * MIB,
            cpu_millis=1000, pid_limit=256, archive_limit_bytes=512 * MIB,
            backup_root=Path('/var/lib/agentai-cells/backups') / ('acct' + label),
            upgrade_image=IMAGE, quarantine_port=port + 50, volume_bytes=300 * MIB)
        tenants[label].backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        supervisor.enroll(tenants[label])
    gen = {'A': 1, 'B': 1}
    ops = {}

    def claim(label, kind, backup_ref=None):
        b = tenants[label]
        op = secrets.token_hex(16)
        ops[(label, kind)] = op
        return Claim(b.account_id, b.deployment_id, b.tenant_ref, op, kind, gen[label],
                     b.profile_revision, backup_ref, 1, 'p4-live-check')

    def run(label, kind, backup_ref=None):
        receipt = supervisor.execute(claim(label, kind, backup_ref))
        if receipt.applied and kind in ('restore', 'upgrade'):
            gen[label] += 1
        return receipt

    A, B = tenants['A'].tenant_ref, tenants['B'].tenant_ref
    try:
        baseline = mem_available_mib()
        r = run('A', 'create')
        record('A create', r.applied and r.state == 'stopped')
        # The global rule also blocks creating while another cell runs, so create B first.
        record('B create', run('B', 'create').applied)
        mounted = driver.volumes.is_mounted(A)
        record('A state volume is a capped loop mount', mounted)
        r = run('A', 'start')
        record('A start', r.applied and r.state == 'running')
        record('A gateway healthy over loopback', http_health(tenants['A'].port, timeout=120))
        code, out = docker('inspect', f'openclaw-cell-{A}', '--format',
                           '{{.HostConfig.Runtime}} {{.HostConfig.Memory}} {{.HostConfig.PidsLimit}} {{.HostConfig.Privileged}} {{.HostConfig.CapDrop}}')
        record('A runs under gVisor with limits and dropped capabilities',
               out.split()[:4] == ['runsc', str(1024 * MIB), '256', 'false'] and 'ALL' in out, out.strip())
        time.sleep(20)
        code, stats = docker('stats', '--no-stream', '--format', '{{.MemUsage}}', f'openclaw-cell-{A}')
        host_delta = baseline - mem_available_mib()
        record('measured idle cell memory recorded', True, f'container={stats.strip()} host_delta_mib={host_delta}')
        exec_in(A, 'echo canary-A-' + secrets.token_hex(3) + ' > /home/node/.openclaw/canary.txt')
        code, _ = exec_in(A, 'test -s /home/node/.openclaw/canary.txt')
        record('A canary written inside its own volume', code == 0)

        # Hard disk cap: fill beyond 300 MiB; the write must stop at the cap.
        code, out = exec_in(A, 'dd if=/dev/zero of=/home/node/.openclaw/fill.bin bs=1M count=400 2>&1 | tail -1; ls -l /home/node/.openclaw/fill.bin | awk "{print \\$5}"')
        size = int(out.strip().splitlines()[-1] or 0)
        record('disk cap stops a 400 MiB write below the 300 MiB volume', 0 < size < 300 * MIB, size)
        exec_in(A, 'rm -f /home/node/.openclaw/fill.bin')
        record('A still healthy after hitting its disk cap', http_health(tenants['A'].port, timeout=30))

        # Egress policy from inside the cell.
        probe = node_probe(A, [['host_ssh', '10.77.0.1', 22], ['host_public_ssh', '179.236.71.203', 22],
                               ['metadata', '169.254.169.254', 80], ['owner_net_litellm', '172.18.0.4', 4000],
                               ['internet', '1.1.1.1', 443]])
        record('cell cannot reach host services, metadata or the owner network; internet works',
               probe.get('internet') == 'OPEN' and all(probe.get(k) not in (None, 'OPEN')
                   for k in ('host_ssh', 'host_public_ssh', 'metadata', 'owner_net_litellm')), probe)

        # Global one-running-cell rule and sequential trial behavior.
        try:
            run('B', 'start')
            record('second cell refused while A runs', False, 'start was admitted')
        except SupervisorBusy as exc:
            record('second cell refused while A runs (global active cell)', 'global' in str(exc), exc)

        r = run('A', 'stop')
        record('A stop is quiesced', r.applied and r.state == 'stopped' and r.quiesced)
        r = run('A', 'backup')
        backup_ref = ops[('A', 'backup')]
        record('A backup verified as bounded gzip archive', r.applied and r.backup_ref == backup_ref)

        # Quarantined restore: separate slug/volume/network, egress dropped before any code runs.
        r = run('A', 'restore', backup_ref)
        q = quarantine_ref(A)
        record('A restore lands in a quarantined cell', r.applied and r.state == 'stopped')
        record('quarantine subnet is in the egress-drop set', driver.isolation.is_quarantined(q))
        record('production A untouched by the restore', driver._observed_state(tenants['A']) == 'stopped')
        code, out = docker('run', '--rm', '--entrypoint', 'cat', '-v',
                           f'/var/lib/agentai-fleet/.openclaw/fleet/cells/{q}:/d:ro', IMAGE, '/d/canary.txt')
        record('restored data carries the original canary', out.startswith('canary-A-'))

        # Quarantined cell must not reach the internet while running.
        code, _ = docker('start', f'openclaw-cell-{q}')
        time.sleep(15)
        probe = node_probe(q, [['internet', '1.1.1.1', 443]])
        record('quarantined cell has no egress', probe.get('internet') not in (None, 'OPEN'), probe)
        docker('stop', f'openclaw-cell-{q}')
        driver.discard_quarantine(tenants['A'])
        record('discard removes only the quarantine',
               driver._observed_state(tenants['A']) == 'stopped' and not driver.volumes.image(q).exists()
               and not (driver.secrets.root / q).exists())

        # Pinned upgrade (same pinned image: exercises replace + canary health path).
        r = run('A', 'backup')
        r = run('A', 'upgrade')
        record('A upgrade with canary health', r.applied and r.state == 'running')
        run('A', 'stop')

        # B runs after A stops, in its own volume; A's canary is invisible to B.
        r = run('B', 'start')
        record('B start after A stopped', r.applied and r.state == 'running')
        record('B gateway healthy', http_health(tenants['B'].port, timeout=120))
        code, out = exec_in(B, 'find / -name canary.txt -not -path "/proc/*" 2>/dev/null | head -3')
        record('B cannot see A canary or volume', out.strip() == '' and not exec_in(B, 'ls /var/lib/agentai-fleet')[0] == 0, out.strip())
        run('B', 'stop')

        # Delete keeps data until the retention purge; purge removes exactly that tenant.
        for label in ('A', 'B'):
            run(label, 'delete')
        record('delete keeps data for retention', driver.volumes.image(A).exists() and driver.volumes.image(B).exists())
        for label in ('A', 'B'):
            driver.purge(tenants[label])
        record('purge removes volumes and secrets', not driver.volumes.image(A).exists()
               and not driver.volumes.image(B).exists() and not (driver.secrets.root / A).exists())
    except Exception as exc:  # report, then fall through to cleanup
        record('unexpected error', False, repr(exc))
    finally:
        for label in ('A', 'B'):
            try:
                b = tenants[label]
                if driver._observed_state(b) is not None:
                    docker('stop', f'openclaw-cell-{b.tenant_ref}')
                    driver._run([str(driver.custody.node), str(driver.custody.entry), 'fleet', 'rm', b.tenant_ref])
                driver.discard_quarantine(b)
                driver.purge(b)
            except Exception:
                pass
    Path(args.evidence).write_text(json.dumps({'results': results, 'all_pass': all(r['pass'] for r in results)}, indent=2))
    sys.exit(0 if all(r['pass'] for r in results) else 1)


if __name__ == '__main__':
    main()
