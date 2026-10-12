import unittest
import importlib.util
from pathlib import Path
from agentai_platform.billing import REQUIRED_EVENTS, WEBHOOK_PATH
spec = importlib.util.spec_from_file_location('billing_install', Path(__file__).resolve().parents[1] / 'deploy' / 'billing_install.py')
bi = importlib.util.module_from_spec(spec); spec.loader.exec_module(bi)

GOOD = {'STRIPE_SECRET_KEY': 'sk_test_' + 'a' * 24, 'STRIPE_WEBHOOK_SECRET': 'whsec_' + 'b' * 32, 'STRIPE_PRICE_ID': 'price_1AbCdE', 'STRIPE_API_VERSION': '2025-09-30.clover'}

class InstallChecks(unittest.TestCase):
    def test_good_test_configuration_passes_and_yields_only_verified_facts(self):
        problems, facts = bi.check_values(GOOD, REQUIRED_EVENTS)
        self.assertEqual(problems, []); self.assertEqual(set(facts), {'stripe_test_keys_present', 'webhook_secret_present', 'stripe_price_configured'})
        self.assertNotIn('webhook_endpoint_registered', facts)   # only the Stripe API check may set this
    def test_live_and_malformed_values_are_refused(self):
        for key, value in [('STRIPE_SECRET_KEY', 'sk_live_' + 'a' * 24), ('STRIPE_SECRET_KEY', ''), ('STRIPE_SECRET_KEY', 'pk_test_' + 'a' * 24),
                           ('STRIPE_WEBHOOK_SECRET', 'sk_test_' + 'a' * 24), ('STRIPE_PRICE_ID', 'prod_123456'), ('STRIPE_API_VERSION', 'latest')]:
            problems, facts = bi.check_values({**GOOD, key: value}, REQUIRED_EVENTS)
            self.assertTrue(problems, key)
        problems, _ = bi.check_values({**GOOD, 'STRIPE_SECRET_KEY': 'sk_live_' + 'a' * 24}, REQUIRED_EVENTS)
        self.assertIn('LIVE', problems[0])
        for text in bi.check_values({**GOOD, 'STRIPE_SECRET_KEY': 'sk_live_' + 'a' * 24}, REQUIRED_EVENTS)[0]: self.assertNotIn('aaaa', text)
    def test_endpoint_registration_needs_url_status_and_every_event(self):
        ep = {'url': bi.WEBHOOK_URL, 'status': 'enabled', 'enabled_events': list(REQUIRED_EVENTS)}
        self.assertTrue(bi.endpoint_registered([ep], REQUIRED_EVENTS))
        self.assertTrue(bi.endpoint_registered([{**ep, 'enabled_events': ['*']}], REQUIRED_EVENTS))
        for bad in [{**ep, 'status': 'disabled'}, {**ep, 'url': 'https://evil.example/v1/billing/webhook'}, {**ep, 'enabled_events': list(REQUIRED_EVENTS)[:-1]}]:
            self.assertFalse(bi.endpoint_registered([bad], REQUIRED_EVENTS))
        self.assertTrue(bi.WEBHOOK_URL.endswith(WEBHOOK_PATH))
    def test_env_merge_is_idempotent_and_preserves_unrelated_lines(self):
        base = 'A=1\nAGENTAI_BILLING_PRICE_ID=old\nB=2\n'
        updates = bi.account_env_lines({'key': '/k', 'secret': '/s', 'plan': '/p'}, 'price_new', '2025-09-30.clover')
        once = bi.merge_env(base, updates); twice = bi.merge_env(once, updates)
        self.assertEqual(once, twice); self.assertIn('A=1\n', once); self.assertIn('B=2\n', once)
        self.assertEqual(once.count('AGENTAI_BILLING_PRICE_ID='), 1); self.assertIn('AGENTAI_BILLING_PRICE_ID=price_new', once)
    def test_apply_steps_keep_secrets_out_of_commands_and_restrict_modes(self):
        paths, steps = bi.apply_steps({'key': '/tmp/k', 'secret': '/tmp/s', 'plan': '/tmp/p'}, 'price_x', '2025-09-30.clover')
        flat = ' '.join(' '.join(step[1:]) for step in steps)
        self.assertNotIn('sk_test', flat); self.assertNotIn('whsec_', flat)
        self.assertIn('install -d -m750 -o root -g agentai-platform', flat); self.assertIn('install -m640', flat); self.assertIn('shred -u', flat)
        self.assertEqual(steps[0][0], 'ssh'); self.assertTrue(all(p.startswith('/etc/agentai-platform/billing/') for p in paths.values()))
    def test_generated_merge_script_updates_settings_and_facts_in_place(self):
        import json, os, subprocess, sys, tempfile
        with tempfile.TemporaryDirectory() as d:
            env, facts = os.path.join(d, 'accounts.env'), os.path.join(d, 'facts.json')
            open(env, 'w').write('KEEP=1\nAGENTAI_BILLING_PRICE_ID=old\n'); os.chmod(env, 0o600)
            json.dump({'custody_backend': True}, open(facts, 'w'))
            code = bi.merge_script({'AGENTAI_BILLING_PRICE_ID': 'price_new', 'AGENTAI_BILLING_API_VERSION': '2025-09-30.clover'},
                                   {'stripe_test_keys_present': True}, env, facts)
            subprocess.run([sys.executable, '-c', code], check=True)
            text = open(env).read()
            self.assertIn('KEEP=1', text); self.assertIn('AGENTAI_BILLING_PRICE_ID=price_new', text); self.assertEqual(text.count('PRICE_ID'), 1)
            self.assertEqual(json.load(open(facts)), {'custody_backend': True, 'stripe_test_keys_present': True})
            self.assertEqual(os.stat(env).st_mode & 0o777, 0o600)
if __name__ == '__main__': unittest.main()
