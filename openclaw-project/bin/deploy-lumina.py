#!/usr/bin/env python3
"""Build the Lumina web app and install it at https://<site>/app/ (replaces the previous bundle, keeping one backup).

    python3 openclaw-project/bin/deploy-lumina.py            # build + test + show plan
    python3 openclaw-project/bin/deploy-lumina.py --apply    # also upload and switch

Rollback: ssh in and `mv /var/lib/agentai-platform/ui.prev /var/lib/agentai-platform/ui` (see OPERATIONS.md).
Nothing on the server is restarted; the account app serves the files straight from the folder.
"""
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMINA = HERE.parent / 'lumina'
REMOTE = '/var/lib/agentai-platform'


def run(argv, cwd=None):
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        print((done.stdout + done.stderr)[-1500:])
        raise SystemExit(f'failed: {" ".join(argv)}')
    return done.stdout


def main():
    apply = '--apply' in sys.argv
    run(['npm', 'ci', '--ignore-scripts'], LUMINA)
    run(['npm', 'test'], LUMINA)
    run(['npm', 'run', 'build'], LUMINA)
    dist = LUMINA / 'dist'
    assert (dist / 'index.html').is_file(), 'build produced no index.html'
    size = sum(f.stat().st_size for f in dist.rglob('*') if f.is_file())
    print(f'Built {dist} ({size // 1024} KiB). Tests passed.')
    if not apply:
        print('Nothing was uploaded. Run again with --apply to install it.')
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / 'lumina-ui.tgz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(dist, arcname='.')
        run([sys.executable, str(HERE / 'scp-server'), str(archive), '/root/lumina-ui.tgz'])
    script = f'''set -e
cd {REMOTE}
rm -rf ui.new ui.prev
install -d -m 755 -o root -g agentai-platform ui.new
tar -xzf /root/lumina-ui.tgz -C ui.new --no-same-owner
chown -R root:agentai-platform ui.new; chmod -R go-w,a+rX ui.new
test -f ui.new/index.html
[ -d ui ] && mv ui ui.prev
mv ui.new ui
# The chat film is served by Caddy from its own public folder (the state directory is private); keep that copy in step.
if [ -d ui/scenes ]; then
  install -d -m 755 /var/www/lumina-scenes/app
  rm -rf /var/www/lumina-scenes/app/scenes.new
  cp -r ui/scenes /var/www/lumina-scenes/app/scenes.new
  chown -R root:root /var/www/lumina-scenes/app/scenes.new; chmod -R u=rwX,go=rX /var/www/lumina-scenes/app/scenes.new
  rm -rf /var/www/lumina-scenes/app/scenes.old
  [ -d /var/www/lumina-scenes/app/scenes ] && mv /var/www/lumina-scenes/app/scenes /var/www/lumina-scenes/app/scenes.old
  mv /var/www/lumina-scenes/app/scenes.new /var/www/lumina-scenes/app/scenes
fi
ls ui | head -5'''
    print(run([sys.executable, str(HERE / 'ssh-server'), script]))
    print('Installed. Open /app/ on your site.')


if __name__ == '__main__':
    main()
