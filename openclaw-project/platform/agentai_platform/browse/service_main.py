"""Browse service entry point (root). Wires the stage launcher, per-account model keys and the TypeSafe key to BrowseService."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import sqlite3
import stat

from agentai_platform.lifecycle.secrets_custody import SecretStore
from agentai_platform.routing.classifier import http_post

from .ladder import JevChooser
from .llm import LiteLLM
from .service import BrowseService, serve, stage_argv
from .session import ProcessTransport

JEV_ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
JEV_MODEL = 'jev-1.13.0'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wiring', type=Path, default=Path('/etc/agentai-supervisor/native-wiring.json'))
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/agentai-supervisor'))
    parser.add_argument('--runner-dir', type=Path, default=Path('/opt/agentai-browse/runner'))
    parser.add_argument('--jobs', type=Path, default=Path('/var/lib/agentai-browse/jobs'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-browse/browse.sock'))
    parser.add_argument('--image', default='openclaw-sandbox-browser:phase4-2026.9.6')
    parser.add_argument('--jev-key-file', type=Path, default=Path('/var/lib/agentai-supervisor-secrets/_shared/typesafe-key'))
    parser.add_argument('--jev-mode', choices=('off', 'shadow', 'live'), default='shadow')
    parser.add_argument('--app-user', default='agentai-platform')
    args = parser.parse_args()
    info = args.wiring.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit('wiring file must be host-owned without group/world writes')
    wiring = json.loads(args.wiring.read_text())
    docker_host = (json.loads(Path(wiring['fleet_custody']).read_text()).get('env') or {}).get('DOCKER_HOST')
    if not docker_host:
        raise SystemExit('wiring needs the cell engine socket')
    secrets = SecretStore(wiring['secrets_dir'])
    db = args.state_dir / 'custody.sqlite3'
    args.jobs.mkdir(parents=True, exist_ok=True)
    os.chmod(args.jobs, 0o700)

    def tenant_of(account):
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            row = con.execute('SELECT tenant FROM bindings WHERE account=?', (account,)).fetchone()
        finally:
            con.close()
        if not row:
            raise RuntimeError('no binding')
        return row[0]

    def llm_for(account):
        key = secrets.provider_key(tenant_of(account))
        if not key:
            raise RuntimeError('no provider key')
        return LiteLLM(key)

    def jev_for(account):
        try:
            key = args.jev_key_file.read_text().strip()
        except OSError:
            return None
        return JevChooser(JEV_ENDPOINT, JEV_MODEL, key, http_post) if key else None

    def spawn(job_id, out_dir):
        argv = stage_argv(job_id, str(out_dir), str(args.runner_dir), args.image)
        return ProcessTransport(argv, env={**os.environ, 'DOCKER_HOST': docker_host})

    service = BrowseService(spawn=spawn, llm_for=llm_for, jev_for=jev_for, root=args.jobs, jev_mode=args.jev_mode)
    service.purge()                                  # screenshots left from before a restart
    app = pwd.getpwnam(args.app_user)
    server = serve(service, str(args.socket), allowed_uids={app.pw_uid}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    server.serve_forever()


if __name__ == '__main__':
    main()
