"""Render service entry point (root). Runs conversions in throwaway containers on the cell engine and serves the app over a private unix socket."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat

from .service import RenderService, serve

IMAGE = re.compile(r'^[a-z0-9][a-z0-9._/-]{0,120}(:[A-Za-z0-9._-]{1,64}|@sha256:[a-f0-9]{64})$')


def main():
    parser = argparse.ArgumentParser(description='Lumina render service')
    parser.add_argument('--wiring', type=Path, default=Path('/etc/agentai-supervisor/native-wiring.json'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-render/render.sock'))
    parser.add_argument('--jobs', type=Path, default=Path('/var/lib/agentai-render/jobs'))
    parser.add_argument('--image', default='lumina-renderer:1')
    parser.add_argument('--app-user', default='agentai-platform')
    parser.add_argument('--slots', type=int, default=2)
    args = parser.parse_args()
    if not IMAGE.fullmatch(args.image):
        raise SystemExit('invalid renderer image name')
    info = args.wiring.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise SystemExit('wiring file must be host-owned without group/world writes')
    wiring = json.loads(args.wiring.read_text())
    docker_host = (json.loads(Path(wiring['fleet_custody']).read_text()).get('env') or {}).get('DOCKER_HOST')
    if not docker_host:
        raise SystemExit('wiring needs the cell engine socket')
    args.jobs.mkdir(parents=True, exist_ok=True)
    os.chmod(args.jobs, 0o711)                     # root-owned; the container user passes through to its own job folders only
    service = RenderService(args.jobs, image=args.image, env={**os.environ, 'DOCKER_HOST': docker_host}, slots=max(1, min(args.slots, 4)))
    service.sweep()
    app = pwd.getpwnam(args.app_user)
    server = serve(service, str(args.socket), allowed_uids={app.pw_uid}, group_gid=grp.getgrnam(args.app_user).gr_gid)
    print(f'render service on {args.socket} (image {args.image})', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
