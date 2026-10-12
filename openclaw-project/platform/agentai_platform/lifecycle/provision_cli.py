"""Host-operator step 1 of giving an account its own assistant cell: record the cell and queue its `create`.

Run as the app user (so database files keep their owner); step 2 is enroll_cli as root. The lifecycle worker
then creates the cell (volume, gateway token, model key, model route); the cell starts on the first message.
"""
import argparse
from pathlib import Path

from agentai_platform.store import Store

from . import profiles
from .coordinator import Coordinator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app-db', type=Path, default=Path('/var/lib/agentai-platform/platform.sqlite3'))
    parser.add_argument('--account', required=True)
    args = parser.parse_args()
    result = Coordinator(Store(args.app_db), profiles={profiles.PROFILE_ID}).host_create(
        args.account, key='host-create-' + args.account[:40], target_profile=profiles.PROFILE_ID)
    print(f"queued create {result['id']} ({result['state']})")


if __name__ == '__main__':
    main()
