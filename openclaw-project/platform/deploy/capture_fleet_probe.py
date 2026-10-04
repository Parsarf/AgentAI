#!/usr/bin/env python3
"""Host operator: capture read-only native CLI probe outputs for schema authoring.

Runs only version, help and `fleet list --json` forms against the separately
installed candidate CLI. Never creates, starts, stops or deletes a cell, and
never touches the owner runtime. Effect-output schemas cannot be captured
read-only; authoring them still requires an explicitly authorized disposable
activation and operator review. Output files are bounded and digest-recorded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

BOUNDS = {'version': 4096, 'help': 65536, 'list': 262144}
HELPS = ('create', 'start', 'stop', 'backup', 'restore', 'rm', 'list', '--help')


def bounded_run(argv, env, cwd, limit, timeout):
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        proc = subprocess.run(argv, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return {'argv': argv[2:], 'started_at': started, 'timed_out': True}
    record = {'argv': argv[2:], 'started_at': started, 'exit': code,
              'stdout_sha256': hashlib.sha256(out).hexdigest(), 'stdout_bytes': len(out),
              'stderr_bytes': len(err), 'truncated': len(out) > limit}
    return record, out[:limit], err[:4096]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True, help='pinned candidate node binary path')
    parser.add_argument('--entry', required=True, help='resolved candidate CLI entry path')
    parser.add_argument('--env', required=True, help='JSON file with the exact probe environment')
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--out', required=True, help='empty output directory for captures')
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    if os.geteuid() != 0 or platform.system() != 'Linux':
        raise SystemExit('requires an authorized Linux host operator')
    node, entry, cwd = Path(args.node), Path(args.entry), Path(args.cwd)
    for path in (node, entry):
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f'unsafe candidate path: {path}')
    env = json.loads(Path(args.env).read_text())
    if not isinstance(env, dict) or 'PATH' not in env:
        raise SystemExit('probe environment must be a JSON object including PATH')
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('output directory must be empty')
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = {'captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'node_sha256': hashlib.sha256(node.read_bytes()).hexdigest(),
                'entry_sha256': hashlib.sha256(entry.read_bytes()).hexdigest(),
                'read_only_only': True, 'effect_schemas_captured': False, 'probes': []}
    probes = [(['--version'], 'version', BOUNDS['version'])]
    probes += [(['fleet', name, '--help'], f'help-{name.lstrip("-")}'.replace(' ', '_'),
                BOUNDS['help']) for name in HELPS]
    probes += [(['fleet', 'list', '--json'], 'list', BOUNDS['list'])]
    for suffix, name, limit in probes:
        record, stdout, stderr = bounded_run([str(node), str(entry), *suffix], env, cwd,
                                             limit, args.timeout)
        stem = name.replace('--', '')
        (out / f'{stem}.stdout.bin').write_bytes(stdout)
        (out / f'{stem}.stderr.txt').write_bytes(stderr)
        if 'timed_out' in record:
            manifest['probes'].append(record)
            continue
        (out / f'{stem}.record.json').write_text(json.dumps(record, indent=2) + '\n')
        manifest['probes'].append(record)
        print(f'{name}: exit={record["exit"]} bytes={record["stdout_bytes"]}', file=sys.stderr)
    (out / 'probe-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('capture complete; effect-output schemas still require authorized activation')


if __name__ == '__main__':
    main()
