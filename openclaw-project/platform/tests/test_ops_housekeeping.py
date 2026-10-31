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
    def test_the_names_the_release_tool_really_makes_are_pruned(self):
        """deploy/release.py names a snapshot backup-<utc time>-premigrate-<release folder>.sqlite3, and release folders carry upper-case T and Z (20261012T1830Z-ops). A pattern that only allowed
        lower case matched none of them, so 114 plaintext database copies piled up on the server with the cleanup running every day."""
        real = ['backup-20261012T174815Z-premigrate-20261012T1830Z-ops.sqlite3', 'backup-20261012T180019Z-premigrate-20261012T1930Z-ops2.sqlite3',
                'backup-20261028T213159Z-premigrate-20261028T212308Z-tool-origin-v2.sqlite3', 'backup-20261027T114642Z-premigrate-20261027T114539Z-cancel-e700e33.sqlite3',
                'backup-20261030T095435Z-before-stale-browse-cleanup.sqlite3']
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); now = 2_000_000_000
            for i, name in enumerate(real):
                (d / name).write_text('x'); os.utime(d / name, (now - i * 86400, now - i * 86400))
            removed = prune_snapshots(d, keep=3, now=now)
            self.assertEqual(sorted(removed), sorted(real[3:]))
            self.assertEqual(sorted(p.name for p in d.iterdir()), sorted(real[:3]))
    def test_a_removed_copy_takes_its_sidecars_with_it_and_a_kept_one_keeps_them(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); now = 2_000_000_000
            names = [f'backup-2026100{i}T000000Z-premigrate-2026100{i}T0000Z-ops.sqlite3' for i in range(4)]
            for i, name in enumerate(names):
                for suffix in ('', '-wal', '-shm'):
                    (d / (name + suffix)).write_text('x'); os.utime(d / (name + suffix), (now - i * 86400, now - i * 86400))
            (d / 'platform.sqlite3-wal').write_text('live'); (d / 'backup-20261009T000000Z-lonely.sqlite3-wal').write_text('orphan')      # not a copy's sidecar: left alone
            prune_snapshots(d, keep=2, now=now)
            left = sorted(p.name for p in d.iterdir())
            self.assertEqual([n for n in left if n.startswith('backup-2026100') and 'premigrate' in n], sorted(n + s for n in names[:2] for s in ('', '-wal', '-shm')))
            self.assertIn('platform.sqlite3-wal', left); self.assertIn('backup-20261009T000000Z-lonely.sqlite3-wal', left)
if __name__ == '__main__': unittest.main()
