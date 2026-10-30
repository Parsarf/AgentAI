#!/usr/bin/env python3
"""Install (or roll back) the experimental jev-ultrafast browser engine on the server, for the owner's own testing.

    python3 openclaw-project/bin/update-ultrafast.py              # run the tests, show the plan, change nothing
    python3 openclaw-project/bin/update-ultrafast.py --apply      # install, switch releases, restart, smoke-test
    python3 openclaw-project/bin/update-ultrafast.py --rollback   # engine off, previous releases back, units stopped

What `--apply` does (all idempotent; the previous release of each tree is kept):
  1. users `agentai-ultrafast` (runs the agent) and `agentai-ufchrome` (runs Chrome), no login, no shell
  2. a python environment from the vendored, hash-pinned `browse-ultrafast/` (no download of unpinned code)
  3. Google Chrome (official .deb; Google's apt source is NOT added), one headless instance on 127.0.0.1:9222 as `agentai-ufchrome`,
     systemd-sandboxed and memory-capped, with its own nftables table that drops its traffic to private and loopback addresses
  4. a drop-in for agentai-browse.service (allow switching to the agent's user; a little more memory)
  5. new release folders for the supervisor tree and the app tree (copied from the current ones, changed files laid over, `current` switched)
  6. the owner account file, the OpenRouter key (copied from .env without printing it) and the Chrome address
  7. restarts agentai-browse and agentai-platform-app, then runs one real task through the production code path
Nothing else changes. The engine stays unreachable until the owner turns the safety switch "Use the standard Lumina browser" OFF for their own
account (Safety console, with a time limit). Rollback: --rollback (or flip the two `current` symlinks back and delete /etc/agentai-supervisor/ultrafast-owner).
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
U = '/opt/agentai-browse/ultrafast'
CODE_FILES = ['agentai_platform/safety.py', 'agentai_platform/browse/service.py', 'agentai_platform/browse/service_main.py',
              'agentai_platform/browse/ultrafast.py', 'agentai_platform/browse/ultrafast_driver.py']
TESTS = ['tests.test_browse_ultrafast', 'tests.test_safety_gates', 'tests.test_browse_service', 'tests.test_browse']


def run(argv, cwd=None, quiet=False):
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print((done.stdout + done.stderr)[-2500:])
        raise SystemExit(f'failed: {" ".join(map(str, argv))[:200]}')
    if not quiet and done.stdout.strip():
        print(done.stdout.rstrip())
    return done.stdout


def remote(script):
    """One bash script on the server (ssh-server never prints credentials). python-dotenv notes about the private env file's loose lines are dropped."""
    done = subprocess.run([sys.executable, str(HERE / 'ssh-server'), 'bash -s <<\'__UF__\'\nset -euo pipefail\n' + script + '\n__UF__'], capture_output=True, text=True)
    out = '\n'.join(l for l in (done.stdout + done.stderr).splitlines() if 'python-dotenv' not in l)
    print(out)
    if done.returncode:
        raise SystemExit('the server step failed (output above); nothing after it was run')
    return out


def upload(local, remote_path):
    run([sys.executable, str(HERE / 'scp-server'), str(local), remote_path], quiet=True)


def git_head():
    return run(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, quiet=True).strip()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


UNITS = r'''
cat > /etc/systemd/system/agentai-ufchrome-firewall.service <<'UNIT'
[Unit]
Description=AgentAI experimental browser firewall (drops the Chrome user's traffic to private and loopback addresses)
Before=agentai-ufchrome.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/agentai-ufchrome-firewall up
ExecStop=/usr/local/sbin/agentai-ufchrome-firewall down
[Install]
WantedBy=multi-user.target
UNIT
cat > /usr/local/sbin/agentai-ufchrome-firewall <<'SH'
#!/bin/bash
# Own table, one chain, only this user: nothing else on the host is touched.
set -eu
UID_=$(id -u agentai-ufchrome)
nft delete table inet agentai_ufchrome 2>/dev/null || true
[ "${1:-up}" = down ] && exit 0
nft -f - <<NFT
table inet agentai_ufchrome {
  chain out {
    type filter hook output priority 0; policy accept;
    ct state established,related accept
    meta skuid $UID_ ip daddr 127.0.0.53 udp dport 53 accept
    meta skuid $UID_ ip daddr 127.0.0.53 tcp dport 53 accept
    meta skuid $UID_ ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4 } drop
    meta skuid $UID_ ip6 daddr { ::1, fc00::/7, fe80::/10, ff00::/8 } drop
  }
}
NFT
SH
chmod 755 /usr/local/sbin/agentai-ufchrome-firewall
cat > /etc/systemd/system/agentai-ufchrome.service <<'UNIT'
[Unit]
Description=AgentAI experimental browser (owner testing only): one headless Chrome for jev-ultrafast, debugging port on loopback
After=network-online.target agentai-ufchrome-firewall.service
Requires=agentai-ufchrome-firewall.service
[Service]
User=agentai-ufchrome
Group=agentai-ufchrome
ExecStart=/opt/google/chrome/chrome --headless=new --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/var/lib/agentai-ufchrome/profile --no-first-run --no-default-browser-check --disable-gpu --disable-dev-shm-usage --disable-background-networking --window-size=1120,780 about:blank
Restart=on-failure
RestartSec=5
UMask=0077
MemoryMax=1500M
MemorySwapMax=0
CPUQuota=100%
TasksMax=512
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/agentai-ufchrome
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
# no RestrictNamespaces / mount sandboxing beyond the above: Chrome's own sandbox needs user namespaces
[Install]
WantedBy=multi-user.target
UNIT
'''

APPLY = r'''
U=@@U@@
NAME=@@NAME@@
OWNER=$(grep -E '^AGENTAI_SAFETY_OWNER_ACCOUNT=' /etc/agentai-platform/accounts.env | head -1 | cut -d= -f2- | tr -d "\"' ")
echo "$OWNER" | grep -qE '^[0-9a-f]{32}$' || { echo "owner account id not found in accounts.env"; exit 1; }
echo "== 1 users and folders"
id agentai-ultrafast >/dev/null 2>&1 || useradd --system --home-dir $U/home --shell /usr/sbin/nologin agentai-ultrafast
id agentai-ufchrome  >/dev/null 2>&1 || useradd --system --home-dir /var/lib/agentai-ufchrome --shell /usr/sbin/nologin agentai-ufchrome
install -d -m 755 $U
install -d -m 700 -o agentai-ultrafast -g agentai-ultrafast $U/home $U/home/shots $U/home/run
install -d -m 700 -o agentai-ufchrome -g agentai-ufchrome /var/lib/agentai-ufchrome /var/lib/agentai-ufchrome/profile
echo "== 2 python environment"
rm -rf $U/src.new && mkdir $U/src.new && tar -xzf /root/uf-src.tgz -C $U/src.new
[ -x $U/.venv/bin/python ] || python3 -m venv $U/.venv
$U/.venv/bin/pip install --quiet --disable-pip-version-check --require-hashes -r $U/src.new/requirements.txt
SP=$($U/.venv/bin/python -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])')
rm -rf $SP/jev_ultrafast && cp -r $U/src.new/jev_ultrafast $SP/ && chown -R root:root $SP/jev_ultrafast && chmod -R go-w,a+rX $SP/jev_ultrafast
$U/.venv/bin/python -I -c 'import jev_ultrafast, browser_harness; print("agent environment ok")'
echo "== 3 chrome"
if [ ! -x /opt/google/chrome/chrome ]; then
  echo 'repo_add_once="false"' > /etc/default/google-chrome
  curl -fsSL -o /root/uf-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq /root/uf-chrome.deb >/dev/null
  rm -f /root/uf-chrome.deb
fi
/opt/google/chrome/chrome --version
@@UNITS@@
systemctl daemon-reload
systemctl enable --now agentai-ufchrome-firewall.service
systemctl enable --now agentai-ufchrome.service
for i in $(seq 1 20); do curl -fs http://127.0.0.1:9222/json/version >/dev/null && break; sleep 1; done
curl -fs http://127.0.0.1:9222/json/version | head -c 160; echo
echo "== 4 browse service drop-in"
install -d /etc/systemd/system/agentai-browse.service.d
cat > /etc/systemd/system/agentai-browse.service.d/ultrafast.conf <<'DROP'
[Service]
CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_CHOWN CAP_FOWNER CAP_SETUID CAP_SETGID
MemoryMax=768M
DROP
echo "== 5 releases"
SUP_OLD=$(readlink -f /opt/agentai-supervisor/current); APP_OLD=$(readlink -f /opt/agentai-platform/current)
printf 'SUP_OLD=%s\nAPP_OLD=%s\n' "$SUP_OLD" "$APP_OLD" > $U/ROLLBACK
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
echo "== 6 settings and keys"
(umask 077; printf 'BU_CDP_URL=http://127.0.0.1:9222\n' > $U/harness.env; printf '%s' "$OWNER" > /etc/agentai-supervisor/ultrafast-owner)
chmod 644 $U/harness.env
install -d -m 700 /var/lib/agentai-supervisor-secrets/_shared
install -m 600 -o root -g root /root/uf-key /var/lib/agentai-supervisor-secrets/_shared/openrouter-key
shred -u /root/uf-key
echo "== 7 switch releases and restart"
ln -sfn $SUP_NEW /opt/agentai-supervisor/current.new && mv -Tf /opt/agentai-supervisor/current.new /opt/agentai-supervisor/current
ln -sfn $APP_NEW /opt/agentai-platform/current.new && mv -Tf /opt/agentai-platform/current.new /opt/agentai-platform/current
systemctl daemon-reload
systemctl restart agentai-browse.service agentai-platform-app.service
sleep 4
systemctl is-active agentai-ufchrome agentai-browse agentai-platform-app
rm -f /root/uf-src.tgz /root/uf-code.tgz /root/uf-release.json
echo "released $NAME"
'''

SMOKE = r'''
cd /opt/agentai-supervisor/current
PYTHONPATH=. python3 - <<'PY'
# One real task through the production path: root service code -> child as agentai-ultrafast -> Chrome -> back, pictures copied to a job folder.
import json, os, pwd, tempfile, time
from pathlib import Path
from agentai_platform.browse import ultrafast as uf
from agentai_platform.browse.trace import NULL
from agentai_platform.safety import FEATURES
assert 'standard_browser' in FEATURES, 'switch missing from the registry'
U = Path('/opt/agentai-browse/ultrafast'); rd = lambda p: Path(p).read_text().strip()
extra = dict(l.split('=', 1) for l in (U / 'harness.env').read_text().split() if '=' in l)
env = uf.child_env(U / 'home', extra, rd('/var/lib/agentai-supervisor-secrets/_shared/typesafe-key'), rd('/var/lib/agentai-supervisor-secrets/_shared/openrouter-key'))
job = 'f' * 32; scratch = U / 'home' / 'shots' / job; scratch.mkdir(parents=True, exist_ok=True)
owner = pwd.getpwnam('agentai-ultrafast'); os.chown(scratch, owner.pw_uid, owner.pw_gid); os.chmod(scratch, 0o700)
out = Path(tempfile.mkdtemp())
child = uf.Child([str(U / '.venv/bin/python'), '-I', '/opt/agentai-supervisor/current/agentai_platform/browse/ultrafast_driver.py'], env=env, cwd='/tmp', user='agentai-ultrafast', scratch=scratch)
events = []
t0 = time.time()
res = uf.run(child=child, request={'url': 'https://books.toscrape.com/', 'goal': 'Open the Travel category of the bookstore.', 'out': str(scratch), 'max_steps': 6},
             trace=NULL, on_event=lambda k, d: events.append((k, d)), cancelled=lambda: False, allowed=lambda: True, max_seconds=120,
             collect=lambda n: uf.copy_shot(scratch, out, n))
child.kill()
print('result:', res[0], '|', res[1], '|', res[2], f'| {time.time()-t0:.1f}s')
for k, d in events: print(' ', k, {x: d[x] for x in d if x in ('step', 'action', 'label', 'url', 'file', 'changed')})
print('pictures copied:', sorted(p.name for p in out.iterdir()))
assert res[0] in ('done', 'max_steps'), 'smoke task did not complete'
assert any(k == 'step' for k, _ in events), 'no steps were reported'
PY
'''

ROLLBACK = r'''
U=@@U@@
[ -f $U/ROLLBACK ] || { echo "nothing to roll back"; exit 0; }
. $U/ROLLBACK
rm -f /etc/agentai-supervisor/ultrafast-owner /var/lib/agentai-supervisor-secrets/_shared/openrouter-key
ln -sfn "$SUP_OLD" /opt/agentai-supervisor/current.new && mv -Tf /opt/agentai-supervisor/current.new /opt/agentai-supervisor/current
ln -sfn "$APP_OLD" /opt/agentai-platform/current.new && mv -Tf /opt/agentai-platform/current.new /opt/agentai-platform/current
rm -f /etc/systemd/system/agentai-browse.service.d/ultrafast.conf
systemctl disable --now agentai-ufchrome.service agentai-ufchrome-firewall.service || true
nft delete table inet agentai_ufchrome 2>/dev/null || true
systemctl daemon-reload
systemctl restart agentai-browse.service agentai-platform-app.service
sleep 3
systemctl is-active agentai-browse agentai-platform-app
echo "rolled back: supervisor -> $SUP_OLD, app -> $APP_OLD (Chrome, the agent environment and the users stay installed but unused)"
'''


def main():
    if '--rollback' in sys.argv:
        remote(ROLLBACK.replace('@@U@@', U))
        print('Rolled back. If the Safety switch was turned off for your account it no longer does anything; the standard browser is in use.')
        return
    apply = '--apply' in sys.argv
    print('Running the tests first...')
    run([sys.executable, '-m', 'unittest', *TESTS], cwd=PLATFORM, quiet=True)
    print('Tests passed.')
    head = git_head()
    name = f'{time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}-ultrafast-{head[:7]}'
    if not apply:
        print(__doc__)
        print(f'Release name would be {name}. Nothing was changed on the server. Run again with --apply.')
        return
    keys = dotenv_values(PROJECT / '.env')
    key = (keys.get('OPENROUTER_API_KEY') or '').strip()
    if not key:
        raise SystemExit('OPENROUTER_API_KEY is not set in openclaw-project/.env')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with tarfile.open(tmp / 'uf-src.tgz', 'w:gz') as tar:
            for rel in ('jev_ultrafast', 'requirements.txt', 'pyproject.toml', 'LICENSE'):
                tar.add(PROJECT / 'browse-ultrafast' / rel, arcname=rel, filter=lambda i: None if '__pycache__' in i.name else i)
        with tarfile.open(tmp / 'uf-code.tgz', 'w:gz') as tar:
            for rel in CODE_FILES:
                tar.add(PLATFORM / rel, arcname=rel)
        (tmp / 'uf-release.json').write_text(json.dumps({'changes': CODE_FILES, 'commit': head, 'purpose': 'Owner-only experimental jev-ultrafast browser engine behind a timed safety switch',
                                                         'release': name, 'source_sha256': {r: sha(PLATFORM / r) for r in CODE_FILES}}))
        (tmp / 'uf-key').write_text(key)
        (tmp / 'uf-key').chmod(0o600)
        for f in ('uf-src.tgz', 'uf-code.tgz', 'uf-release.json', 'uf-key'):
            upload(tmp / f, f'/root/{f}')
    remote(APPLY.replace('@@U@@', U).replace('@@NAME@@', name).replace('@@UNITS@@', UNITS))
    print('Smoke test: one real task through the production path...')
    remote(SMOKE)
    print(f'\nInstalled and verified ({name}).\nNext: python3 openclaw-project/bin/deploy-lumina.py --apply   (the Safety console wording)')
    print('Turn it on: Safety console -> Browser -> "Use the standard Lumina browser" -> OFF, with a time limit. Roll back: update-ultrafast.py --rollback')


if __name__ == '__main__':
    main()
