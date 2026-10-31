"""Lifecycle worker entry point (runs as the app identity, never as root).

Reads the app database, talks to the host supervisor only through its Unix
socket, and recomputes host capacity before every dispatch. It holds no Docker
socket, no secrets and no enrollment authority.
"""
import argparse
import json
import os
from pathlib import Path
import time

from agentai_platform.events import EventService
from agentai_platform.store import Store
from agentai_platform.switches import SwitchStore

from agentai_platform.bridge_client import BridgeRpc

from .profiles import host_capacity
from .supervisor_transport import SocketDriver
from .worker import LifecycleWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, default=Path('/var/lib/agentai-platform/platform.sqlite3'))
    parser.add_argument('--socket', type=Path, default=Path('/run/agentai-supervisor/control.sock'))
    parser.add_argument('--interval', type=int, default=15)
    parser.add_argument('--idle-after', type=int, default=900)
    parser.add_argument('--switches-file', default=os.environ.get('AGENTAI_SWITCHES_FILE', ''))
    parser.add_argument('--switch-facts-file', default=os.environ.get('AGENTAI_SWITCH_FACTS_FILE', ''))
    parser.add_argument('--bridge-socket', type=Path, default=Path('/run/agentai-cell-bridge/bridge.sock'))
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.interval <= 3600 or not 60 <= args.idle_after <= 86400:
        raise SystemExit('invalid timing')
    # Native operations (volume + create, restore + health) take minutes; a timeout is
    # an uncertain outcome that the reconcile pass resolves from the supervisor journal.
    def observe(account):
        try:
            return bool(BridgeRpc(account, args.bridge_socket, timeout=30)('cell.status', {})['running'])
        except Exception:
            return None   # unknown is never treated as 'gone'

    switches = SwitchStore(args.switches_file or None, facts_path=args.switch_facts_file or None)
    worker = LifecycleWorker(Store(args.db), SocketDriver(args.socket, timeout_seconds=600), host_capacity,
                             idle_after=args.idle_after, backup_max_age=20 * 3600,
                             wake=lambda: switches.is_on('customer_execution'), observe=observe, events=EventService(Store(args.db)))
    while True:
        # Counts only: no account, tenant, token or path ever reaches the journal.
        print(json.dumps(worker.tick(), sort_keys=True), flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
