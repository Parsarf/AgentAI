import io
import contextlib
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
from agentai_platform.ops import cli
from agentai_platform.store import Store
from tests.test_ops_backup import HAVE_AGE, keypair


@unittest.skipUnless(HAVE_AGE, 'age is not installed')
class EndToEndChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        public, self.identity = keypair(self.root)
        db = self.root / 'app.sqlite3'; Store(db).initialize()
        con = sqlite3.connect(db)
        for a in ('a', 'b'):
            con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,)); con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (a, 'd' + a))
            con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,?)", (a, 'p' + a, 'P' + a)); con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (a, 'p' + a, 'c' + a, 'd' + a))
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content,created_at) VALUES (?,?,?,?,?)", (a, 'c' + a, 'customer', f'hello-{a}', '2026-01-01T00:00:00Z'))
        con.commit(); con.close()
        custody = self.root / 'custody.sqlite3'; con = sqlite3.connect(custody); con.execute('CREATE TABLE bindings(account TEXT, tenant TEXT)'); con.execute("INSERT INTO bindings VALUES ('a','aa-%s')" % ('a1' * 16)); con.commit(); con.close()
        (self.root / 'owner').mkdir(); (self.root / 'cells' / 'a').mkdir(parents=True); (self.root / 'secrets').mkdir(); (self.root / 'secrets' / 'tok').write_text('tenant-token-canary')
        for name, content in (('litellm-20261012.sql', '-- PostgreSQL database dump\n' + 'x' * 3000),):
            (self.root / 'owner' / name).write_text(content)
        with tarfile.open(self.root / 'owner' / 'oc-ops-1.tar.gz', 'w:gz') as t:
            f = self.root / 'f.txt'; f.write_text('owner state'); t.add(f, arcname='state/f.txt')
        with tarfile.open(self.root / 'cells' / 'a' / 'op1.tgz', 'w:gz') as t: t.add(f, arcname='data/x')
        (self.root / 'conf.env').write_text('SECRET_CANARY=1')
        self.cfg_path = self.root / 'config.json'
        self.cfg = {'app_db': str(db), 'custody_db': str(custody), 'tenant_secrets_dir': str(self.root / 'secrets'), 'cell_backup_root': str(self.root / 'cells'),
                    'owner_backup_dir': str(self.root / 'owner'), 'state_dir': str(self.root / 'state'), 'backup_status': str(self.root / 'state' / 'b.json'),
                    'monitor_status': str(self.root / 'state' / 'm.json'), 'alert_state': str(self.root / 'state' / 'a.json'), 'work_root': str(self.root / 'state' / 'work'),
                    'age_recipients': [public], 'destinations': [{'type': 'local', 'path': str(self.root / 'bk'), 'offsite': False}],
                    'config_paths': [str(self.root / 'conf.env')], 'private_paths': []}
        (self.root / 'state').mkdir(mode=0o700); self.cfg_path.write_text(json.dumps(self.cfg))

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): code = cli.main([*args, '--config', str(self.cfg_path)])
        return code, out.getvalue()

    def test_backup_verify_fetch_and_scoped_restore_through_the_real_cli(self):
        code, text = self.run_cli('backup'); report = json.loads(text)
        self.assertEqual((code, report['complete'], report['offsite_copy']), (0, True, False)); self.assertGreaterEqual(report['artifacts'], 7)
        code, text = self.run_cli('verify'); self.assertEqual(code, 0); self.assertEqual(json.loads(text)['size_mismatch'], [])
        # nothing readable on the host side
        blob = b''.join(p.read_bytes() for p in (self.root / 'bk').rglob('*.age'))
        for canary in (b'tenant-token-canary', b'SECRET_CANARY', b'hello-a', b'owner state'): self.assertNotIn(canary, blob)
        out = self.root / 'fetched'
        code, text = self.run_cli('fetch', '--identity', str(self.identity), '--out', str(out)); self.assertEqual(code, 0)
        files = json.loads(text)['files']; self.assertTrue({'app-db', 'custody-db', 'config', 'tenant-secrets', 'owner-state', 'litellm', 'versions'} <= set(files))
        self.assertTrue(any(k.startswith('cell-') for k in files))
        # corrupt live data for account a, then restore it from the set
        con = sqlite3.connect(self.cfg['app_db']); con.execute("DELETE FROM chat_messages WHERE account_id='a'"); con.commit(); con.close()
        live_before = (self.root / 'app.sqlite3').read_bytes()
        code, text = self.run_cli('restore-account', '--identity', str(self.identity), '--account', 'a', '--out', str(self.root / 'rest'))
        report = json.loads(text); self.assertEqual(code, 0); self.assertTrue(report['other_accounts_unchanged'])
        restored = next((self.root / 'rest').glob('restored-*.sqlite3'))
        con = sqlite3.connect(restored); self.assertEqual(con.execute("SELECT content FROM chat_messages WHERE account_id='a'").fetchall(), [('hello-a',)]); con.close()
        self.assertEqual((self.root / 'app.sqlite3').read_bytes(), live_before)

    def test_setup_check_names_every_gap_and_marks_the_launch_blocker(self):
        self.cfg['age_recipients'] = []; self.cfg_path.write_text(json.dumps(self.cfg))
        code, text = self.run_cli('check'); self.assertEqual(code, 1); self.assertIn('no age recipient', text); self.assertIn('LAUNCH BLOCKER', text); self.assertIn('no alert destination', text)

    def test_inventory_and_diagnostics_commands(self):
        code, text = self.run_cli('inventory'); self.assertIn('app-db', text); self.assertIn('encryption-keys', text)
        code, text = self.run_cli('diagnostics'); self.assertNotIn('hello-a', text); self.assertEqual(len(json.loads(text)['accounts']), 2)

    def test_a_failed_source_exits_nonzero_and_still_reports(self):
        (self.root / 'owner' / 'litellm-20261012.sql').unlink()
        code, text = self.run_cli('backup'); self.assertEqual(code, 1); self.assertFalse(json.loads(text.splitlines()[-1])['complete'])
