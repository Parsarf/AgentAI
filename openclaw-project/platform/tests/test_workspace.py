import os
import tempfile
import time
import unittest
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

    def test_symlinks_never_followed(self):
        os.symlink(self.outside, self.ws / 'link.txt')
        os.symlink(self.tmp.name, self.ws / 'dirlink')
        (self.ws / 'ok.txt').write_text('fine')
        got = dict(collect(self.ws, 0))
        self.assertEqual(list(got), ['ok.txt'])
        self.assertNotIn(b'TOP SECRET', b''.join(got.values()))

    def test_bounds(self):
        for i in range(15):
            (self.ws / f'f{i:02}.txt').write_text('x' * 10)
        (self.ws / 'big.txt').write_bytes(b'x' * (3 * 1024 * 1024))
        got = collect(self.ws, 0)
        self.assertLessEqual(len(got), 10)
        self.assertNotIn('big.txt', dict(got))

    def test_missing_workspace_or_symlinked_root(self):
        self.assertEqual(collect(Path(self.tmp.name) / 'nope', 0), [])
        os.symlink(self.ws, Path(self.tmp.name) / 'wslink')
        (self.ws / 'a.txt').write_text('a')
        self.assertEqual(collect(Path(self.tmp.name) / 'wslink', 0), [])


if __name__ == '__main__':
    unittest.main()
