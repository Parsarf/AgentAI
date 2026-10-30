"""Browse service entry point (root). Wires the stage launcher, per-account model keys and the TypeSafe key to BrowseService."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import stat

from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.routing.classifier import http_post

from .ladder import JevChooser
from .native_runner import NativeRunner, NativeTransport
from .service import BrowseService, serve, stage_argv
from .session import ProcessTransport

JEV_ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
JEV_MODEL = 'jev-1.14.0'            # box questions and pictures need 1.14; the same model decides controls steps and picture steps


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
    parser.add_argument('--jev-mode', choices=('off', 'live', 'shadow'), default='live')       # 'shadow' is retired (it compared JEV with model tiers that no longer exist): it runs as 'live'
    parser.add_argument('--app-user', default='agentai-platform')
    parser.add_argument('--live-secret-file', type=Path, default=Path('/etc/agentai-platform/live.secret'))
    parser.add_argument('--live-port', type=int, default=18801)
    parser.add_argument('--bridge-socket', type=Path, default=Path('/run/agentai-cell-bridge/bridge.sock'))
    parser.add_argument('--engine-file', type=Path, default=Path('/etc/agentai-supervisor/browse-engine.json'))
    parser.add_argument('--safety-file', type=Path, default=Path('/var/lib/agentai-platform/safety-switches.json'))       # the account's safety switches, written by the app (agentai_platform/safety.py)
    parser.add_argument('--ultrafast-dir', type=Path, default=Path('/opt/agentai-browse/ultrafast'))      # the experimental engine's own python environment (.venv) and non-secret settings (harness.env)
    parser.add_argument('--ultrafast-owner-file', type=Path, default=Path('/etc/agentai-supervisor/ultrafast-owner'))      # the one account id allowed to use it; no file = off
    parser.add_argument('--ultrafast-text-key-file', type=Path, default=Path('/var/lib/agentai-supervisor-secrets/_shared/openrouter-key'))
    parser.add_argument('--ultrafast-user', default='agentai-ultrafast')                                  # the child runs as this unprivileged user, never as root
    args = parser.parse_args()
    if args.jev_mode == 'shadow':
        print('jev-mode shadow is retired; running as live', flush=True)
        args.jev_mode = 'live'
    info = args.wiring.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit('wiring file must be host-owned without group/world writes')
    wiring = json.loads(args.wiring.read_text())
    docker_host = (json.loads(Path(wiring['fleet_custody']).read_text()).get('env') or {}).get('DOCKER_HOST')
    if not docker_host:
        raise SystemExit('wiring needs the cell engine socket')
    args.jobs.mkdir(parents=True, exist_ok=True)
    os.chmod(args.jobs, 0o700)

    def jev_for(account):
        try:
            key = args.jev_key_file.read_text().strip()
        except OSError:
            return None
        return JevChooser(JEV_ENDPOINT, JEV_MODEL, key, http_post) if key else None

    def spawn(job_id, out_dir):
        argv = stage_argv(job_id, str(out_dir), str(args.runner_dir), args.image)
        return ProcessTransport(argv, env={**os.environ, 'DOCKER_HOST': docker_host})

    from ..safety import Reader
    safety = Reader(args.safety_file)

    def native_spawn(account, job_id, out_dir):
        """The browser of the account's own cell, through the cell bridge (this process is root, the only caller the bridge lets use the browser methods).
        Its address rules follow the account's `ssrf_guard` switch, read when the job starts."""
        call = BridgeRpc(account, args.bridge_socket, timeout=75)
        return NativeTransport(call, out_dir, runner=NativeRunner(call, out_dir, allow_private=not safety.on(account, 'ssrf_guard')))

    def engine_for(account):
        """Which hands a new job for this account gets: 'native' when the engine file lists the account (or its default is native), else the host stage. Read at every start, so a change needs no restart."""
        try:
            config = json.loads(args.engine_file.read_text())
        except (OSError, ValueError):
            return 'runner'
        if not isinstance(config, dict):
            return 'runner'
        listed = config.get('native')
        if isinstance(listed, list) and account in listed:
            return 'native'
        return 'native' if config.get('default') == 'native' else 'runner'

    def read_secret(path):
        try:
            return path.read_text().strip()
        except OSError:
            return ''

    def ultrafast_for(account):
        """The experimental engine: True only for the owner's own account, only while the standard browser is switched off for it (the temporary toggle; an "off" with a time
        limit lapses by itself), and only when its environment and both keys are installed. Anything missing or unreadable means the standard browser."""
        owner = read_secret(args.ultrafast_owner_file)
        if not owner or account != owner or safety.on(account, 'standard_browser'):
            return False
        return (args.ultrafast_dir / '.venv' / 'bin' / 'python').is_file() and bool(read_secret(args.jev_key_file)) and bool(read_secret(args.ultrafast_text_key_file))

    def ultrafast_spawn(job_id, out_dir):
        """The child gets the goal and a start address on stdin and its two model keys in its environment (never argv), as an unprivileged user."""
        from .ultrafast import Child, child_env
        extra = {}
        try:
            for line in (args.ultrafast_dir / 'harness.env').read_text().splitlines():
                key, sep, value = line.partition('=')
                if sep and key.strip() and not line.lstrip().startswith('#'):
                    extra[key.strip()] = value.strip()
        except OSError:
            pass
        env = child_env(args.ultrafast_dir / 'home', extra, read_secret(args.jev_key_file), read_secret(args.ultrafast_text_key_file))
        driver = Path(__file__).with_name('ultrafast_driver.py')
        return Child([str(args.ultrafast_dir / '.venv' / 'bin' / 'python'), '-I', str(driver)], env=env, cwd='/tmp', user=args.ultrafast_user)

    service = BrowseService(spawn=spawn, jev_for=jev_for, root=args.jobs, jev_mode=args.jev_mode, native_spawn=native_spawn, engine_for=engine_for, switch_for=safety.for_account,
                            ultrafast_spawn=ultrafast_spawn, ultrafast_for=ultrafast_for)
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
