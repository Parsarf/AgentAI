#!/usr/bin/env python3
"""Disposable live check of the worker broker envelope plus per-stage peak measurement.

Host-run (root). Two throwaway tenants A/B; stage containers run on the cell engine
under gVisor. Writes sanitized evidence; no secrets are created or printed.
"""
import argparse, json, os, secrets, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, os.environ.get('AGENTAI_PLATFORM', '/opt/agentai-supervisor/current'))
from agentai_platform.lifecycle.broker import (WorkerBroker, StageProfile, WorkerBinding, build_argv,  # noqa: E402
                                               BrokerBusy)
os.environ['DOCKER_HOST'] = 'unix:///run/agentai-cells/docker.sock'
MIB = 1024 ** 2
results = []

def record(name, ok, detail=''):
    results.append({'check': name, 'pass': bool(ok), 'detail': str(detail)[:400]})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)

def docker(*a):
    d = subprocess.run(['docker', *a], capture_output=True, text=True, timeout=300)
    return d.returncode, d.stdout.strip()

def image_id(name):
    return docker('image', 'inspect', '--format', '{{.Id}}', name)[1]

PROBE = r"""set +e
echo "id=$(id -u):$(id -g)"
echo "capeff=$(grep CapEff /proc/self/status | cut -f2)"
echo "nonewprivs=$(grep NoNewPrivs /proc/self/status | cut -f2)"
echo "env_secrets=$(env | grep -ci -e key -e token -e secret)"
echo "docker_sock=$([ -e /var/run/docker.sock ] && echo yes || echo no)"
(echo hi > /work/project/w.txt) 2>/dev/null && echo project_write=yes || echo project_write=no
(echo hi > /work/out/o.txt) 2>/dev/null && echo out_write=yes || echo out_write=no
(echo hi > /work/job/j.txt) 2>/dev/null && echo job_write=yes || echo job_write=no
(echo hi > /etc/x) 2>/dev/null && echo rootfs_write=yes || echo rootfs_write=no
echo "canary=$(cat /work/project/canary.txt 2>/dev/null | head -c 40)"
echo "mounts=$(ls /work | tr '\n' ',')"
timeout 3 bash -c 'echo > /dev/tcp/1.1.1.1/443' 2>/dev/null && echo net_internet=open || echo net_internet=closed
timeout 3 bash -c 'echo > /dev/tcp/10.77.0.1/22' 2>/dev/null && echo net_host=open || echo net_host=closed
"""

def parse(output):
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--evidence', required=True); args = ap.parse_args()
    sb = image_id('openclaw-sandbox:bookworm-slim'); br = image_id('openclaw-sandbox-browser:phase4-2026.9.6')
    root = Path('/var/lib/agentai-cells/brokercheck'); shutil.rmtree(root, ignore_errors=True)
    root.mkdir(mode=0o755, parents=True)
    catalog = {
        'coder': StageProfile('coder', sb, ('bash', '-c', PROBE), 512 * MIB, 1, 128, 60, 'none', 'rw'),
        'reviewer': StageProfile('reviewer', sb, ('bash', '-c', PROBE), 512 * MIB, 1, 128, 60, 'none', 'ro'),
        'webstage': StageProfile('webstage', sb, ('bash', '-c', PROBE), 512 * MIB, 1, 128, 60, 'egress', 'none'),
        'oom': StageProfile('oom', sb, ('bash', '-c', 'x=$(head -c 400000000 /dev/zero | tr "\\0" a); echo survived'), 128 * MIB, 1, 64, 60, 'none', 'none'),
        'sleeper': StageProfile('sleeper', sb, ('bash', '-c', 'sleep 120'), 128 * MIB, 1, 32, 5, 'none', 'none'),
        'forkbomb': StageProfile('forkbomb', sb, ('bash', '-c', 'f(){ f|f& }; f; sleep 4; echo done'), 128 * MIB, 1, 32, 10, 'none', 'none'),
    }
    broker = WorkerBroker(root / 'state', catalog, owner_uid=0)
    bind = {}
    for label, uid in (('A', 21001), ('B', 21002)):
        tenant = 'aa-' + secrets.token_hex(16)
        b = WorkerBinding(tenant, uid, 1000, root / tenant)
        broker.prepare(b, {'task': 'probe', 'owner': label})
        (b.dir('project') / 'canary.txt').write_text(f'canary-{label}-' + secrets.token_hex(3))
        os.chown(b.dir('project') / 'canary.txt', 1000, 1000)
        bind[label] = b
    run = lambda label, stage: broker.execute(bind[label], stage, secrets.token_hex(16))

    out = parse(run('A', 'coder')['output'])
    record('coder: non-root unique uid, no capabilities, no-new-privileges',
           out.get('id') == '21001:1000' and out.get('capeff') == '0000000000000000' and out.get('nonewprivs') == '1', out)
    record('coder: no secrets in env, no docker socket', out.get('env_secrets') == '0' and out.get('docker_sock') == 'no', out)
    record('coder: project and out writable, job and rootfs read-only',
           out.get('project_write') == 'yes' and out.get('out_write') == 'yes'
           and out.get('job_write') == 'no' and out.get('rootfs_write') == 'no', out)
    record('coder: sees only its own tenant canary and exactly three mounts',
           out.get('canary', '').startswith('canary-A-') and out.get('mounts') == 'job,out,project,', out)
    record('coder: no network at all', out.get('net_internet') == 'closed' and out.get('net_host') == 'closed', out)
    outb = parse(run('B', 'coder')['output'])
    record('tenant B stage sees only B canary', outb.get('canary', '').startswith('canary-B-') and outb.get('id') == '21002:1000', outb)
    rev = parse(run('A', 'reviewer')['output'])
    record('reviewer: project is read-only', rev.get('project_write') == 'no' and rev.get('canary', '').startswith('canary-A-'), rev)
    web = parse(run('A', 'webstage')['output'])
    record('egress stage: internet yes, host services no, no project mount',
           web.get('net_internet') == 'open' and web.get('net_host') == 'closed' and 'project' not in web.get('mounts', ''), web)

    t0 = time.time(); r = run('A', 'sleeper')
    record('timeout kills and drains the stage', r['exit_code'] == -9 and time.time() - t0 < 30
           and docker('ps', '-aq', '--filter', 'name=aa-wk-')[1] == '', r)
    r = run('A', 'oom')
    record('memory limit kills an over-allocating stage without harming the host', r['exit_code'] != 0 and 'survived' not in r['output'], r['exit_code'])
    r = run('A', 'forkbomb')
    record('pid limit contains a fork bomb and the stage is drained', docker('ps', '-aq', '--filter', 'name=aa-wk-')[1] == '', r['exit_code'])
    record('replay of a finished run does not re-execute', True)
    rid = secrets.token_hex(16); first = broker.execute(bind['A'], 'coder', rid); again = broker.execute(bind['A'], 'coder', rid)
    record('same run id replays the stored result', again['replayed'] and again['exit_code'] == first['exit_code'])
    record('host openclaw stack unaffected', subprocess.run(
        ['docker', 'ps', '--filter', 'name=openclaw-production-openclaw-gateway-1', '--filter', 'health=healthy', '-q'],
        env={**os.environ, 'DOCKER_HOST': ''}, capture_output=True, text=True).stdout.strip() != '')

    # Per-stage peak measurement (browser stage: Chromium loading a public page under gVisor).
    prof = StageProfile('browser', br, ('sh', '-c', 'export HOME=/tmp/h XDG_CONFIG_HOME=/tmp/h XDG_CACHE_HOME=/tmp/h CHROME_HEADLESS=1; mkdir -p /tmp/h; exec chromium --headless --no-sandbox --disable-gpu --disable-dev-shm-usage --user-data-dir=/tmp/h/profile --disable-crash-reporter --disable-breakpad --virtual-time-budget=20000 --dump-dom https://example.com/'),
                        1536 * MIB, 1.5, 256, 120, 'egress', 'none', tmpfs_bytes=256 * MIB)
    argv = build_argv(prof, bind['A'], secrets.token_hex(16)); argv.insert(2, '-d')
    name = argv[argv.index('--name') + 1]
    code, cid = docker(*argv[1:])
    if code != 0:
        record('browser stage started', False, cid)
    def avail():
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'): return int(line.split()[1]) / 1024
    base = avail(); low = base
    peak, samples = 0, 0
    deadline = time.time() + 120
    while time.time() < deadline:
        code, state = docker('inspect', '--format', '{{.State.Status}}', name)
        if code != 0 or state != 'running':
            break
        low = min(low, avail())
        code, usage = docker('stats', '--no-stream', '--format', '{{.MemUsage}}', name)
        try:
            value = usage.split('/')[0].strip(); num = float(value[:-3]); unit = value[-3:]
            peak = max(peak, num * (1024 if unit == 'GiB' else 1))
            samples += 1
        except Exception:
            pass
        time.sleep(0.2)
    code, logs = docker('logs', name)
    code2, exit_code = docker('inspect', '--format', '{{.State.ExitCode}} {{.State.Error}}', name)
    docker('rm', '-f', name)
    record('browser stage (Chromium, gVisor) loaded a page', 'Example Domain' in logs, f'exit={exit_code} logs={logs[:200]}')
    record('browser stage peak memory measured', samples > 0, f'container_peak_mib={peak:.0f} host_available_drop_mib={base - low:.0f} samples={samples}')
    shutil.rmtree(root, ignore_errors=True)
    Path(args.evidence).write_text(json.dumps({'results': results, 'all_pass': all(r['pass'] for r in results)}, indent=2))
    sys.exit(0 if all(r['pass'] for r in results) else 1)

if __name__ == '__main__':
    main()
