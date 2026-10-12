import os
from pathlib import Path
import tempfile
import unittest
from agentai_platform.lifecycle.secrets_custody import ProviderKeys, SecretStore
from agentai_platform.ops.rotation import (RotationError, add_webhook_secret, drop_old_webhook_secrets, retry_pending_revocations,
                                           rotate_provider_key, rotate_session_secret)
T = 'aa-' + 'a1' * 16


class RotationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.store = SecretStore(self.root / 'sec'); self.calls, self.fail_delete, self.n = [], False, 0
        def http(method, path, body):
            self.calls.append((path, body))
            if path == '/key/generate': self.n += 1; return 200, {'key': 'sk-' + str(self.n) * 30}
            return (500, {}) if self.fail_delete else (200, {})
        self.keys = ProviderKeys(http, self.store)
        self.keys.issue(T, 'acct', max_budget_usd=25, duration_days=30, models=['m'])
    def rotate(self): return rotate_provider_key(self.keys, self.store, T, 'acct', max_budget_usd=25, duration_days=30, models=['m'], pending_path=self.root / 'pending.json')
    def test_new_key_is_stored_before_the_old_one_is_revoked(self):
        old = self.store.provider_key(T); result = self.rotate()
        self.assertEqual(result, {'rotated': True, 'old_key_revoked': True}); self.assertNotEqual(self.store.provider_key(T), old)
        self.assertEqual([c[0] for c in self.calls][-2:], ['/key/generate', '/key/delete']); self.assertEqual(self.calls[-1][1]['keys'], [old])
        self.assertEqual(oct(os.stat(self.root / 'sec' / T / 'provider-key').st_mode & 0o777), '0o600')
    def test_failed_revoke_is_queued_and_retried_not_forgotten(self):
        old = self.store.provider_key(T); self.fail_delete = True; self.assertFalse(self.rotate()['old_key_revoked'])
        self.assertIn(old, (self.root / 'pending.json').read_text()); self.fail_delete = False
        self.assertEqual(retry_pending_revocations(self.keys, self.root / 'pending.json'), 1); self.assertEqual(retry_pending_revocations(self.keys, self.root / 'pending.json'), 0)
    def test_failed_issue_leaves_the_old_key_working(self):
        old = self.store.provider_key(T); self.keys.http = lambda *a: (500, {})
        with self.assertRaises(RotationError): self.rotate()
        self.assertEqual(self.store.provider_key(T), old)
    def test_nothing_to_rotate_is_an_error(self):
        with self.assertRaises(RotationError): rotate_provider_key(self.keys, self.store, 'aa-' + 'b2' * 16, 'x', max_budget_usd=1, duration_days=1, models=['m'], pending_path=self.root / 'p')
    def test_webhook_secrets_overlap_then_drop(self):
        path = self.root / 'wh'; a, b, c = ('whsec_' + ch * 20 for ch in 'abc')
        add_webhook_secret(path, a); self.assertEqual(add_webhook_secret(path, b), [a, b]); self.assertEqual(add_webhook_secret(path, b), [a, b])
        self.assertEqual(add_webhook_secret(path, c), [b, c])                          # never more than two active
        drop_old_webhook_secrets(path); self.assertEqual(path.read_text().split(), [c]); self.assertEqual(oct(os.stat(path).st_mode & 0o777), '0o600')
        with self.assertRaises(RotationError): add_webhook_secret(path, 'sk_test_' + 'a' * 20)
    def test_session_secret_rotation_changes_only_that_line(self):
        env = self.root / 'a.env'; env.write_text('KEEP=1\nAGENTAI_SESSION_SECRET=old\nOTHER=2\n')
        result = rotate_session_secret(env); text = env.read_text()
        self.assertTrue(result['sessions_invalidated']); self.assertIn('KEEP=1', text); self.assertIn('OTHER=2', text); self.assertNotIn('=old', text)
        with self.assertRaises(RotationError): rotate_session_secret(env, 'MISSING')
if __name__ == '__main__': unittest.main()
