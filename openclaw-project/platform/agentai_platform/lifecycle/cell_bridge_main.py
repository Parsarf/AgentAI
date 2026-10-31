"""Cell bridge entry point (root). Serves the app's private socket; see cell_bridge.py."""
import argparse
import grp
import hmac
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import stat

from .cell_bridge import CellBridge, DockerRelay, serve
from .litellm_admin import LiteLLMAdmin
from .secrets_custody import SecretStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wiring', type=Path, default=Path('/etc/agentai-supervisor/native-wiring.json'))
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/agentai-supervisor'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-cell-bridge/bridge.sock'))
    parser.add_argument('--app-user', default='agentai-platform')
    args = parser.parse_args()
    info = args.wiring.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit('wiring file must be host-owned without group/world writes')
    wiring = json.loads(args.wiring.read_text())
    custody = json.loads(Path(wiring['fleet_custody']).read_text())
    docker_host = (custody.get('env') or {}).get('DOCKER_HOST')
    if not docker_host or not wiring.get('litellm_env'):
        raise SystemExit('wiring needs the cell engine socket and litellm_env')
    secrets = SecretStore(wiring['secrets_dir'])
    litellm = LiteLLMAdmin(wiring['litellm_env'])
    db = args.state_dir / 'custody.sqlite3'

    def lookup(account):
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            row = con.execute("SELECT tenant FROM bindings WHERE account=? AND state='running'", (account,)).fetchone()
        finally:
            con.close()
        return (row[0], secrets.gateway_token(row[0])) if row else None

    def binding(account):
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            row = con.execute('SELECT tenant FROM bindings WHERE account=?', (account,)).fetchone()
        finally:
            con.close()
        return row[0] if row else None

    def probe(tenant):
        done = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', f'openclaw-cell-{tenant}'], capture_output=True, text=True,
                              env={**os.environ, 'DOCKER_HOST': docker_host}, timeout=20)
        return done.returncode == 0 and done.stdout.strip() == 'true'

    def spend(tenant):
        key = secrets.provider_key(tenant)
        if key is None:
            raise RuntimeError('no provider key')
        return litellm.key_spend_microusd(key)

    def identify(credential):
        """Which account does this cell credential belong to? A cell proves itself with its own model key (the one it was provisioned with), so the tool relay needs no secret of its own.
        Every running binding is compared in constant time; none is skipped early."""
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            rows = con.execute("SELECT account, tenant FROM bindings WHERE state='running'").fetchall()
        finally:
            con.close()
        found = None
        for account, tenant in rows:
            key = secrets.provider_key(tenant)
            if key and hmac.compare_digest(key.encode(), credential.encode()):
                found = account
        return found

    app = pwd.getpwnam(args.app_user)
    # root (the browse service) may connect too, and only root may use the browser methods; the app user keeps exactly the methods it had.
    bridge = CellBridge(lookup, lambda tenant, token, scopes=None: DockerRelay(tenant, token, docker_host=docker_host, scopes=scopes), spend,
                        binding=binding, probe=probe, ready_timeout=100, workspace_root=wiring.get('cell_state_root'), identify=identify, browser_callers={0})
    server = serve(bridge, str(args.socket), allowed_uids={app.pw_uid, 0}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    try:
        server.serve_forever()
    finally:
        bridge.close_all()


if __name__ == '__main__':
    main()
