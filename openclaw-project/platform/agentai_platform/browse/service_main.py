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

from .device_gateway import DeviceGateway, make_server as make_device_server, sweep_forever
from .device_transport import DeviceTransport
from .devices import DeviceDesk, DeviceHub, DeviceStore
from .ladder import JevChooser
from .native_runner import NativeRunner, NativeTransport
from .service import BrowseError, BrowseService, serve, stage_argv
from .session import ProcessTransport
from .picture_only_brain import PictureOnlyChooser
from .ultrafast_brain import UltrafastChooser

JEV_ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
JEV_MODEL = 'jev-1.14.0'            # box questions and pictures need 1.14; the same model decides controls steps and picture steps


def local_enabled(config, account=None):
    """Is the customer's-own-Chrome engine available to `account`? To everyone, unless browse-engine.json says `"local": false` (off for all) or `"local": ["<account id>", ...]`
    (only those accounts: how it is tried out before it is opened to everyone). An empty list means nobody."""
    if not isinstance(config, dict):
        return True
    local = config.get('local')
    if local is False:
        return False
    if isinstance(local, list):
        return account in local
    return True


def pick_engine(config, account, device_connected, wants_local=False):
    """Which hands a new job for `account` gets, from browse-engine.json: 'local' (the customer's own Chrome) when the customer has switched "use my own browser" on AND
    their extension is connected right now AND the feature is open to that account (see local_enabled), else 'native' when listed under "native" (or the file's
    default is native), else the host stage. A switch that is on while the extension is off quietly means the hosted browser: the icon at the top of the chat says which."""
    if not isinstance(config, dict):
        return 'runner'
    if wants_local and device_connected and local_enabled(config, account):
        return 'local'
    listed = config.get('native')
    if isinstance(listed, list) and account in listed:
        return 'native'
    return 'native' if config.get('default') == 'native' else 'runner'


def start_device_gateway(args, hub, store):
    """The customers' extensions connect here (loopback, behind the proxy). No port = off."""
    import threading
    if not args.device_port:
        print('devices: off (no port)', flush=True)
        return None
    gateway = DeviceGateway(store, hub, origins=[o for o in args.device_origin if o])
    threading.Thread(target=make_device_server(gateway, '127.0.0.1', args.device_port).serve_forever, daemon=True).start()
    threading.Thread(target=sweep_forever, args=(gateway, threading.Event()), daemon=True).start()
    print(f'devices: on 127.0.0.1:{args.device_port}', flush=True)
    return gateway


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
    parser.add_argument('--device-port', type=int, default=18802)       # 0 = the customer's-own-Chrome engine is off
    parser.add_argument('--device-store', type=Path, default=Path('/var/lib/agentai-supervisor/devices.json'))
    parser.add_argument('--device-origin', action='append', default=[])   # the extension's origin, chrome-extension://<id>; none given = any extension origin (token still required)
    parser.add_argument('--safety-file', type=Path, default=Path('/var/lib/agentai-platform/safety-switches.json'))       # the account's safety switches, written by the app (agentai_platform/safety.py)
    parser.add_argument('--ultrafast-owner-file', type=Path, default=Path('/etc/agentai-supervisor/ultrafast-owner'))      # the one account id allowed to use the experimental decider; no file = off
    parser.add_argument('--ultrafast-text-key-file', type=Path, default=Path('/var/lib/agentai-supervisor-secrets/_shared/openrouter-key'))       # for its fast text writer
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

    def read_secret(path):
        try:
            return path.read_text().strip()
        except OSError:
            return ''

    def ultrafast_on(account):
        """The experimental decider (ultrafast_brain.py) on the same browser: only for the owner's own account, and only while the standard decider is switched off for it
        (the Safety console's `standard_browser`, which can carry a time limit). Read when a task starts. Anything missing or unreadable means the standard decider."""
        owner = read_secret(args.ultrafast_owner_file)
        return bool(owner) and account == owner and not safety.on(account, 'standard_browser')

    def picture_only_on(account):
        """The owner's navigation test (picture_only_brain.py): only for the owner's own account, and only while its `jev_sees_controls` switch is off (with a time limit). Read when a task starts."""
        owner = read_secret(args.ultrafast_owner_file)
        return bool(owner) and account == owner and not safety.on(account, 'jev_sees_controls')

    def jev_for(account):
        key = read_secret(args.jev_key_file)
        if not key:
            return None
        if picture_only_on(account):
            return PictureOnlyChooser(JEV_ENDPOINT, JEV_MODEL, key, http_post)
        if ultrafast_on(account):
            return UltrafastChooser(JEV_ENDPOINT, key, http_post, read_secret(args.ultrafast_text_key_file), http_post)
        return JevChooser(JEV_ENDPOINT, JEV_MODEL, key, http_post)

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

    hub = DeviceHub()
    device_store = DeviceStore(args.device_store)

    def local_allowed(account):
        """Is the customer's-own-Chrome engine open to this account? See local_enabled (read each time, like the engine choice itself)."""
        try:
            return local_enabled(json.loads(args.engine_file.read_text()), account)
        except (OSError, ValueError):
            return True

    def local_spawn(account, job_id, out_dir):
        """The customer's own Chrome, through their paired extension (this process is the only one that holds the connection)."""
        link = hub.link(account)
        if link is None:
            raise BrowseError('your browser is not connected. Open the Lumina extension in Chrome and switch it on.')
        return DeviceTransport(link, out_dir)

    def engine_for(account):
        """Which hands a new job for this account gets (see pick_engine). Read at every start, so a change needs no restart."""
        try:
            config = json.loads(args.engine_file.read_text())
        except (OSError, ValueError):
            config = {}                                   # no file: nothing is listed for native, and the customer's own Chrome is on unless the file says otherwise
        return pick_engine(config, account, hub.link(account) is not None, device_store.wants_local(account))

    service = BrowseService(spawn=spawn, jev_for=jev_for, root=args.jobs, jev_mode=args.jev_mode, native_spawn=native_spawn, engine_for=engine_for, switch_for=safety.for_account, local_spawn=local_spawn,
                           devices=DeviceDesk(device_store, hub, allowed=local_allowed) if args.device_port else None)
    import threading
    from ..switches import SwitchStore
    from .service import watch_kill_switch, watch_purge
    switches = SwitchStore(args.switches, facts_path=args.switch_facts)
    threading.Thread(target=watch_kill_switch, args=(service, lambda: switches.is_on('browse_tasks'), threading.Event()), daemon=True).start()
    threading.Thread(target=watch_purge, args=(service, threading.Event()), daemon=True).start()      # now, and then every 15 minutes: screenshots and live frames live a day
    start_live_view(args, service)
    start_device_gateway(args, hub, device_store)
    app = pwd.getpwnam(args.app_user)
    server = serve(service, str(args.socket), allowed_uids={app.pw_uid}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    server.serve_forever()


if __name__ == '__main__':
    main()
