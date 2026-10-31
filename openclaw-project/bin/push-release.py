#!/usr/bin/env python3
"""Ship a few changed backend files to the server as a new release, restart the services that use them, and undo it in one command.

    python3 openclaw-project/bin/push-release.py --files agentai_platform/lifecycle/sleep.py --restart agentai-lifecycle-worker --why "Idle sleep 45 min"
    python3 openclaw-project/bin/push-release.py --rollback

Files are paths under openclaw-project/platform/. By default the supervisor tree (/opt/agentai-supervisor: browse service, workers) is released; add
`--trees supervisor,app` when the web app (/opt/agentai-platform) uses the file too. Without --apply it only shows the plan (nothing is changed).
A release is a timestamped folder copied from the current one with the files laid over; `current` is switched atomically and the old folder is kept.
`--rollback` points `current` back at the previous folders and restarts the same services. Tests named with --tests run first (default: none).
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PLATFORM = PROJECT / 'platform'
STATE = '/etc/agentai-supervisor/push-release-last'
TREES = {'supervisor': ('/opt/agentai-supervisor', 'SUP'), 'app': ('/opt/agentai-platform', 'APP')}


def run(argv, cwd=None):
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print((done.stdout + done.stderr)[-2500:])
        raise SystemExit(f'failed: {" ".join(map(str, argv))[:200]}')
    return done.stdout


def remote(script):
    done = subprocess.run([sys.executable, str(HERE / 'ssh-server'), 'bash -s <<\'__PR__\'\nset -euo pipefail\n' + script + '\n__PR__'], capture_output=True, text=True)
    print('\n'.join(l for l in (done.stdout + done.stderr).splitlines() if 'python-dotenv' not in l))
    if done.returncode:
        raise SystemExit('the server step failed (output above)')


APPLY = r'''
NAME=@@NAME@@
@@TREES@@
@@RECORD@@
systemctl restart @@UNITS@@
sleep 3
systemctl is-active @@UNITS@@
rm -f /root/pr-code.tgz /root/pr-release.json
echo "released $NAME"
'''

TREE = r'''
OLD=$(readlink -f @@BASE@@/current); echo "@@TAG@@_OLD=$OLD" >> @@STATE@@.new
NEW=@@BASE@@/releases/$NAME
rm -rf $NEW; cp -a $OLD $NEW
tar -xzf /root/pr-code.tgz -C $NEW --no-same-owner
chown -R root:root $NEW/agentai_platform; chmod -R go-w,a+rX $NEW/agentai_platform
@@META@@
ln -sfn $NEW @@BASE@@/current.new && mv -Tf @@BASE@@/current.new @@BASE@@/current
'''

META = r'''python3 - "$NEW" <<'PY'
import json, sys
p = sys.argv[1] + '/RELEASE.json'
meta = json.load(open(p)); add = json.load(open('/root/pr-release.json'))
meta.update(changes=add['changes'], commit=add['commit'], purpose=add['purpose'], release=add['release'])
meta.setdefault('source_sha256', {}).update(add['source_sha256'])
json.dump(meta, open(p, 'w'), indent=2, sort_keys=True)
PY'''

ROLLBACK = r'''
[ -f @@STATE@@ ] || { echo "nothing to roll back"; exit 0; }
. @@STATE@@
[ -n "${SUP_OLD:-}" ] && { ln -sfn "$SUP_OLD" /opt/agentai-supervisor/current.new && mv -Tf /opt/agentai-supervisor/current.new /opt/agentai-supervisor/current; }
[ -n "${APP_OLD:-}" ] && { ln -sfn "$APP_OLD" /opt/agentai-platform/current.new && mv -Tf /opt/agentai-platform/current.new /opt/agentai-platform/current; }
systemctl restart $UNITS
sleep 3
systemctl is-active $UNITS
rm -f @@STATE@@
echo "rolled back (supervisor: ${SUP_OLD:-unchanged}, app: ${APP_OLD:-unchanged})"
'''


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--files', nargs='*', default=[])
    p.add_argument('--restart', nargs='*', default=[])
    p.add_argument('--trees', default='supervisor')
    p.add_argument('--tests', nargs='*', default=[])
    p.add_argument('--why', default='')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--rollback', action='store_true')
    a = p.parse_args()
    if a.rollback:
        remote(ROLLBACK.replace('@@STATE@@', STATE))
        return
    if not a.files or not a.restart or not a.why:
        raise SystemExit('give --files, --restart and --why (or --rollback)')
    trees = [t for t in a.trees.split(',') if t]
    if any(t not in TREES for t in trees):
        raise SystemExit(f'--trees must be from {sorted(TREES)}')
    for rel in a.files:
        if not (PLATFORM / rel).is_file() or '..' in rel:
            raise SystemExit(f'not a file under openclaw-project/platform: {rel}')
    if a.tests:
        run([sys.executable, '-m', 'unittest', *a.tests], cwd=PLATFORM)
        print('Tests passed.')
    dirty = run(['git', 'status', '--porcelain', '--', *[f'platform/{r}' for r in a.files]], cwd=PROJECT).strip()
    head = run(['git', 'rev-parse', 'HEAD'], cwd=PROJECT).strip()
    name = f'{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-{head[:7]}'
    print(f'Release {name}: {len(a.files)} file(s) -> {", ".join(trees)}; restart {", ".join(a.restart)}')
    if dirty:
        print('Note: these files have uncommitted changes (commit first so the release can be traced):\n' + dirty)
    if not a.apply:
        print('Nothing was changed. Add --apply to ship it.')
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with tarfile.open(tmp / 'pr-code.tgz', 'w:gz') as tar:
            for rel in a.files:
                tar.add(PLATFORM / rel, arcname=rel)
        (tmp / 'pr-release.json').write_text(json.dumps({'changes': a.files, 'commit': head, 'purpose': a.why, 'release': name,
                                                         'source_sha256': {r: hashlib.sha256((PLATFORM / r).read_bytes()).hexdigest() for r in a.files}}))
        for f in ('pr-code.tgz', 'pr-release.json'):
            run([sys.executable, str(HERE / 'scp-server'), str(tmp / f), f'/root/{f}'])
    blocks = ''.join(TREE.replace('@@BASE@@', TREES[t][0]).replace('@@TAG@@', TREES[t][1]).replace('@@META@@', META if t == 'app' else ':').replace('@@STATE@@', STATE) for t in trees)
    units = ' '.join(a.restart)
    record = f"echo 'UNITS=\"{units}\"' >> {STATE}.new; mv -f {STATE}.new {STATE}"        # the previous releases and the services to restart on rollback, written once the trees are switched
    script = APPLY.replace('@@NAME@@', name).replace('@@TREES@@', f': > {STATE}.new\n' + blocks).replace('@@RECORD@@', record).replace('@@UNITS@@', units).replace('@@STATE@@', STATE)
    remote(script)
    print(f'Shipped {name}. Undo: python3 openclaw-project/bin/push-release.py --rollback')


if __name__ == '__main__':
    main()
