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
        self.assertIn('html.duckduckgo.com', text); self.assertIn('never invent prices', text); self.assertIn('at most 5 pages', text)
        self.assertEqual({o[1:] for o in owners}, {(1000, 1000)})
