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


def start_live_view(args, service):
    """Live frames for browser tasks, on loopback behind the proxy. Runs as threads here because this process alone may read the job folders
    (they hold pictures of customers' pages and stay 0700); the web app's single worker is never involved. No secret file = feature off."""
    import threading
    from agentai_platform.live.gateway import FrameGateway, make_server
    try:
        info = args.live_secret_file.lstat()
        secret = args.live_secret_file.read_bytes().strip()
    except OSError:
        print('live view: off (no secret file)', flush=True)
        return
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o027 or len(secret) < 32:
        raise SystemExit('live secret must be a root-owned file, not world-readable or group-writable, with at least 32 bytes')
    server = make_server(FrameGateway(args.jobs, secret), '127.0.0.1', args.live_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'live view: on 127.0.0.1:{args.live_port}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wiring', type=Path, default=Path('/etc/agentai-supervisor/native-wiring.json'))
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/agentai-supervisor'))
    parser.add_argument('--runner-dir', type=Path, default=Path('/opt/agentai-browse/runner'))
    parser.add_argument('--switches', default='/opt/openclaw-production/feature-switches/switches.json')
    parser.add_argument('--switch-facts', default='/opt/openclaw-production/feature-switches/facts.json')
    parser.add_argument('--jobs', type=Path, default=Path('/var/lib/agentai-browse/jobs'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-browse/browse.sock'))
    parser.add_argument('--image', default='openclaw-sandbox-browser:phase4-2026.9.6')
    parser.add_argument('--jev-key-file', type=Path, default=Path('/var/lib/agentai-supervisor-secrets/_shared/typesafe-key'))
    parser.add_argument('--jev-mode', choices=('off', 'shadow', 'live'), default='shadow')
    parser.add_argument('--app-user', default='agentai-platform')
    parser.add_argument('--live-secret-file', type=Path, default=Path('/etc/agentai-platform/live.secret'))
    parser.add_argument('--live-port', type=int, default=18801)
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
    import threading
    from ..switches import SwitchStore
    from .service import watch_kill_switch, watch_purge
    switches = SwitchStore(args.switches, facts_path=args.switch_facts)
    threading.Thread(target=watch_kill_switch, args=(service, lambda: switches.is_on('browse_tasks'), threading.Event()), daemon=True).start()
    threading.Thread(target=watch_purge, args=(service, threading.Event()), daemon=True).start()      # now, and then every 15 minutes: screenshots and live frames live a day
    start_live_view(args, service)
    app = pwd.getpwnam(args.app_user)
    server = serve(service, str(args.socket), allowed_uids={app.pw_uid}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    server.serve_forever()


if __name__ == '__main__':
    main()
