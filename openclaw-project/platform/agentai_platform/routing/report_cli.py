"""Prints the routing report as JSON (read-only database access). Used by the owner dashboard."""
import json
import sqlite3
import sys
import time
from contextlib import contextmanager

from .store import report


class ReadOnly:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        con = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/var/lib/agentai-platform/platform.sqlite3'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    print(json.dumps(report(ReadOnly(path), time.time() - days * 86400)))


if __name__ == '__main__':
    main()
