"""One-use runtime proofs do not depend on transcript snapshots or turn claims."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest

from agentai_platform.lifecycle.tool_origin import inspect_origin, resolve
from agentai_platform.lifecycle.tool_origin_install import configure, install


class OriginChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.directory = self.root / 'tool-origins'
        self.directory.mkdir(mode=0o700)
        self.args = {'task': 'Read available colours', 'site': 'https://shop.example/product'}
        self.nonce = 'a' * 32
        self.proof = {'version': 2, 'name': 'lumina_browser', 'arguments': self.args,
                      'session_key': 'agent:main:s1', 'run_id': 'run-1', 'call_id': 'native-call-1',
                      'started_ms': time.time() * 1000}
        self.write()

    def write(self, nonce=None, **changes):
        path = self.directory / ((nonce or self.nonce) + '.json')
        path.write_text(json.dumps({**self.proof, **changes}))
        path.chmod(0o600)
        return path

    def inspect(self, **kw):
        return inspect_origin(self.root, 'lumina_browser', self.args, self.nonce, **kw)

    def test_runtime_identity_is_verified_without_any_transcript_database(self):
        result = self.inspect()
        self.assertEqual(result, {'status': 'verified', 'origin': {'session_key': 'agent:main:s1', 'run_id': 'run-1', 'call_id': 'native-call-1'}})
        self.assertFalse((self.directory / (self.nonce + '.json')).exists())

    def test_consumed_proof_cannot_be_replayed_across_requests_or_processes(self):
        self.assertIsNotNone(resolve(self.root, 'lumina_browser', self.args, self.nonce))
        self.assertEqual(self.inspect()['status'], 'proof_missing_or_consumed')

    def test_two_calls_with_identical_arguments_keep_their_own_native_identity(self):
        other = 'b' * 32
        self.write(other, session_key='agent:main:s2', run_id='run-2', call_id='native-call-2')
        self.assertEqual(resolve(self.root, 'lumina_browser', self.args, self.nonce)['run_id'], 'run-1')
        self.assertEqual(resolve(self.root, 'lumina_browser', self.args, other)['run_id'], 'run-2')

    def test_missing_or_model_invented_nonce_is_not_authority(self):
        for token in (None, '', 'fake', '../escape', 'f' * 32):
            self.assertIsNone(resolve(self.root, 'lumina_browser', self.args, token))

    def test_arguments_are_bound_to_the_proof(self):
        self.assertEqual(inspect_origin(self.root, 'lumina_browser', {'site': 'other.example'}, self.nonce)['status'], 'argument_mismatch')
        self.assertIsNotNone(self.inspect()['origin'])

    def test_expired_and_future_proofs_are_refused(self):
        for started in (time.time() * 1000 - 1801000, time.time() * 1000 + 60000, True, 'now'):
            self.write(started_ms=started)
            self.assertEqual(self.inspect()['status'], 'proof_expired')

    def test_invalid_runtime_identity_is_refused(self):
        for changes in ({'version': 1}, {'name': 'lumina_browser_step'}, {'session_key': ''}, {'run_id': None}, {'call_id': 'x' * 512}):
            self.write(**changes)
            self.assertEqual(self.inspect()['status'], 'proof_invalid')

    def test_world_readable_and_oversized_records_fail_closed(self):
        path = self.write(); path.chmod(0o644)
        self.assertEqual(self.inspect()['status'], 'proof_invalid')
        path.write_text('x' * 24001); path.chmod(0o600)
        self.assertEqual(self.inspect()['status'], 'proof_invalid')

    def test_invalid_json_and_non_object_records_fail_closed(self):
        path = self.write()
        for raw in ('bad json', '[]', 'null'):
            path.write_text(raw)
            self.assertIsNone(self.inspect()['origin'])

    def test_symlink_proofs_and_directories_are_not_followed(self):
        path = self.write(); external = self.root / 'outside.json'; path.rename(external); path.symlink_to(external)
        self.assertIsNone(self.inspect()['origin'])
        path.unlink(); self.directory.rmdir(); self.directory.symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(self.inspect()['origin'])

    def test_fifo_does_not_block_the_root_reader(self):
        path = self.write(); path.unlink(); os.mkfifo(path, 0o600)
        self.assertEqual(self.inspect()['status'], 'proof_invalid')

    def test_atomic_consumption_allows_only_one_parallel_caller(self):
        gate = threading.Barrier(2)
        def check(_):
            gate.wait()
            return self.inspect()['origin'] is not None
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(check, range(2))), [False, True])


class InstallChecks(unittest.TestCase):
    def test_installer_and_config_preserve_other_plugins_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = install(tmp)
            self.assertIn('before_tool_call', (target / 'index.mjs').read_text())
            original = {'plugins': {'allow': ['brave'], 'load': {'paths': ['/other']}, 'entries': {'brave': {'enabled': True}}}}
            config = configure(original, target)
            self.assertEqual(config['plugins']['allow'], ['brave', 'lumina-tool-origin'])
            self.assertTrue(config['plugins']['entries']['brave']['enabled'])
            self.assertEqual(configure(config, target), config)
            self.assertEqual(install(tmp), target)

    def test_installer_refuses_redirected_extension_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'extensions').symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError): install(root)

    def test_existing_cell_hook_wiring_does_not_wait_for_provider_model_refresh(self):
        from types import SimpleNamespace
        from agentai_platform.lifecycle.cell_config import CellProvisioner
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tenant = 'aa-' + 'a' * 32
            (root / tenant).mkdir()
            config = root / tenant / 'openclaw.json'
            config.write_text(json.dumps({'gateway': {'mode': 'local'}}))
            keys = SimpleNamespace(ensure_models=lambda *a: False)
            provisioner = CellProvisioner(keys, None, root, chown=lambda *a: None, tool_relay_url='http://tools.example/mcp')
            provisioner.before_start(SimpleNamespace(account_id='a', tenant_ref=tenant))
            actual = json.loads(config.read_text())
            self.assertTrue(actual['plugins']['entries']['lumina-tool-origin']['enabled'])
            self.assertTrue((root / tenant / 'extensions/lumina-tool-origin/index.mjs').is_file())


class McpSetupOriginChecks(unittest.TestCase):
    def test_setup_tools_require_and_consume_the_same_bound_proof(self):
        from agentai_platform.lifecycle.tool_origin import is_tool_name
        for name in ('lumina_mcp_search', 'lumina_mcp_setup', 'lumina_mcp_connections'):
            self.assertTrue(is_tool_name(name))
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)/'tool-origins';directory.mkdir(mode=0o700)
                nonce='a'*32;args={'url':'https://mcp.vercel.com'} if name=='lumina_mcp_setup' else {}
                proof={'version':2,'name':name,'arguments':args,'session_key':'session','run_id':'run','call_id':'call','started_ms':time.time()*1000}
                path=directory/(nonce+'.json');path.write_text(json.dumps(proof));path.chmod(0o600)
                self.assertEqual(inspect_origin(tmp,name,args,nonce)['status'],'verified')
                self.assertNotEqual(inspect_origin(tmp,name,args,nonce)['status'],'verified')
        self.assertFalse(is_tool_name('lumina_mcp_setup forged'))


class EveryRelayToolCanBeProven(unittest.TestCase):
    """The relay refuses a tool call it cannot prove came from the runtime's own hook. The bridge's name check and the cell plugin's name pattern must therefore cover every
    tool the relay serves. Until 2026-11-19 both held a fixed list that fell behind: the 28 mail, calendar, document, commitment, memory-correction and connected-service
    tools were refused for every real cell ("does not belong to an admitted live task")."""

    def served(self):
        from agentai_platform import connector_tools, file_tools, hub_tools, knowledge_tools, location, longterm_memory, show_tool, tool_relay
        from agentai_platform.mcp_connections import relay as remote
        names = set(tool_relay.TOOLS) | {tool_relay.PROGRESS_NAME, location.NAME, show_tool.NAME}
        names |= set(hub_tools.HubTools.names) | set(connector_tools.ConnectorTools.names) | set(file_tools.FileTools.names) | set(longterm_memory.MemoryTools.names)
        names |= set(knowledge_tools.KNOWLEDGE_NAMES) | set(knowledge_tools.COMMITMENT_NAMES) | set(knowledge_tools.DASHBOARD_NAMES)
        names |= {s['name'] for s in remote.GENERIC} | {'lumina_mcp_' + 'a' * 32 + '_' + 'b' * 12}
        return names

    def test_the_bridge_accepts_every_tool_the_relay_serves(self):
        from agentai_platform.lifecycle.tool_origin import is_tool_name
        names = self.served()
        self.assertGreaterEqual(len(names), 40)          # 42 on 2026-11-19; a floor so an empty collection cannot pass
        self.assertEqual(sorted(n for n in names if not is_tool_name(n)), [])

    def test_the_plugin_stamps_every_tool_the_relay_serves_and_nothing_else(self):
        source = (Path(__file__).resolve().parents[1] / 'agentai_platform/lifecycle/tool_origin_plugin/index.mjs').read_text()
        pattern = re.compile(re.search(r'const NAME = /(.+)/;', source).group(1))
        self.assertEqual(sorted(n for n in self.served() if not pattern.fullmatch('lumina__' + n)), [])
        for other in ('web_fetch', 'exec', 'lumina_browser', 'other__lumina_browser', 'lumina__Lumina_x', 'lumina__lumina-x', 'lumina__lumina_' + 'x' * 90):
            self.assertIsNone(pattern.fullmatch(other), other)
        self.assertNotIn('matcher:', source)          # OpenClaw's matcher takes exact names only: a list there would fall behind again

    def test_malformed_names_are_refused(self):
        from agentai_platform.lifecycle.tool_origin import is_tool_name
        for name in ('', 'browser', 'lumina_', 'lumina_Mail', 'lumina_mail-search', 'lumina__x', 'lumina_' + 'x' * 90, None, 7):
            self.assertFalse(is_tool_name(name), name)
