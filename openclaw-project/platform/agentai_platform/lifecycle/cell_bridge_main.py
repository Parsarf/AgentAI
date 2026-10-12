"""Cell bridge entry point (root). Serves the app's private socket; see cell_bridge.py."""
import argparse
import grp
import json
from pathlib import Path
import pwd
import sqlite3
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

    def spend(tenant):
        key = secrets.provider_key(tenant)
        if key is None:
            raise RuntimeError('no provider key')
        return litellm.key_spend_microusd(key)

    app = pwd.getpwnam(args.app_user)
    bridge = CellBridge(lookup, lambda tenant, token: DockerRelay(tenant, token, docker_host=docker_host), spend,
                        ready_timeout=100)
    server = serve(bridge, str(args.socket), allowed_uids={app.pw_uid}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    try:
        server.serve_forever()
    finally:
        bridge.close_all()


if __name__ == '__main__':
    main()
