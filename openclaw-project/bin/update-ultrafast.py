#!/usr/bin/env python3
"""Install (or roll back) the experimental "ultrafast" decider on the server, for the owner's own testing.

    python3 openclaw-project/bin/update-ultrafast.py              # run the tests, show the plan, change nothing
    python3 openclaw-project/bin/update-ultrafast.py --apply      # install, switch releases, restart, smoke-test
    python3 openclaw-project/bin/update-ultrafast.py --rollback   # previous releases back, engine off

It runs on the SAME sandboxed browser stage as the standard decider (platform/agentai_platform/browse/ultrafast_brain.py): same loop, same stops, same clean profile.
The Safety console switch "Use the standard Lumina browser" only chooses who decides each step. Nothing new is installed on the server except two new release folders:
  1. removes what the first, separate-Chrome design left behind (its Chrome, users, firewall table, units and folders); all of it was unused after the rollback
  2. new release folders for the supervisor tree and the app tree (copied from the current ones, changed files laid over, `current` switched; the old ones are kept)
  3. the owner account file and the OpenRouter key for the fast text writer (copied from .env without printing it)
  4. restarts agentai-browse and agentai-platform-app, then asks TypeSafe and the text writer one real question each through the new code
Turn it on: Safety console -> Browser -> "Use the standard Lumina browser" -> OFF, with a time limit. Read when a task starts: the next task uses it.
"""
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PLATFORM = PROJECT / 'platform'
CODE_FILES = ['agentai_platform/safety.py', 'agentai_platform/browse/ladder.py', 'agentai_platform/browse/loop.py', 'agentai_platform/browse/service.py',
              'agentai_platform/browse/service_main.py', 'agentai_platform/browse/ultrafast_brain.py']
TESTS = ['tests.test_browse_ultrafast', 'tests.test_safety_gates', 'tests.test_browse_service', 'tests.test_browse', 'tests.test_browse_modes']
KEY = '/var/lib/agentai-supervisor-secrets/_shared/openrouter-key'
STATE = '/etc/agentai-supervisor/ultrafast-rollback'


def run(argv, cwd=None):
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print((done.stdout + done.stderr)[-2500:])
        raise SystemExit(f'failed: {" ".join(map(str, argv))[:200]}')
    return done.stdout


def remote(script):
    """One bash script on the server (ssh-server never prints credentials). python-dotenv notes about the private env file's loose lines are dropped."""
    done = subprocess.run([sys.executable, str(HERE / 'ssh-server'), 'bash -s <<\'__UF__\'\nset -euo pipefail\n' + script + '\n__UF__'], capture_output=True, text=True)
    print('\n'.join(l for l in (done.stdout + done.stderr).splitlines() if 'python-dotenv' not in l))
    if done.returncode:
        raise SystemExit('the server step failed (output above); nothing after it was run')


def upload(local, remote_path):
    run([sys.executable, str(HERE / 'scp-server'), str(local), remote_path])


CLEANUP = r'''
echo "== 1 remove what the first design left behind (all unused)"
systemctl disable --now agentai-ufchrome.service agentai-ufchrome-firewall.service 2>/dev/null || true
nft delete table inet agentai_ufchrome 2>/dev/null || true
rm -f /etc/systemd/system/agentai-ufchrome.service /etc/systemd/system/agentai-ufchrome-firewall.service /usr/local/sbin/agentai-ufchrome-firewall /etc/systemd/system/agentai-browse.service.d/ultrafast.conf
if dpkg -s google-chrome-stable >/dev/null 2>&1; then DEBIAN_FRONTEND=noninteractive apt-get remove -y -qq google-chrome-stable >/dev/null; rm -f /etc/default/google-chrome; fi
rm -rf /opt/agentai-browse/ultrafast /var/lib/agentai-ufchrome
id agentai-ultrafast >/dev/null 2>&1 && userdel agentai-ultrafast || true
id agentai-ufchrome >/dev/null 2>&1 && userdel agentai-ufchrome || true
systemctl daemon-reload
'''

APPLY = r'''
NAME=@@NAME@@
OWNER=$(grep -E '^AGENTAI_SAFETY_OWNER_ACCOUNT=' /etc/agentai-platform/accounts.env | head -1 | cut -d= -f2- | tr -d "\"' ")
echo "$OWNER" | grep -qE '^[0-9a-f]{32}$' || { echo "owner account id not found in accounts.env"; exit 1; }
@@CLEANUP@@
echo "== 2 releases"
SUP_OLD=$(readlink -f /opt/agentai-supervisor/current); APP_OLD=$(readlink -f /opt/agentai-platform/current)
[ -f @@STATE@@ ] || printf 'SUP_OLD=%s\nAPP_OLD=%s\n' "$SUP_OLD" "$APP_OLD" > @@STATE@@
SUP_NEW=/opt/agentai-supervisor/releases/$NAME; APP_NEW=/opt/agentai-platform/releases/$NAME
rm -rf $SUP_NEW $APP_NEW
cp -a $SUP_OLD $SUP_NEW; cp -a $APP_OLD $APP_NEW
for T in $SUP_NEW $APP_NEW; do tar -xzf /root/uf-code.tgz -C $T --no-same-owner; chown -R root:root $T/agentai_platform; chmod -R go-w,a+rX $T/agentai_platform; done
python3 - "$APP_NEW" <<'PY'
import json, sys
p = sys.argv[1] + '/RELEASE.json'
meta = json.load(open(p)); add = json.load(open('/root/uf-release.json'))
meta.update(changes=add['changes'], commit=add['commit'], purpose=add['purpose'], release=add['release'], frontend_changes=True, schema_changes=False)
meta.setdefault('source_sha256', {}).update(add['source_sha256'])
json.dump(meta, open(p, 'w'), indent=2, sort_keys=True)
PY
echo "== 3 owner and key"
(umask 077; printf '%s' "$OWNER" > /etc/agentai-supervisor/ultrafast-owner)
install -d -m 700 /var/lib/agentai-supervisor-secrets/_shared
install -m 600 -o root -g root /root/uf-key @@KEY@@
shred -u /root/uf-key
echo "== 4 switch releases and restart"
ln -sfn $SUP_NEW /opt/agentai-supervisor/current.new && mv -Tf /opt/agentai-supervisor/current.new /opt/agentai-supervisor/current
ln -sfn $APP_NEW /opt/agentai-platform/current.new && mv -Tf /opt/agentai-platform/current.new /opt/agentai-platform/current
systemctl restart agentai-browse.service agentai-platform-app.service
sleep 4
systemctl is-active agentai-browse agentai-platform-app
rm -f /root/uf-code.tgz /root/uf-release.json
echo "released $NAME"
'''

SMOKE = r'''
cd /opt/agentai-supervisor/current
PYTHONPATH=. python3 - <<'PY'
# One real question to TypeSafe and one to the text writer, through the new code and the production keys.
import json, time
from pathlib import Path
from agentai_platform.browse import candidates as cand
from agentai_platform.browse.ladder import RUNNER_V2
from agentai_platform.browse.ultrafast_brain import UltrafastChooser
from agentai_platform.browse.service_main import JEV_ENDPOINT
from agentai_platform.routing.classifier import http_post
from agentai_platform.safety import FEATURES
assert 'standard_browser' in FEATURES, 'switch missing from the registry'
rd = lambda p: Path(p).read_text().strip()
brain = UltrafastChooser(JEV_ENDPOINT, rd('/var/lib/agentai-supervisor-secrets/_shared/typesafe-key'), http_post, rd('@@KEY@@'), http_post)
page = {'url': 'https://books.toscrape.com/', 'title': 'All products | Books to Scrape', 'text': 'Books to Scrape. Browse by category: Travel, Mystery, Poetry'}
t0 = time.time()
links = cand.build('[1] <a> "Travel"\n[2] <a> "Mystery"\n[3] <a> "Poetry"')
pick = brain.choose('Open the Travel category.', page['text'], links, page=page, caps=RUNNER_V2)
print('chooser:', pick.operation, pick.target, f'| answered by {brain.resolved} | {time.time()-t0:.1f}s')
assert pick.operation == 'click' and pick.target == 'c1', 'unexpected choice'
form = cand.build('[1] <input type=text> "Search"\n[2] <a> "Home"')
t0 = time.time()
text = brain.write_text('Search the store for a book about poetry.', page['text'], page, [], form[0])
print('text writer:', repr(text), f'| {time.time()-t0:.1f}s')
assert text and 'poet' in text.lower(), 'unexpected text'
PY
'''

ROLLBACK = r'''
[ -f @@STATE@@ ] || { echo "nothing to roll back"; exit 0; }
. @@STATE@@
rm -f /etc/agentai-supervisor/ultrafast-owner @@KEY@@
ln -sfn "$SUP_OLD" /opt/agentai-supervisor/current.new && mv -Tf /opt/agentai-supervisor/current.new /opt/agentai-supervisor/current
ln -sfn "$APP_OLD" /opt/agentai-platform/current.new && mv -Tf /opt/agentai-platform/current.new /opt/agentai-platform/current
rm -f @@STATE@@
systemctl restart agentai-browse.service agentai-platform-app.service
sleep 3
systemctl is-active agentai-browse agentai-platform-app
echo "rolled back: supervisor -> $SUP_OLD, app -> $APP_OLD"
'''


def main():
    if '--rollback' in sys.argv:
        remote(ROLLBACK.replace('@@STATE@@', STATE).replace('@@KEY@@', KEY))
        return
    apply = '--apply' in sys.argv
    print('Running the tests first...')
    run([sys.executable, '-m', 'unittest', *TESTS], cwd=PLATFORM)
    print('Tests passed.')
    head = run(['git', 'rev-parse', 'HEAD'], cwd=PROJECT).strip()
    name = f'{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-ultrafast-{head[:7]}'
    if not apply:
        print(__doc__)
        print(f'Release name would be {name}. Nothing was changed on the server. Run again with --apply.')
        return
    key = (dotenv_values(PROJECT / '.env').get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        raise SystemExit('OPENROUTER_API_KEY is not set in openclaw-project/.env')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with tarfile.open(tmp / 'uf-code.tgz', 'w:gz') as tar:
            for rel in CODE_FILES:
                tar.add(PLATFORM / rel, arcname=rel)
        (tmp / 'uf-release.json').write_text(json.dumps({'changes': CODE_FILES, 'commit': head, 'purpose': 'Owner-only experimental ultrafast decider on the standard browser, behind a timed safety switch',
                                                         'release': name, 'source_sha256': {r: hashlib.sha256((PLATFORM / r).read_bytes()).hexdigest() for r in CODE_FILES}}))
        (tmp / 'uf-key').write_text(key)
        (tmp / 'uf-key').chmod(0o600)
        for f in ('uf-code.tgz', 'uf-release.json', 'uf-key'):
            upload(tmp / f, f'/root/{f}')
    remote(APPLY.replace('@@NAME@@', name).replace('@@CLEANUP@@', CLEANUP).replace('@@STATE@@', STATE).replace('@@KEY@@', KEY))
    print('Smoke test: one real question to each model through the new code...')
    remote(SMOKE.replace('@@KEY@@', KEY))
    print(f'\nInstalled and verified ({name}).\nNext: python3 openclaw-project/bin/deploy-lumina.py --apply   (the Safety console wording)')


if __name__ == '__main__':
    main()
