"""Host-operator enrollment of one account's cell binding (root only; never exposed by the socket).

The app queued a `create` and holds the opaque tenant/deployment identifiers; the
host operator decides the pinned image, loopback ports, volume cap and resources.
Run as root on the host, once per account, before the worker may dispatch for it.
"""
import argparse
from pathlib import Path
import sqlite3

from . import profiles
from .fleet_plan import FleetBinding
from .supervisor import HostSupervisor

PORT_BASE, PORT_LIMIT = 19101, 19140


def free_port(supervisor):
    with supervisor.connect() as con:
        used = {r[0] for r in con.execute('SELECT port FROM bindings')}
    used |= {p + 50 for p in used}   # each binding also reserves its quarantine port
    for port in range(PORT_BASE, PORT_LIMIT):
        if port not in used and port + 50 not in used:
            return port
    raise SystemExit('no free loopback port in the trial range')


def build_binding(app_db, account, image, backup_root, port):
    con = sqlite3.connect(f'file:{app_db}?mode=ro', uri=True)
    row = con.execute('SELECT deployment_id,tenant_ref,profile_revision FROM lifecycle_cells WHERE account_id=?', (account,)).fetchone()
    if not row:
        raise SystemExit('account has no queued lifecycle binding')
    deployment, tenant, profile = row
    return FleetBinding(
        account_id=account, deployment_id=deployment, tenant_ref=tenant, profile_revision=profile,
        image=image, port=port, memory_bytes=profiles.CELL_MEMORY, cpu_millis=profiles.CELL_MILLIS,
        pid_limit=profiles.CELL_PIDS, archive_limit_bytes=2 * 1024**3, backup_root=Path(backup_root) / account,
        upgrade_image=None, quarantine_port=port + 50, volume_bytes=profiles.VOLUME_BYTES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-db', type=Path, required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/agentai-supervisor'))
    parser.add_argument('--backup-root', type=Path, default=Path('/var/lib/agentai-cells/backups'))
    args = parser.parse_args()
    supervisor = HostSupervisor(args.state_dir, backend=None, owner_uid=0)
    binding = build_binding(args.app_db, args.account, args.image, args.backup_root, free_port(supervisor))
    binding.backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    supervisor.enroll(binding)
    print(f'enrolled {args.account} on port {binding.port}')


if __name__ == '__main__':
    main()
