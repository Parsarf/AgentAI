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
        self.assertEqual(cfg['agents']['defaults']['model']['primary'], 'litellm/claude-sonnet-5-5')            # the assistant that plans and answers
        ids = {m['id']: m for m in provider['models']}
        self.assertEqual(set(ids), {'claude-sonnet-5-5', 'claude-haiku-4-5', 'claude-sonnet-4-6'}); self.assertFalse(ids['claude-sonnet-5-5']['reasoning'])      # no hidden thinking tokens
        self.assertEqual(cfg['gateway'], {'mode': 'local'})

    def test_the_cells_own_browser_is_switched_on_only_when_asked_and_stays_out_of_the_assistants_reach(self):
        off = patch({})
        self.assertEqual(off['browser'], {'enabled': False})
        on = patch({}, native_browser=True)
        self.assertTrue(on['browser']['enabled']); self.assertTrue(on['browser']['headless']); self.assertTrue(on['browser']['noSandbox'])
        self.assertNotIn('ssrfPolicy', on['browser'])                                         # the default policy blocks private and internal addresses; nothing here opens it
        self.assertIn('browser', on['tools']['deny'])                                         # the assistant itself still cannot call it: it goes through Lumina's rules
        self.assertEqual(on['browser']['executablePath'], '/home/node/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome')       # the plugin is told where the image's Chromium is
        self.assertNotIn('ssrfPolicy', patch({'browser': {'ssrfPolicy': {'dangerouslyAllowPrivateNetwork': True}}}, native_browser=True)['browser'])      # never inherited from an earlier config

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
        self.assertEqual(calls[0][2]['max_budget'], 25); self.assertEqual(calls[0][2]['models'], ['claude-sonnet-5-5', 'claude-haiku-4-5', 'claude-sonnet-4-6'])
        prov.finish(binding)
        cfg = json.loads((cells / TENANT / 'openclaw.json').read_text())
        self.assertIn('litellm', cfg['models']['providers']); self.assertEqual(set(owners), {(1000, 1000)})
        self.assertNotIn('sk-testkey', json.dumps(cfg))

    def test_an_existing_assistant_is_brought_up_to_date_before_each_start(self):
        calls = []
        def http(method, path, body=None):
            calls.append((method, path, body)); return 200, {'key': 'sk-testkey-0123456789abcdef'}
        secrets = SecretStore(self.root / 'sec'); cells = self.root / 'cells'; (cells / TENANT).mkdir(parents=True)
        old = patch({'gateway': {'port': 1}}, default_model='litellm/claude-haiku-4-5'); old['models']['providers']['litellm']['models'] = old['models']['providers']['litellm']['models'][1:]   # created under the old setup
        (cells / TENANT / 'openclaw.json').write_text(json.dumps(old))
        prov = CellProvisioner(ProviderKeys(http, secrets), secrets, cells, chown=lambda p, u, g: None)
        binding = SimpleNamespace(tenant_ref=TENANT, account_id='acct')
        prov.prepare(binding); calls.clear()
        prov.before_start(binding)
        cfg = json.loads((cells / TENANT / 'openclaw.json').read_text())
        self.assertEqual(cfg['agents']['defaults']['model']['primary'], 'litellm/claude-sonnet-5-5'); self.assertEqual(cfg['gateway'], {'port': 1})       # only the model setup changed
        self.assertEqual([(m, path, body['models']) for m, path, body in calls], [('POST', '/key/update', ['claude-sonnet-5-5', 'claude-haiku-4-5', 'claude-sonnet-4-6'])])
        before = (cells / TENANT / 'openclaw.json').read_text(); prov.before_start(binding)
        self.assertEqual((cells / TENANT / 'openclaw.json').read_text(), before)                                                                         # idempotent

    def test_a_failure_in_the_update_never_blocks_the_start(self):
        def http(method, path, body=None): raise OSError('gateway down')
        secrets = SecretStore(self.root / 'sec'); cells = self.root / 'cells'; (cells / TENANT).mkdir(parents=True)
        secrets.store_provider_key(TENANT, 'sk-testkey-0123456789abcdef')
        (cells / TENANT / 'openclaw.json').write_text('not json')
        CellProvisioner(ProviderKeys(http, secrets), secrets, cells, chown=lambda p, u, g: None).before_start(SimpleNamespace(tenant_ref=TENANT, account_id='a'))   # no exception
        old = patch({'gateway': {'port': 1}}, default_model='litellm/claude-haiku-4-5'); (cells / TENANT / 'openclaw.json').write_text(json.dumps(old))
        CellProvisioner(ProviderKeys(http, secrets), secrets, cells, chown=lambda p, u, g: None).before_start(SimpleNamespace(tenant_ref=TENANT, account_id='a'))
        self.assertEqual(json.loads((cells / TENANT / 'openclaw.json').read_text()), old)                      # the key update failed, so the assistant keeps the model it can use
        self.assertEqual(ProviderKeys(lambda *a: (200, {}), secrets).ensure_models(TENANT.replace(TENANT[-1], '0'), ['x']), False)       # a tenant with no key is left alone
        with self.assertRaises(Exception): ProviderKeys(lambda *a: (500, {}), secrets).ensure_models(TENANT, ['x'])
        with self.assertRaises(Exception): ProviderKeys(lambda *a: (200, {}), secrets).ensure_models(TENANT, [])

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


class BrowserRelaySecretChecks(unittest.TestCase):
    """The browser plugin's own start writes a small secret with a rename-without-replace the sandbox rejects, so the host writes it first, exactly as the plugin's reader demands."""
    NAME = 'browser-extension-relay.secret'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        (self.root / TENANT).mkdir(parents=True)
        self.owners = []
        self.binding = SimpleNamespace(tenant_ref=TENANT, account_id='a')

    def prov(self, browser=True):
        return CellProvisioner(None, None, self.root, native_browser=browser, chown=lambda p, u, g: self.owners.append((Path(p).name, u, g)))

    def secret(self): return self.root / TENANT / 'credentials' / self.NAME

    def test_it_is_a_private_64_hex_file_owned_by_the_cells_user(self):
        self.prov().ensure_browser_relay_secret(self.binding)
        path = self.secret()
        self.assertRegex(path.read_text(), r'^[0-9a-f]{64}$')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600); self.assertEqual((path.parent.stat().st_mode & 0o777), 0o700)
        self.assertIn((self.NAME, 1000, 1000), self.owners); self.assertIn(('credentials', 1000, 1000), self.owners)
        self.assertEqual([p.name for p in path.parent.iterdir()], [self.NAME])                       # no temporary file is left behind

    def test_a_valid_secret_is_kept_and_a_broken_one_is_replaced(self):
        prov = self.prov(); prov.ensure_browser_relay_secret(self.binding)
        first = self.secret().read_text()
        prov.ensure_browser_relay_secret(self.binding)
        self.assertEqual(self.secret().read_text(), first)                                            # every start runs this; the token stays
        for broken in ('', 'not hex', 'ab' * 20, 'G' * 64):
            self.secret().write_text(broken)
            prov.ensure_browser_relay_secret(self.binding)
            self.assertRegex(self.secret().read_text(), r'^[0-9a-f]{64}$', broken)
            self.assertEqual(self.secret().stat().st_mode & 0o777, 0o600)

    def test_a_link_in_its_place_is_never_followed(self):
        outside = self.root / 'outside'; outside.write_text('keep')
        (self.root / TENANT / 'credentials').mkdir()
        self.secret().symlink_to(outside)
        self.prov().ensure_browser_relay_secret(self.binding)
        self.assertEqual(outside.read_text(), 'keep'); self.assertFalse(self.secret().is_symlink())
        self.assertRegex(self.secret().read_text(), r'^[0-9a-f]{64}$')

    def test_nothing_is_written_when_the_cells_browser_is_off(self):
        self.prov(browser=False).ensure_browser_relay_secret(self.binding)
        self.assertFalse((self.root / TENANT / 'credentials').exists())

    def test_it_runs_on_every_start_and_after_create_and_a_failure_never_blocks_a_start(self):
        (self.root / TENANT / 'openclaw.json').write_text('{}')
        prov = self.prov(); prov.finish(self.binding)
        self.assertTrue(self.secret().is_file())                                                      # after create
        self.secret().unlink()
        class NoKeys:
            def ensure_models(self, *a): return False                                                  # a cell with no key in custody returns early from before_start
        started = CellProvisioner(NoKeys(), None, self.root, native_browser=True, chown=lambda *a: None)
        started.before_start(self.binding)
        self.assertTrue(self.secret().is_file())                                                      # before every start, whatever else is true of the cell
        def refuse(*a): raise OSError('read-only')
        broken = CellProvisioner(NoKeys(), None, self.root, native_browser=True, chown=refuse)
        broken.before_start(self.binding)                                                              # no exception: the start itself goes on


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

    def test_rules_use_one_registry_protocol_and_on_demand_schema_files(self):
        from agentai_platform.lifecycle.cell_config import WORKSPACE_RULES as rules
        self.assertIn('lumina-doc', rules)
        self.assertIn('lumina-ui/components/', rules)
        self.assertNotIn('```lumina\n', rules)
        self.assertIn('Use plain text', rules)

    def test_written_component_schemas_and_examples_match_the_registry(self):
        from agentai_platform.genui.document import registry, validate_block
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); (root / TENANT).mkdir()
        prov = CellProvisioner(None, None, root, chown=lambda *args: None)
        prov.write_rules(SimpleNamespace(tenant_ref=TENANT))
        for component in registry()['offered']:
            saved = json.loads((root / TENANT / 'workspace' / 'lumina-ui' / 'components' / (component + '.json')).read_text())
            self.assertEqual(saved['componentId'], component)
            validate_block(saved['example'], saved['exampleDatasets'])

    def test_cell_validator_reports_corrective_errors_without_a_server_connection(self):
        import subprocess, sys
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); (root / TENANT).mkdir()
        CellProvisioner(None, None, root, chown=lambda *args: None).write_rules(SimpleNamespace(tenant_ref=TENANT))
        ui = root / TENANT / 'workspace' / 'lumina-ui'
        draft = ui / 'draft.json'
        draft.write_text(json.dumps({'version': '1.0', 'responseId': 'check', 'blocks': [{'id': 'x', 'type': 'script', 'props': {}}]}))
        result = subprocess.run([sys.executable, str(ui / 'validate.py'), str(draft)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['valid'])
        self.assertIn('error', json.loads(result.stdout))


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

    def test_a_rotated_key_reaches_a_cell_that_already_has_search_without_reinstalling_the_plugin(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        self.assertTrue(self.prov().setup_search(binding)); self.calls.clear()
        self.assertTrue(self.prov().setup_search(binding)); self.assertEqual(self.calls, [])                  # same key: nothing to do
        self.key.write_text('BSA-the-NEW-key-after-rotation\n')
        self.assertTrue(self.prov().setup_search(binding))
        flat = [' '.join(a) for a, _ in self.calls]
        self.assertEqual([i for _, i in self.calls if i], ['BSA-the-NEW-key-after-rotation\n'])             # the new key, on stdin
        self.assertFalse(any('plugins install' in c for c in flat))                                          # no reinstall, no config churn
        self.assertNotIn('NEW-key', ' '.join(flat)); self.calls.clear()
        self.assertTrue(self.prov().setup_search(binding)); self.assertEqual(self.calls, [])                  # and it is remembered
        marker = (self.root / TENANT / 'workspace' / '.search-2026.9.6').read_text()
        self.assertNotIn('BSA', marker); self.assertNotIn('NEW', marker)                                      # the marker never holds the key

    def test_a_cell_set_up_before_keys_were_tracked_gets_one_key_refresh_and_a_failed_refresh_is_retried(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        (self.root / TENANT / 'workspace' / '.search-2026.9.6').write_text('ok\n')                           # the old marker
        self.assertTrue(self.prov().setup_search(binding))
        self.assertEqual(len([i for _, i in self.calls if i]), 1); self.assertFalse(any('plugins install' in ' '.join(a) for a, _ in self.calls))
        self.key.write_text('BSA-another-key\n'); self.calls.clear()
        def failing(argv, input_text=None):
            self.calls.append((list(argv), input_text)); return (1, '') if input_text else (0, '')
        broken = CellProvisioner(None, None, self.root, run=failing, search_key_file=self.key, chown=lambda *a: None, sleep=lambda s: None)
        self.assertFalse(broken.setup_search(binding))                                                         # the cell keeps its key and says so
        self.calls.clear(); self.assertTrue(self.prov().setup_search(binding)); self.assertEqual(len([i for _, i in self.calls if i]), 1)   # the next start tries again

    def test_an_unreadable_key_file_leaves_a_working_cell_alone(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        self.assertTrue(self.prov().setup_search(binding)); self.calls.clear()
        self.key.unlink()
        self.assertTrue(self.prov().setup_search(binding)); self.assertEqual(self.calls, [])
        fresh = SimpleNamespace(tenant_ref='other-tenant'); (self.root / 'other-tenant' / 'workspace').mkdir(parents=True)
        self.assertFalse(self.prov().setup_search(fresh))

    def test_waits_for_the_gateway_then_gives_up_without_leaving_a_marker(self):
        binding = SimpleNamespace(tenant_ref=TENANT)
        self.assertTrue(self.prov(fail_installs=3).setup_search(binding))                           # retried until the gateway answered
        for f in (self.root / TENANT / 'workspace').glob('.search-*'): f.unlink()
        self.assertFalse(self.prov(fail_installs=99).setup_search(binding, attempts=3))
        self.assertEqual(list((self.root / TENANT / 'workspace').glob('.search-*')), [])
        self.key.write_text('\n')
        self.assertFalse(self.prov().setup_search(binding))                                         # no key: nothing is installed
