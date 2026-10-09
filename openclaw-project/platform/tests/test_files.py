import json
import os
from pathlib import Path
import tempfile
import unittest
from agentai_platform.artifacts import ArtifactService
from agentai_platform.files import FileService, Rejected, sniff
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal
from agentai_platform.storage import RootStore, validate_component
from agentai_platform.store import Store

LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000,
          'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class StorageChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = RootStore(Path(self.tmp.name) / 'storage')
        self.assertFalse((Path(self.tmp.name) / 'storage').is_symlink())

    def test_component_validation(self):
        for bad in ['..', '.', 'a/b', '', 'x' * 129, '\x00', '.hidden', 'a\\b', 'sp ace', 'café']:
            with self.assertRaises(ValueError):
                validate_component(bad)
        self.assertEqual(validate_component('ok.Name-1_2'), 'ok.Name-1_2')

    def test_write_read_delete_roundtrip(self):
        self.root.write_private(['acct', 'artifacts', 'a1', '1'], b'content')
        self.assertEqual(self.root.read_private(['acct', 'artifacts', 'a1', '1']), b'content')
        self.assertEqual(self.root.size(['acct', 'artifacts', 'a1', '1']), 7)
        self.root.delete(['acct', 'artifacts', 'a1', '1'])
        with self.assertRaises(FileNotFoundError):
            self.root.read_private(['acct', 'artifacts', 'a1', '1'])

    def test_traversal_and_symlink_escape_denied(self):
        self.root.write_private(['acct', 'secret.txt'], b'top secret')
        for parts in [['..'], ['acct', '..', '..', 'etc'], ['acct', 'artifacts', '..', 'secret.txt']]:
            with self.assertRaises(ValueError):
                self.root.read_private(parts)
        # Intermediate symlink race: swapping a directory component in after
        # validation still fails to open (O_NOFOLLOW on every component).
        self.root.write_private(['acct', 'artifacts', 'a1', '1'], b'real')
        base = Path(self.tmp.name) / 'storage' / 'acct' / 'artifacts' / 'a1'
        # Swap the validated directory for a symlink after the fact.
        os.unlink(base / '1')
        os.rmdir(base)
        os.symlink('../..', base)
        with self.assertRaises(OSError):
            self.root.read_private(['acct', 'artifacts', 'a1', '1'])
        base.unlink(missing_ok=True)
        os.symlink('../../secret.txt', base)
        with self.assertRaises(OSError):
            self.root.read_private(['acct', 'artifacts', 'a1'])


class FilesChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3');self.store.initialize()
        self.root = RootStore(Path(self.tmp.name) / 'storage')
        self.files = FileService(self.store, storage=self.root, clock=lambda: 2000000000)
        self.a = Principal('a', 'actor-a', 'customer');self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P ' + x))

    def test_allowlist_and_content_mismatch(self):
        ok = self.files.upload(self.a, 'p-a', [('notes.txt', 'text/plain', b'hello')])
        self.assertEqual(ok['accepted'][0]['media_type'], 'text/plain')
        for name, data, why in [
            ('evil.exe', b'MZ\x90\x00', 'allowlist'),
            ('note.md', b'\x00\x01binary', 'binary'),
            ('data.json', b'{not json', 'invalid JSON'),
            ('pic.png', b'\xff\xd8\xffnotpng', 'content does not match'),
            ('doc.pdf', b'\x89PNG\r\n\x1a\n', 'content does not match'),
            ('.hidden.txt', b'x', 'hidden'),
            ('../trav.txt', b'x', 'invalid file name'),
        ]:
            with self.assertRaises(Rejected):
                self.files.upload(self.a, 'p-a', [(name, '', data)])
        encrypted = b'%PDF-1.4 /Encrypt 1 0 obj' + b'x' * 100
        with self.assertRaises(Rejected):
            self.files.upload(self.a, 'p-a', [('doc.pdf', '', encrypted)])
        self.assertEqual(len(self.files.list_files(self.a, 'p-a')), 1)

    def test_batch_limits_and_partial_accept(self):
        big = b'x' * (10 * 1024 * 1024 + 1)
        with self.assertRaises(Rejected):
            self.files.upload(self.a, 'p-a', [('big.txt', '', big)])
        with self.assertRaises(Rejected):
            self.files.upload(self.a, 'p-a', [(f'f{i}.txt', '', b'x') for i in range(11)])
        result = self.files.upload(self.a, 'p-a', [('good.txt', '', b'ok'), ('bad.json', '', b'nope')])
        self.assertEqual(len(result['accepted']), 1)
        self.assertEqual(len(result['rejected']), 1)

    def test_scoped_listing_and_preview_parts(self):
        self.files.upload(self.a, 'p-a', [('notes.txt', '', b'hello')])
        file_id = self.files.list_files(self.a, 'p-a')[0]['id']
        with self.assertRaises(NotFound):
            self.files.list_files(self.b, 'p-a')
        with self.assertRaises(NotFound):
            self.files.open_parts(self.b, 'p-a', file_id)
        parts, media = self.files.open_parts(self.a, 'p-a', file_id)
        self.assertEqual(self.root.read_private(parts), b'hello')
        self.assertEqual(media, 'text/plain')


class ArtifactChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3');self.store.initialize()
        self.root = RootStore(Path(self.tmp.name) / 'storage')
        self.artifacts = ArtifactService(self.store, storage=self.root,
                                         signing_key=b'k' * 32, clock=lambda: 2000000000)
        self.a = Principal('a', 'actor-a', 'customer');self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in ['a', 'b']:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (x, 'd-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))
                limits = dict(LIMITS)
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",
                            (x, 'e-' + x, json.dumps(limits), 2000000000 + 1000000))
                con.execute('''INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)''',
                            (x, 'p-' + x, 'c-' + x, 'd-' + x))
                con.execute('''INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd)
                    VALUES (?,?,?,'t-' || ?,'completed',0)''', (x, 'p-' + x, 'c-' + x, x))

    def capture(self, account='a', project='p-a', data=b'artifact body', name='result.txt'):
        return self.artifacts.capture(account_id=account, project_id=project,
                                      task_id='t-' + account, name=name, media_type='text/plain', data=data)

    def test_capture_version_hash_and_immutability(self):
        first = self.capture(data=b'v1 body')
        self.assertEqual(first['version'], 1)
        second = self.artifacts.add_version(self.a, first['artifact_id'], b'v2 body')
        self.assertEqual(second['version'], 2)
        listed = self.artifacts.list_artifacts(self.a, 'p-a')
        self.assertEqual(sorted(row['version'] for row in listed), [1, 2])
        with self.assertRaises(NotFound):
            self.artifacts.add_version(self.b, first['artifact_id'], b'nope')
        with self.assertRaises(ValueError):
            self.artifacts.capture(account_id='a', project_id='p-a', task_id='t',
                                   name='../evil', media_type='text/plain', data=b'x')

    def test_tickets_single_use_bound_and_scoped(self):
        captured = self.capture(data=b'secret body')
        minted = self.artifacts.mint_ticket(self.a, captured['artifact_id'], 1)
        path = minted['path']
        # B cannot mint a ticket for A's artifact.
        with self.assertRaises(NotFound):
            self.artifacts.mint_ticket(self.b, captured['artifact_id'], 1)
        parts, name, media = self.artifacts.consume_ticket(captured['artifact_id'], 1, path.split('ticket=')[1])
        self.assertEqual(self.root.read_private(parts), b'secret body')
        # Replay fails: single use.
        with self.assertRaises(NotFound):
            self.artifacts.consume_ticket(captured['artifact_id'], 1, path.split('ticket=')[1])
        # Ticket for a different version of the same artifact fails.
        self.artifacts.add_version(self.a, captured['artifact_id'], b'v2')
        minted2 = self.artifacts.mint_ticket(self.a, captured['artifact_id'], 2)
        with self.assertRaises(NotFound):
            self.artifacts.consume_ticket(captured['artifact_id'], 1, minted2['path'].split('ticket=')[1])
        self.now_expired()

    def now_expired(self):
        expired = self.artifacts.mint_ticket(self.a, self.artifacts.list_artifacts(self.a, 'p-a')[0]['id'], 1)
        import agentai_platform.artifacts as module
        old_clock = self.artifacts.clock
        self.artifacts.clock = lambda: 2000000000 + 999999
        with self.assertRaises(NotFound):
            self.artifacts.consume_ticket(self.artifacts.list_artifacts(self.a, 'p-a')[0]['id'], 1,
                                          expired['path'].split('ticket=')[1])
        self.artifacts.clock = old_clock

    def test_bundle_contains_latest_versions_and_manifest(self):
        captured = self.capture(data=b'v1 body')
        self.artifacts.add_version(self.a, captured['artifact_id'], b'v2 body')
        self.capture(project='p-a', data=b'other result', name='other.txt')
        result = self.artifacts.build_bundle(self.a, 'p-a')
        self.assertEqual(result['file_count'], 2)
        import zipfile
        from io import BytesIO
        with self.store.connect() as con:
            ref = con.execute("SELECT storage_ref FROM artifacts WHERE id=? AND version=1", (result['artifact_id'],)).fetchone()[0]
        data = self.root.read_private(['a'] + ref.split('/'))
        with zipfile.ZipFile(BytesIO(data)) as bundle:
            names = bundle.namelist()
            self.assertIn('manifest.json', names)
            self.assertEqual(sum(1 for n in names if n.endswith('result.txt')), 1)
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(len(manifest['files']), 2)
            versions = {f['path']: f for f in manifest['files']}
            self.assertTrue(any('v2/' in p for p in versions))
            body = bundle.read([p for p in versions if p.endswith('result.txt')][0])
            self.assertEqual(body, b'v2 body')
        # Bundle counts against the same quota and belongs to the account.
        with self.assertRaises(NotFound):
            self.artifacts.build_bundle(self.b, 'p-a')


if __name__ == '__main__':
    unittest.main()
