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
