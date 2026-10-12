import os
from pathlib import Path
import tempfile
import time
import unittest
from agentai_platform.ops.housekeeping import prune_snapshots


class HousekeepingChecks(unittest.TestCase):
    def test_only_old_or_excess_snapshots_matching_the_exact_pattern_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); now = 2_000_000_000
            names = [f'backup-20261001T0{i}0000Z-premigrate.sqlite3' for i in range(6)]
            for i, name in enumerate(names):
                (d / name).write_text('x'); os.utime(d / name, (now - i * 86400, now - i * 86400))
            for keepers in ('platform.sqlite3', 'platform.sqlite3-wal', 'backup-notes.txt', 'backup-20261001T000000Z.sqlite3.bak'):
                (d / keepers).write_text('keep'); os.utime(d / keepers, (0, 0))
            removed = prune_snapshots(d, keep=3, now=now)
            self.assertEqual(sorted(removed), sorted(names[3:]))
            self.assertTrue({'platform.sqlite3', 'platform.sqlite3-wal', 'backup-notes.txt', 'backup-20261001T000000Z.sqlite3.bak'} <= {p.name for p in d.iterdir()})
    def test_age_limit_applies_but_the_newest_snapshot_always_survives(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); now = 2_000_000_000
            for i, age in enumerate((40, 50)):
                p = d / f'backup-2026100{i}T000000Z-x.sqlite3'; p.write_text('x'); os.utime(p, (now - age * 86400, now - age * 86400))
            self.assertEqual(len(prune_snapshots(d, keep=5, now=now)), 1); self.assertEqual(len(list(d.iterdir())), 1)
if __name__ == '__main__': unittest.main()
