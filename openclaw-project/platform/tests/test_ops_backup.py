import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import unittest
from agentai_platform.ops.backup import (BackupJob, BackupError, files_source, latest_file_source, select_keep, sqlite_source,
    tenant_hash, Source, verify_pgdump, verify_sqlite, verify_tar)
from agentai_platform.ops.crypto import AgeCrypto, CryptoError
from agentai_platform.ops.destinations import CommandDestination, DestinationError, LocalDir

HAVE_AGE = shutil.which('age') and shutil.which('age-keygen')
T1, T2 = 'aa-' + 'a1' * 16, 'aa-' + 'b2' * 16


def keypair(directory):
    identity = Path(directory) / 'identity.txt'
    out = subprocess.run(['age-keygen', '-o', str(identity)], capture_output=True, text=True)
    public = [w for w in out.stderr.split() if w.startswith('age1')][0]
    return public, identity


@unittest.skipUnless(HAVE_AGE, 'age is not installed')
class BackupKit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.public, self.identity = keypair(self.root)
        self.crypto = AgeCrypto([self.public])
        self.now = 2_000_000_000
        self.dest = LocalDir(self.root / 'backups')
        db = sqlite3.connect(self.root / 'app.db'); db.execute('CREATE TABLE t(x)'); db.execute("INSERT INTO t VALUES ('canary-secret-value')"); db.commit(); db.close()
        (self.root / 'conf').mkdir(); (self.root / 'conf' / 'a.env').write_text('TOKEN=canary-token-value\n')
        (self.root / 'dump').mkdir(); (self.root / 'dump' / 'litellm-1.sql').write_text('-- PostgreSQL database dump\n' + 'x' * 2000)
        os.utime(self.root / 'dump' / 'litellm-1.sql', (self.now - 100, self.now - 100))
        for ref in (T1, T2):
            with tarfile.open(self.root / f'{ref}.tgz', 'w:gz') as t:
                data = self.root / f'{ref}.dat'; data.write_text('tenant-' + ref); t.add(data, arcname='data/x')
        self.alerts = []

    def job(self, sources=None, dests=None, **kw):
        sources = sources if sources is not None else [
            sqlite_source('app-db', self.root / 'app.db', asset='app-db'),
            files_source('config', [self.root / 'conf' / 'a.env', self.root / 'conf' / 'missing.env'], asset='config'),
            latest_file_source('litellm', self.root / 'dump', 'litellm-*.sql', 'pgdump', 86400, clock=lambda: self.now, asset='litellm'),
            *[Source(f'cell-{i}', 'tar', (lambda w, ref=ref, i=i: shutil.copyfile(self.root / f'{ref}.tgz', w / f'cell-{i}.tar.gz') and (w / f'cell-{i}.tar.gz')),
                     tenant=ref, asset='tenant-cells') for i, ref in enumerate((T1, T2))]]
        return BackupJob(sources, self.crypto, dests or [self.dest], work_root=self.root / 'work', status_path=self.root / 'status.json',
                         clock=lambda: self.now, alert=lambda kind, report: self.alerts.append((kind, report)),
                         expected_assets=kw.pop('expected_assets', ('app-db', 'config', 'litellm', 'tenant-cells')), **kw)



@unittest.skipUnless(HAVE_AGE, 'age is not installed')
class BackupChecks(BackupKit):
    def test_complete_set_is_encrypted_verified_and_leaves_no_plain_copy(self):
        report = self.job().run()
        self.assertTrue(report['complete'], report); self.assertEqual(report['artifacts'], 5); self.assertFalse(report['offsite_copy'])
        self.assertEqual(list((self.root / 'work').iterdir()), [])                      # work dir cleaned
        listing = [n for n, _, _ in self.dest.list()]
        manifest = json.loads(self.dest.read(f"sets/{report['set_id']}/manifest.json"))
        for art in manifest['artifacts']:
            data = self.dest.read(f"sets/{report['set_id']}/{art['name']}")
            self.assertTrue(data.startswith(b'age-encryption.org/v1')); self.assertNotIn(b'canary', data)
            self.assertEqual(oct(os.stat(self.dest.root / 'sets' / report['set_id'] / art['name']).st_mode & 0o777), '0o600')
        status = json.loads((self.root / 'status.json').read_text())
        self.assertEqual((status['last_complete'], status['last_success_set'], status['offsite_copy']), (True, report['set_id'], False))
        self.assertEqual(self.alerts, [])

    def test_round_trip_through_the_owners_private_key_matches_the_recorded_hashes(self):
        report = self.job().run(); manifest = json.loads(self.dest.read(f"sets/{report['set_id']}/manifest.json"))
        art = next(a for a in manifest['artifacts'] if a['source'] == 'app-db')
        out = self.root / 'restored.sqlite3'
        AgeCrypto([self.public]).decrypt(self.dest.root / 'sets' / report['set_id'] / art['name'], out, self.identity)
        from agentai_platform.ops.backup import sha256_file
        self.assertEqual(sha256_file(out), art['plain_sha256']); verify_sqlite(out)
        self.assertEqual(sqlite3.connect(out).execute('SELECT x FROM t').fetchone()[0], 'canary-secret-value')

    def test_a_wrong_key_cannot_read_and_a_damaged_file_is_rejected(self):
        report = self.job().run(); sid = report['set_id']
        art = json.loads(self.dest.read(f'sets/{sid}/manifest.json'))['artifacts'][0]
        path = self.dest.root / 'sets' / sid / art['name']
        stranger = self.root / 'stranger'; stranger.mkdir(); _, wrong_identity = keypair(stranger)
        with self.assertRaises(CryptoError): self.crypto.decrypt(path, self.root / 'x1', wrong_identity)
        damaged = self.root / 'damaged.age'; blob = bytearray(path.read_bytes()); blob[len(blob) // 2] ^= 0xFF; damaged.write_bytes(bytes(blob))
        with self.assertRaises(CryptoError): self.crypto.decrypt(damaged, self.root / 'x2', self.identity)

    def test_tenant_manifests_are_separate_and_never_carry_tenant_references(self):
        report = self.job().run(); sid = report['set_id']
        text = '\n'.join(self.dest.read(n).decode() for n, _, _ in self.dest.list() if n.endswith('.json'))
        self.assertNotIn(T1, text); self.assertNotIn(T2, text)
        t1 = json.loads(self.dest.read(f'sets/{sid}/tenant-{tenant_hash(T1)}.manifest.json'))
        self.assertEqual({a['tenant'] for a in t1['artifacts']}, {tenant_hash(T1)}); self.assertEqual(len(t1['artifacts']), 1)

    def test_one_bad_source_makes_the_set_incomplete_and_alerts_without_losing_the_rest(self):
        (self.root / 'bad.db').write_text('not a database')
        sources = [sqlite_source('app-db', self.root / 'app.db', asset='app-db'), sqlite_source('broken', self.root / 'bad.db', asset='x')]
        ok = self.job(sources, expected_assets=('app-db',)).run(); self.assertFalse(ok['complete'])
        self.assertEqual(ok['failures'][0]['source'], 'broken'); self.assertEqual(self.alerts[0][0], 'backup_failed')
        status = json.loads((self.root / 'status.json').read_text()); self.assertFalse(status['last_complete']); self.assertIsNone(status['last_success_epoch'])

    def test_stale_inputs_and_uncovered_assets_are_failures_not_silent_gaps(self):
        os.utime(self.root / 'dump' / 'litellm-1.sql', (self.now - 90000, self.now - 90000))
        report = self.job().run(); self.assertFalse(report['complete']); self.assertIn('StaleSource', report['failures'][0]['error'])
        short = self.job([sqlite_source('app-db', self.root / 'app.db', asset='app-db')]).run()
        self.assertFalse(short['complete']); self.assertEqual(short['missing_assets'], ['config', 'litellm', 'tenant-cells'])

    def test_a_failed_run_never_prunes_older_good_sets(self):
        self.job().run(); good = [n for n, _, _ in self.dest.list()]
        self.now += 86400 * 30
        os.utime(self.root / 'dump' / 'litellm-1.sql', (self.now - 10, self.now - 10))
        (self.root / 'app.db').write_bytes(b'broken')
        self.job().run()
        self.assertTrue(set(good) <= {n for n, _, _ in self.dest.list()})

    def test_offsite_flag_follows_a_successful_offsite_destination_only(self):
        sent = []
        def run(argv): sent.append(argv); return subprocess.CompletedProcess(argv, 0, stdout=b'', stderr=b'')
        class Remote(CommandDestination):
            def __init__(s): super().__init__(['rclone', 'copyto', '{src}', 'remote:{name}'], ['rclone', 'lsf', '{prefix}'], ['rclone', 'deletefile', '{name}'], run=run); s.store = {}
            def put(s, src, name): s.store[name] = Path(src).stat().st_size; return s.store[name]
            def size(s, name): return s.store.get(name)
            def list(s, prefix=''): return [(n, v, 0) for n, v in s.store.items() if n.startswith(prefix)]
            def remove(s, name): s.store.pop(name, None)
        remote = Remote()
        report = self.job(dests=[self.dest, remote]).run(); self.assertTrue(report['offsite_copy']); self.assertTrue(report['complete'])
        broken = Remote(); broken.put = lambda *a: (_ for _ in ()).throw(RuntimeError('network'))
        self.now += 100; os.utime(self.root / 'dump' / 'litellm-1.sql', (self.now - 10, self.now - 10))
        report = self.job(dests=[self.dest, broken]).run(); self.assertFalse(report['offsite_copy']); self.assertFalse(report['complete'])
        self.assertEqual(self.alerts[-1][0], 'backup_failed')


class RetentionChecks(unittest.TestCase):
    def ids(self, days, step=86400, base=2_000_000_000):
        return [time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(base - i * step)) for i in range(days)]
    def test_bounded_and_always_keeps_the_newest(self):
        ids = self.ids(400); keep = select_keep(ids, 2_000_000_000)
        self.assertIn(ids[0], keep); self.assertLessEqual(len(keep), 14 + 8 + 6 + 1); self.assertGreaterEqual(len(keep), 14)
        self.assertTrue(set(ids[:14]) <= keep)
    def test_few_sets_are_all_kept_and_empty_is_safe(self):
        ids = self.ids(5); self.assertEqual(select_keep(ids, 2_000_000_000), set(ids)); self.assertEqual(select_keep([], 0), set())
    def test_pruning_removes_only_old_set_directories_and_leaves_other_files(self):
        with tempfile.TemporaryDirectory() as d:
            dest = LocalDir(Path(d) / 'b')
            dest.put(__file__, 'notes/keep-me.txt'); dest.put(__file__, 'sets/not-a-set/file')
            for sid in self.ids(30):
                dest.put(__file__, f'sets/{sid}/x.age'); dest.put(__file__, f'sets/{sid}/manifest.json')
            job = BackupJob([], None, [dest], work_root=Path(d) / 'w', status_path=Path(d) / 's.json', clock=lambda: 2_000_000_000)
            job._prune()
            names = {n for n, _, _ in dest.list()}
            self.assertIn('notes/keep-me.txt', names); self.assertIn('sets/not-a-set/file', names)
            kept = {n.split('/')[1] for n in names if n.startswith('sets/') and n.split('/')[1][0].isdigit()}
            self.assertIn(self.ids(30)[0], kept); self.assertLessEqual(len(kept), 14 + 8 + 6 + 1); self.assertLess(len(kept), 30)


class DestinationChecks(unittest.TestCase):
    def test_names_cannot_escape_the_root_and_partial_objects_are_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            dest = LocalDir(Path(d) / 'b')
            for bad in ('../x', '/etc/x', 'a/../../x', '', 'a b', '.hidden', 'a//b'):
                with self.assertRaises(DestinationError): dest.put(__file__, bad)
            (dest.root / 'sets').mkdir(); (dest.root / 'sets' / 'half.age.partial').write_bytes(b'x')
            self.assertEqual(dest.list(), [])
    def test_root_must_be_private(self):
        with tempfile.TemporaryDirectory() as d:
            os.chmod(d, 0o755)
            with self.assertRaises(DestinationError): LocalDir(d)
    def test_command_destination_uses_argv_not_a_shell(self):
        calls = []
        def run(argv): calls.append(argv); return subprocess.CompletedProcess(argv, 0, stdout=b'sets/a/x.age\t12\t5\n', stderr=b'')
        dest = CommandDestination(['cp', '{src}', '/r/{name}'], ['ls', '{prefix}'], ['rm', '/r/{name}'], run=run)
        dest.put(__file__, 'sets/a/x.age'); self.assertEqual(calls[-1][0], 'cp'); self.assertEqual(dest.list('sets/'), [('sets/a/x.age', 12, 5)])
        with self.assertRaises(DestinationError): dest.put(__file__, 'a; rm -rf /')
        with self.assertRaises(DestinationError): CommandDestination('cp {src}', ['x'], ['y'])


class CryptoChecks(unittest.TestCase):
    def test_recipients_are_validated_and_overwrite_is_refused(self):
        for bad in ([], ['not-a-key'], ['AGE-SECRET-KEY-1' + 'A' * 50], None):
            with self.assertRaises(CryptoError): AgeCrypto(bad)
    @unittest.skipUnless(HAVE_AGE, 'age is not installed')
    def test_encrypt_refuses_to_overwrite_and_verifies_the_header(self):
        with tempfile.TemporaryDirectory() as d:
            public, _ = keypair(d); crypto = AgeCrypto([public]); src = Path(d) / 's'; src.write_bytes(b'hello' * 100)
            out = crypto.encrypt(src, Path(d) / 's.age'); self.assertTrue(AgeCrypto.looks_encrypted(out))
            with self.assertRaises(CryptoError): crypto.encrypt(src, out)
            self.assertFalse(AgeCrypto.looks_encrypted(src))


class VerifierChecks(unittest.TestCase):
    def test_verifiers_reject_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            junk = Path(d) / 'j'; junk.write_bytes(b'junk' * 500)
            for fn in (verify_sqlite, verify_tar, verify_pgdump):
                with self.assertRaises(Exception): fn(junk)
if __name__ == '__main__': unittest.main()


from agentai_platform.ops.sets import SetError, fetch, load_manifest, newest_complete


@unittest.skipUnless(HAVE_AGE, 'age is not installed')
class SetRetrievalChecks(BackupKit):
    def setUp(self):
        super().setUp(); self.report = self.job().run(); self.sid = self.report['set_id']
        self.out = self.root / 'restore-work'

    def test_clean_set_decrypts_and_verifies_every_artifact(self):
        manifest, got = fetch(self.dest, self.sid, self.identity, self.out)
        self.assertEqual(set(got), {'app-db', 'config', 'litellm', 'cell-0', 'cell-1'}); self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted(p.name for p in got.values()))
        self.assertEqual(newest_complete(self.dest), self.sid)
        _, only = fetch(self.dest, self.sid, self.identity, self.root / 'one', only={'app-db'}); self.assertEqual(set(only), {'app-db'})

    def test_every_kind_of_damage_is_rejected_with_a_reason_and_no_plain_output(self):
        art = next(a for a in load_manifest(self.dest, self.sid)['artifacts'] if a['source'] == 'app-db')
        path = self.dest.root / 'sets' / self.sid / art['name']; original = path.read_bytes()
        path.write_bytes(original[:-10] + b'X' * 10)                                        # same size, flipped tail
        with self.assertRaises(SetError) as e: fetch(self.dest, self.sid, self.identity, self.root / 'o1', only={'app-db'})
        self.assertIn('damaged', str(e.exception))
        path.write_bytes(original[:-5])                                                     # truncated
        with self.assertRaises(SetError) as e: fetch(self.dest, self.sid, self.identity, self.root / 'o2', only={'app-db'})
        self.assertIn('size', str(e.exception))
        path.unlink()
        with self.assertRaises(SetError) as e: fetch(self.dest, self.sid, self.identity, self.root / 'o3', only={'app-db'})
        self.assertIn('missing', str(e.exception))
        path.write_bytes(original)
        for out in ('o1', 'o2', 'o3'):
            self.assertEqual(list((self.root / out).glob('*')) if (self.root / out).exists() else [], [])
        fetch(self.dest, self.sid, self.identity, self.root / 'o4', only={'app-db'})         # restored original passes again

    def test_wrong_key_incomplete_sets_and_forged_manifests_are_refused(self):
        stranger = self.root / 'stranger'; stranger.mkdir(); _, wrong = keypair(stranger)
        with self.assertRaises(SetError): fetch(self.dest, self.sid, wrong, self.root / 'o5')
        manifest_path = self.dest.root / 'sets' / self.sid / 'manifest.json'; manifest = json.loads(manifest_path.read_text())
        manifest['complete'] = False; manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(SetError): fetch(self.dest, self.sid, self.identity, self.root / 'o6')
        self.assertIsNone(newest_complete(self.dest))
        manifest['complete'] = True; manifest['set_id'] = '20200101T000000Z'; manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(SetError): load_manifest(self.dest, self.sid)
        with self.assertRaises(SetError): load_manifest(self.dest, '../etc')
        manifest_path.unlink()
        with self.assertRaises(SetError): load_manifest(self.dest, self.sid)

    def test_a_manifest_edit_that_hides_damage_is_caught_by_the_plain_hash(self):
        manifest_path = self.dest.root / 'sets' / self.sid / 'manifest.json'; manifest = json.loads(manifest_path.read_text())
        art = next(a for a in manifest['artifacts'] if a['source'] == 'config'); art['plain_sha256'] = '0' * 64; manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(SetError) as e: fetch(self.dest, self.sid, self.identity, self.root / 'o7', only={'config'})
        self.assertIn('differs', str(e.exception))
