"""Private supervisor entry point. Native effects intentionally disabled.

The entry point is usable for transport/custody installation checks, but cannot
execute native lifecycle operations until a verified backend is implemented.
"""
import argparse
import grp
import os
from pathlib import Path
import pwd
import socket
import stat

from .supervisor import HostSupervisor
from .supervisor_transport import handle_connection
from .types import DisabledDriver


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--controller-user',default='agentai-lifecycle-control')
    parser.add_argument('--state-dir',type=Path,default=Path('/var/lib/agentai-supervisor'))
    parser.add_argument('--socket',type=Path,default=Path('/run/agentai-supervisor/control.sock'))
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0: raise SystemExit('host supervisor requires root custody')
    uid=pwd.getpwnam(args.controller_user).pw_uid
    gid=grp.getgrnam(args.controller_user).gr_gid
    if uid==0: raise SystemExit('controller must be unprivileged')
    supervisor=HostSupervisor(args.state_dir,DisabledDriver(),owner_uid=0)
    if args.check:
        print('{"custody_ready":true,"native_execution_enabled":false}');return
    parent=args.socket.parent
    info=parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:
        raise SystemExit('socket directory must be host-owned without group/world writes')
    # No automatic unlink: an old server or unknown socket needs operator review.
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
        server.bind(str(args.socket));os.chown(args.socket,0,gid);os.chmod(args.socket,0o660)
        identity=args.socket.lstat()
        try:
            server.listen(1)
            while True:
                conn,_=server.accept()
                with conn:
                    conn.settimeout(5)
                    try: handle_connection(conn,supervisor,controller_uid=uid)
                    except OSError: pass # Closed/slow client; journal remains authoritative.
        finally:
            current=args.socket.lstat()
            if (current.st_dev,current.st_ino)==(identity.st_dev,identity.st_ino): args.socket.unlink()


if __name__=='__main__': main()
