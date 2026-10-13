import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from agentai_platform.lifecycle.cell_config import CellProvisioner, patch
from agentai_platform.lifecycle.litellm_admin import LiteLLMAdmin
from agentai_platform.lifecycle.secrets_custody import ProviderKeys, SecretStore

TENANT = 'aa-' + 'b' * 32


class Resp:
    def __init__(self, body, status=200): self.body, self.status = json.dumps(body).encode(), status
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self.body
    def __iter__(self): return iter([self.body])


class CellConfigChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)

    def test_patch_routes_the_cell_to_the_host_relay_with_an_env_key(self):
        cfg = patch({'gateway': {'mode': 'local'}})
        provider = cfg['models']['providers']['litellm']
        self.assertEqual(provider['baseUrl'], 'http://10.77.0.1:4000')
        self.assertEqual(provider['apiKey']['id'], 'LITELLM_API_KEY')               # the key is never written into the file
        self.assertEqual(cfg['agents']['defaults']['model']['primary'], 'litellm/claude-haiku-4-5')
        self.assertEqual(cfg['gateway'], {'mode': 'local'})

    def test_provisioner_issues_one_key_and_patches_config_atomically(self):
        calls = []
        def http(method, path, body=None):
            calls.append((method, path, body)); return 200, {'key': 'sk-testkey-0123456789abcdef'}
        secrets = SecretStore(self.root / 'sec')
        cells = self.root / 'cells'; (cells / TENANT).mkdir(parents=True)
        (cells / TENANT / 'openclaw.json').write_text(json.dumps({'gateway': {'port': 18789}}))
        owners = []
        prov = CellProvisioner(ProviderKeys(http, secrets), secrets, cells, chown=lambda p, u, g: owners.append((u, g)))
        binding = SimpleNamespace(tenant_ref=TENANT, account_id='acct')
        self.assertEqual(prov.prepare(binding), ['--env', 'LITELLM_API_KEY=sk-testkey-0123456789abcdef'])
        self.assertEqual(prov.prepare(binding), ['--env', 'LITELLM_API_KEY=sk-testkey-0123456789abcdef'])   # retry reuses the key
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2]['max_budget'], 25); self.assertIn('claude-haiku-4-5', calls[0][2]['models'])
        prov.finish(binding)
        cfg = json.loads((cells / TENANT / 'openclaw.json').read_text())
        self.assertIn('litellm', cfg['models']['providers']); self.assertEqual(set(owners), {(1000, 1000)})
        self.assertNotIn('sk-testkey', json.dumps(cfg))

    def test_admin_reads_master_key_at_call_time_and_converts_spend(self):
        env = self.root / 'l.env'; env.write_text('X=1\nLITELLM_MASTER_KEY=sk-master\n')
        seen = []
        def opener(request, timeout=0):
            seen.append(request.get_header('Authorization')); return Resp({'info': {'spend': 0.0153}})
        self.assertEqual(LiteLLMAdmin(env, opener=opener).key_spend_microusd('sk-abc'), 15300)
        self.assertEqual(seen, ['Bearer sk-master'])
        bad = LiteLLMAdmin(env, opener=lambda r, timeout=0: Resp({}, 404))
        with self.assertRaises(RuntimeError): bad.key_spend_microusd('sk-abc')


if __name__ == '__main__':
    unittest.main()


class ResolverChecks(unittest.TestCase):
    def test_after_start_rewrites_resolv_conf_in_place(self):
        import os
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / 'var/lib/agentai-cells/docker/containers/abc'; d.mkdir(parents=True)
        conf = d / 'resolv.conf'; conf.write_text('nameserver 127.0.0.11\n# long generated comment line to be fully replaced ' * 3)
        inode = conf.stat().st_ino
        import agentai_platform.lifecycle.cell_config as cc
        prov = CellProvisioner(None, None, tmp.name, run=lambda argv: (0, '/var/lib/agentai-cells/docker/containers/abc/resolv.conf\n'))
        real_open = open
        import builtins
        builtins_open = builtins.open
        def redirect(path, *a, **k):
            return builtins_open(str(Path(tmp.name)) + str(path), *a, **k) if str(path).startswith('/var/lib/agentai-cells') else builtins_open(path, *a, **k)
        builtins.open = redirect
        try:
            prov.after_start(SimpleNamespace(tenant_ref=TENANT))
        finally:
            builtins.open = builtins_open
        self.assertEqual(conf.read_text(), 'nameserver 1.1.1.1\nnameserver 9.9.9.9\noptions ndots:0\n')
        self.assertEqual(conf.stat().st_ino, inode)
        with self.assertRaises(RuntimeError):
            CellProvisioner(None, None, tmp.name, run=lambda argv: (0, '/etc/passwd\n')).after_start(SimpleNamespace(tenant_ref=TENANT))


class RulesChecks(unittest.TestCase):
    def test_workspace_rules_are_written_idempotently_with_the_cell_owner(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / TENANT).mkdir(parents=True)
        owners = []
        prov = CellProvisioner(None, None, tmp.name, chown=lambda p, u, g: owners.append((str(p).split('/')[-1], u, g)))
        binding = SimpleNamespace(tenant_ref=TENANT)
        prov.write_rules(binding); prov.write_rules(binding)
        text = (Path(tmp.name) / TENANT / 'workspace' / 'AGENTS.md').read_text()
        self.assertIn('web_search', text); self.assertIn('never invent prices', text); self.assertIn('do not scrape search-engine pages', text)
        self.assertEqual({o[1:] for o in owners}, {(1000, 1000)})


class SearchSetupChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        (self.root / TENANT / 'workspace').mkdir(parents=True)
        self.key = self.root / 'brave.key'; self.key.write_text('BSA-secret-search-key\n')
        self.calls = []

    def prov(self, fail_installs=0):
        left = [fail_installs]
        def run(argv, input_text=None):
            self.calls.append((list(argv), input_text))
            if 'install' in argv and left[0] > 0:
                left[0] -= 1; return 1, 'gateway not ready'
            return 0, ''
        return CellProvisioner(None, None, self.root, run=run, search_key_file=self.key, chown=lambda *a: None, sleep=lambda s: None)

    def test_installs_the_pinned_plugin_enables_it_and_passes_the_key_only_on_stdin(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        self.assertTrue(self.prov().setup_search(binding))
        flat = [' '.join(a) for a, _ in self.calls]
        self.assertTrue(any('plugins install @openclaw/brave-plugin@2026.9.6 --force' in c for c in flat))
        self.assertTrue(any('config set tools.web.search.provider brave' in c for c in flat))
        self.assertNotIn('BSA-secret-search-key', ' '.join(flat))                                  # never on a command line
        self.assertEqual([i for _, i in self.calls if i], ['BSA-secret-search-key\n'])
        self.assertTrue(all(f'openclaw-cell-{TENANT}' in c for c in flat))
        self.calls.clear()
        self.assertTrue(self.prov().setup_search(binding)); self.assertEqual(self.calls, [])      # marker: second start does nothing

    def test_waits_for_the_gateway_then_gives_up_without_leaving_a_marker(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        self.assertTrue(self.prov(fail_installs=3).setup_search(binding))                           # retried until the gateway answered
        for f in (self.root / TENANT / 'workspace').glob('.search-*'): f.unlink()
        self.assertFalse(self.prov(fail_installs=99).setup_search(binding, attempts=3))
        self.assertEqual(list((self.root / TENANT / 'workspace').glob('.search-*')), [])
        self.key.write_text('\n')
        self.assertFalse(self.prov().setup_search(binding))                                         # no key: nothing is installed
