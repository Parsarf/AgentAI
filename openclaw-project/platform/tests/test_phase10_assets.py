import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
REQ = json.loads((ROOT / 'plans/product/requirements.json').read_text())
CASE_IDS = {r['acceptance_case'] for r in REQ['requirements'] if r.get('acceptance_case')}


class AssetChecks(unittest.TestCase):
    def test_fixture_cases_map_to_ledger_and_files_exist(self):
        cases = json.loads((ROOT / 'config/phase10-fixtures/cases.json').read_text())['cases']
        for case in cases:
            self.assertIn(case['acceptance_case'], CASE_IDS, case['id'])
            self.assertTrue(case['assertions'])
            for fixture in case['fixtures']:
                self.assertTrue((ROOT / fixture).exists(), fixture)

    def test_memory_fixture_has_twelve_unrelated_facts(self):
        data = json.loads((ROOT / 'config/phase10-fixtures/memory-12-facts.json').read_text())
        self.assertEqual(len(data['unrelated_facts']), 12)

    def test_required_procedures_present_with_frontmatter(self):
        for name in ('orchestration', 'deep-research', 'browser-task', 'software-project', 'debugging',
                     'untrusted-content', 'skill-improvement'):
            text = (ROOT / 'config/skills' / name / 'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: ' + name + '\n'), name)

    def test_harness_inventory_lists_blockers(self):
        inv = json.loads((ROOT / 'plans/product/phase-10-harness-inventory.json').read_text())
        self.assertTrue(inv['activation_blockers'])
        self.assertIn('acp-reviewer', inv['harnesses'])

    def test_claude_code_batches_are_safe_by_construction(self):
        pre = {x['path']: x['value'] for x in json.loads((ROOT / 'config/phase10-claude-code-preflight.batch.json').read_text())}
        act = {x['path']: x['value'] for x in json.loads((ROOT / 'config/phase10-claude-code-activation.batch.json').read_text())}
        self.assertFalse(pre['plugins.entries.acpx']['enabled'])
        self.assertFalse(pre['acp.enabled'])
        cfg = pre['plugins.entries.acpx']['config']
        self.assertEqual((cfg['permissionMode'], cfg['nonInteractivePermissions']), ('deny-all', 'deny'))
        self.assertFalse(cfg['pluginToolsMcpBridge'] or cfg['openClawToolsMcpBridge'])
        reviewer = act['agents.entries.claude-reviewer']
        self.assertEqual(reviewer['runtime']['acp']['mode'], 'oneshot')
        self.assertFalse({'write', 'edit', 'exec', 'process', 'apply_patch'} & set(reviewer['tools']['allow']))
        self.assertEqual(act['acp']['allowedAgents'], ['claude'])
        for name in ('claude-builder', 'claude-debugger'):
            tools = act['agents.entries.' + name]['tools']
            self.assertFalse(tools['elevated']['enabled'])
            self.assertTrue({'sessions_spawn', 'sessions_send', 'message', 'web_fetch', 'cron'} <= set(tools['deny']))
        self.assertIn('claude-sonnet-5-5', (ROOT / 'deploy/litellm.yaml').read_text())

    def test_dockerfile_requires_pins(self):
        text = (ROOT / 'deploy/Dockerfile.claude-code').read_text()
        self.assertIn('test -n "${CLAUDE_CODE_VERSION}"', text)
        self.assertFalse([l for l in text.splitlines() if l.startswith('RUN') and 'auth login' in l])


class Phase11Assets(unittest.TestCase):
    def test_permission_matrix_is_read_only_and_matches_catalog(self):
        from agentai_platform.connectors import CATALOG
        matrix = json.loads((ROOT / 'plans/product/phase-11-permission-matrix.json').read_text())
        for name, service in matrix['services'].items():
            for kind in ('send', 'share', 'write', 'delete'):
                self.assertIs(service.get(kind, False), False, name + ' ' + kind)
            self.assertIn(service['gate'], CASE_IDS, name)
        self.assertEqual({'gmail', 'calendar', 'drive', 'github'}, set(CATALOG) & set(matrix['services']))
        for name, entry in matrix['inventory'].items():
            if name != 'brave-search':
                self.assertFalse(entry['enabled'], name)
        self.assertIn('OWNER RUNTIME ONLY', matrix['inventory']['brave-search']['scope'])
        for name, service in CATALOG.items():
            allowed = {s.rsplit('/', 1)[-1] for s in service.allowed_scopes}
            self.assertTrue(set(matrix['services'][name]['scopes_allowed']) >= allowed - {'openid', 'email'} or name == 'github')

    def test_phase11_fixtures_map_to_ledger_and_exist(self):
        data = json.loads((ROOT / 'config/phase11-fixtures/cases.json').read_text())
        for case in data['cases']:
            self.assertIn(case['acceptance_case'], CASE_IDS, case['id'])
            self.assertTrue(case['assertions'])
            for fixture in case.get('fixtures', []):
                self.assertTrue((ROOT / fixture).exists(), fixture)
            if 'mock_covered_by' in case:
                self.assertTrue((ROOT / 'platform' / case['mock_covered_by'].split('platform/')[-1]).exists())


if __name__ == '__main__':
    unittest.main()
