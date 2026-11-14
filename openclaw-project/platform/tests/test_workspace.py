import os
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
from agentai_platform.lifecycle.workspace import collect


class WorkspaceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / 'workspace'; self.ws.mkdir()
        self.outside = Path(self.tmp.name) / 'secret.txt'; self.outside.write_text('TOP SECRET')

    def test_collects_new_allowlisted_files_only(self):
        (self.ws / 'slug.py').write_text('print(1)')
        (self.ws / 'sub').mkdir(); (self.ws / 'sub' / 'page.html').write_text('<p>hi</p>')
        (self.ws / 'AGENTS.md').write_text('rules'); (self.ws / '.search-1').write_text('x')
        (self.ws / 'bin.exe').write_bytes(b'MZ'); (self.ws / 'node_modules').mkdir(); (self.ws / 'node_modules' / 'a.js').write_text('x')
        old = self.ws / 'old.txt'; old.write_text('old'); os.utime(old, (1, 1))
        got = dict(collect(self.ws, time.time() - 60))
        self.assertEqual(sorted(got), ['slug.py', 'sub/page.html'])

    def test_the_runtimes_own_seeded_files_are_not_deliverables(self):
        for name in ('AGENTS.md', 'SOUL.md', 'USER.md', 'IDENTITY.md', 'BOOTSTRAP.md', 'TOOLS.md', 'HEARTBEAT.md', 'MEMORY.md'):
            (self.ws / name).write_text('the runtime wrote this')
        (self.ws / 'memory').mkdir(); (self.ws / 'memory' / '2026-10-26.md').write_text('daily log')
        (self.ws / 'report.md').write_text('the customer asked for this')
        self.assertEqual(sorted(dict(collect(self.ws, 0))), ['report.md'])

    def test_symlinks_never_followed(self):
        os.symlink(self.outside, self.ws / 'link.txt')
        os.symlink(self.tmp.name, self.ws / 'dirlink')
        (self.ws / 'ok.txt').write_text('fine')
        got = dict(collect(self.ws, 0))
        self.assertEqual(list(got), ['ok.txt'])
        self.assertNotIn(b'TOP SECRET', b''.join(got.values()))

    def test_bounds(self):
        from agentai_platform.lifecycle import workspace as ws
        for i in range(60):
            (self.ws / f'f{i:02}.txt').write_text('x' * 10)
        found = ws.scan(self.ws, 0)
        self.assertEqual(len(found['files']), 50)
        self.assertEqual({s['reason'] for s in found['skipped']}, {'more than 50 files in one task'})
        with mock.patch.object(ws, 'MAX_FILE_BYTES', 1024):
            (self.ws / 'big.bin').write_bytes(b'x' * 2048)
            found = ws.scan(self.ws, 0)
            self.assertIn({'path': 'big.bin', 'reason': 'larger than 50 MB'}, found['skipped'])
            self.assertIsNone(ws.read(self.ws, 'big.bin'))
            self.assertEqual(ws.stat_file(self.ws, 'big.bin'), {'reason': 'larger than 50 MB'})
        self.assertLessEqual(sum(len(d) for _, d in collect(self.ws, 0, max_total=100)), 100)

    def test_any_format_is_kept_but_never_a_program_or_working_leftovers(self):
        from agentai_platform.lifecycle import workspace as ws
        (self.ws / 'Q3 sales.xlsx').write_bytes(b'PK\x03\x04 sheet'); (self.ws / 'deck.pptx').write_bytes(b'PK\x03\x04 deck')
        (self.ws / 'movie.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42'); (self.ws / 'invite.ics').write_text('BEGIN:VCALENDAR')
        (self.ws / 'tool.exe').write_bytes(b'MZ\x90\x00'); (self.ws / 'renamed.pdf').write_bytes(b'\x7fELF\x02\x01')     # a program is found by its first bytes too
        (self.ws / 'run.log').write_text('noise'); (self.ws / 'tmp').mkdir(); (self.ws / 'tmp' / 'draft.md').write_text('working notes')
        found = ws.scan(self.ws, 0)
        self.assertEqual(sorted(f['path'] for f in found['files']), ['Q3 sales.xlsx', 'deck.pptx', 'invite.ics', 'movie.mp4'])
        self.assertEqual(sorted(s['path'] for s in found['skipped']), ['renamed.pdf', 'tool.exe'])
        self.assertEqual(ws.stat_file(self.ws, 'tool.exe'), {'reason': 'programs and installers are not delivered'})
        self.assertIsNone(ws.read(self.ws, 'renamed.pdf'))
        self.assertIsNone(ws.safe_path('tmp/draft.md'))

    def test_one_file_is_read_in_slices_and_only_from_inside_the_workspace(self):
        from agentai_platform.lifecycle import workspace as ws
        (self.ws / 'out').mkdir(); (self.ws / 'out' / 'data.csv').write_bytes(b'a,b\n1,2\n')
        self.assertEqual(ws.stat_file(self.ws, 'out/data.csv')['size'], 8)
        self.assertEqual(ws.read(self.ws, 'out/data.csv', 0, 4) + ws.read(self.ws, 'out/data.csv', 4, 4), b'a,b\n1,2\n')
        os.symlink(self.outside, self.ws / 'link.txt'); os.symlink(self.tmp.name, self.ws / 'up')
        for path in ('../secret.txt', '/etc/passwd', 'link.txt', 'up/secret.txt', 'out/../../secret.txt', '.hidden', 'AGENTS.md', 'a\\b', ''):
            self.assertIsNone(ws.read(self.ws, path), path)
            self.assertIn('reason', ws.stat_file(self.ws, path), path)

    def test_missing_workspace_or_symlinked_root(self):
        self.assertEqual(collect(Path(self.tmp.name) / 'nope', 0), [])
        os.symlink(self.ws, Path(self.tmp.name) / 'wslink')
        (self.ws / 'a.txt').write_text('a')
        self.assertEqual(collect(Path(self.tmp.name) / 'wslink', 0), [])


if __name__ == '__main__':
    unittest.main()
