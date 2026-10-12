"""Lifecycle worker entry point (runs as the app identity, never as root).

Reads the app database, talks to the host supervisor only through its Unix
socket, and recomputes host capacity before every dispatch. It holds no Docker
socket, no secrets and no enrollment authority.
"""
import argparse
import json
from pathlib import Path
import time

from agentai_platform.store import Store

from .profiles import host_capacity
from .supervisor_transport import SocketDriver
from .worker import LifecycleWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, default=Path('/var/lib/agentai-platform/platform.sqlite3'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-supervisor/control.sock'))
    parser.add_argument('--interval', type=int, default=15)
    parser.add_argument('--idle-after', type=int, default=900)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.interval <= 3600 or not 60 <= args.idle_after <= 86400:
        raise SystemExit('invalid timing')
    # Native operations (volume + create, restore + health) take minutes; a timeout is
    # an uncertain outcome that the reconcile pass resolves from the supervisor journal.
    worker = LifecycleWorker(Store(args.db), SocketDriver(args.socket, timeout_seconds=600), host_capacity,
                             idle_after=args.idle_after)
    while True:
        # Counts only: no account, tenant, token or path ever reaches the journal.
        print(json.dumps(worker.tick(), sort_keys=True), flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
