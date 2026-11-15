import importlib.machinery
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'deploy' / 'agentai-deploy'
loader = importlib.machinery.SourceFileLoader('agentai_deploy', str(PATH))
spec = importlib.util.spec_from_loader('agentai_deploy', loader)
deploy = importlib.util.module_from_spec(spec)
loader.exec_module(deploy)
SHA = 'a' * 40


def archive(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == 'file':
                info.size = len(data); tar.addfile(info, io.BytesIO(data))
            elif kind == 'link':
                info.type = tarfile.SYMTYPE; info.linkname = data; tar.addfile(info)
            elif kind == 'dir':
                info.type = tarfile.DIRTYPE; tar.addfile(info)
    return buf.getvalue()


class Command(unittest.TestCase):
    def test_only_the_two_exact_forms_are_accepted(self):
        self.assertEqual(deploy.parse_command(f'deploy {SHA}'), ('deploy', SHA))
        self.assertEqual(deploy.parse_command(f'deploy-dry {SHA}'), ('deploy-dry', SHA))
        for bad in ('', None, 'bash', f'deploy {SHA}; id', f'deploy {SHA} extra', f'deploy {SHA[:39]}', f'deploy {"A" * 40}', f'deploy ../{SHA}',
                    f'deploy {SHA}\nid', f' deploy {SHA}', f'rm -rf / {SHA}', 'deploy $(id)'):
            self.assertIsNone(deploy.parse_command(bad), bad)


class Archive(unittest.TestCase):
    def test_normal_files_are_unpacked(self):
        with tempfile.TemporaryDirectory() as d:
            deploy.safe_extract(archive([('a/b.txt', b'hi', 'file'), ('c', None, 'dir')]), d)
            self.assertEqual((Path(d) / 'a/b.txt').read_bytes(), b'hi')

    def test_anything_that_could_escape_the_folder_is_refused(self):
        for entries in ([('../evil', b'x', 'file')], [('/etc/evil', b'x', 'file')], [('a/../../evil', b'x', 'file')], [('link', '/etc', 'link')], [('l', '../x', 'link')]):
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError, msg=entries[0][0]):
                    deploy.safe_extract(archive(entries), d)
                self.assertEqual(list(Path(d).iterdir()), [])

    def test_an_oversized_upload_is_refused(self):
        with self.assertRaises(ValueError):
            deploy.read_stream(io.BytesIO(b'0' * (deploy.MAX_BYTES + 1)))


class Drift(unittest.TestCase):
    def tree(self, root, name, recorded):
        d = Path(root) / name / 'current'; d.mkdir(parents=True)
        import json
        (d / 'RELEASE.json').write_text(json.dumps({'source_sha256': recorded}))
        return Path(root) / name

    def test_files_released_by_hand_must_be_in_the_incoming_code_unchanged(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'a').mkdir(parents=True)
            (plat / 'a/same.py').write_text('1'); (plat / 'a/changed.py').write_text('NEW')
            h = lambda t: hashlib.sha256(t.encode()).hexdigest()
            app = self.tree(root, 'app', {'a/same.py': h('1'), 'a/changed.py': h('OLD'), 'a/gone.py': h('x'), '../evil': h('x')})
            sup = self.tree(root, 'sup', {'a/same.py': h('1')})
            self.assertEqual(deploy.drift([app, sup], plat), ['app: a/changed.py', 'app: a/gone.py'])
            self.assertEqual(deploy.drift([sup], plat), [])

    def test_a_finished_deploy_forgets_the_manual_record_so_later_commits_are_not_refused(self):
        import hashlib, json
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'a').mkdir(parents=True); (plat / 'a/file.py').write_text('COMMITTED')
            app = self.tree(root, 'app', {'a/file.py': hashlib.sha256(b'HAND MADE').hexdigest()})
            record = app / 'current' / 'RELEASE.json'
            record.write_text(json.dumps({'source_sha256': json.loads(record.read_text())['source_sha256'], 'commit': 'abc', 'purpose': 'kept'}))
            self.assertEqual(deploy.drift([app], plat), ['app: a/file.py'])            # before: the hand-made file would be undone
            deploy.forget_manual([app, Path(root) / 'missing'])
            self.assertEqual(json.loads(record.read_text()), {'commit': 'abc', 'purpose': 'kept'})
            (plat / 'a/file.py').write_text('A LATER COMMIT')
            self.assertEqual(deploy.drift([app], plat), [])                            # after: a later change to the same file is an ordinary change

    def test_a_tree_without_a_record_has_no_drift(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(deploy.drift([Path(root) / 'nothing'], root), [])


class SelfInstall(unittest.TestCase):
    def test_the_installed_program_follows_the_deployed_commit(self):
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'deploy').mkdir(parents=True)
            installed = Path(root) / 'sbin' / 'agentai-deploy'; installed.parent.mkdir()
            installed.write_text('#!/usr/bin/env python3\nold = 1\n')
            (plat / 'deploy' / 'agentai-deploy').write_text('#!/usr/bin/env python3\nnew = 2\n')
            self.assertTrue(deploy.install_self(plat, installed))
            self.assertIn('new = 2', installed.read_text())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
            self.assertFalse(deploy.install_self(plat, installed))                     # already the same: nothing to do
            self.assertEqual([p.name for p in installed.parent.iterdir()], ['agentai-deploy'])      # no temporary file left behind

    def test_a_program_that_does_not_parse_or_is_missing_is_never_installed(self):
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'deploy').mkdir(parents=True)
            installed = Path(root) / 'agentai-deploy'; installed.write_text('#!/usr/bin/env python3\nold = 1\n')
            self.assertFalse(deploy.install_self(plat, installed))                     # the commit has no deploy program
            for bad in ('#!/usr/bin/env python3\ndef broken(:\n', 'not a script\n'):
                (plat / 'deploy' / 'agentai-deploy').write_text(bad)
                self.assertFalse(deploy.install_self(plat, installed), bad)
                self.assertIn('old = 1', installed.read_text())

    def test_the_lifecycle_worker_is_restarted_with_the_other_services_and_the_supervisor_is_not(self):
        self.assertIn('agentai-lifecycle-worker', deploy.UNITS)
        self.assertNotIn('agentai-supervisor-native', deploy.UNITS)


class Layout(unittest.TestCase):
    def test_the_required_paths_exist_in_the_repository(self):
        platform = Path(__file__).resolve().parents[1]
        for name in deploy.REQUIRED:
            self.assertTrue((platform / name).exists(), name)
        self.assertTrue((platform / deploy.RELEASE_PY).is_file())

    def test_the_restart_list_is_services_that_exist(self):
        platform = Path(__file__).resolve().parents[1]
        for unit in deploy.UNITS:
            self.assertTrue((platform / 'deploy' / f'{unit}.service').is_file(), unit)


if __name__ == '__main__':
    unittest.main()
